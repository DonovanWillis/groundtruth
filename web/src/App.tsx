import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AgentResponse, Bbox, Envelope, FC, Feature, Health, cellBboxOf, exampleOf, geomBbox, health, setThumbAoi, shapeOf, sleep, tool,
} from "./api";
import { AgentTarget, runPlanner } from "./agent";
import { CONTEXT_LAYERS, SUGGESTIONS } from "./config";
import { MapView, unionBbox } from "./mapview";
import { Candidates, Msg, ResultCard, capital, cleanSay, countOf, measureLine, stepLine } from "./turns";
import { Composer, Thread } from "./Chat";
import { Compose, Layers, Minus, Plus } from "./icons";

type Phase = "landing" | "chat";
const PANEL_INSET = 432;            // left panel (12 + 400) + breathing room the camera keeps clear
const OUTLINE_BATCH = 24, OUTLINE_POLL_MS = 2500, OUTLINE_POLL_MAX = 40;
const isPending = (f: Feature) => f.properties.geometry_kind === "box" || f.properties.geometry_kind === "cell";
const reduceMotion = () => !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

export default function App() {
  const [hl, setHl] = useState<Health | null>(null);
  const [year, setYear] = useState(2022);
  const [aoi, setAoi] = useState("");
  setThumbAoi(aoi);
  const [phase, setPhase] = useState<Phase>("landing");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [busy, setBusy] = useState(false);
  const [brain, setBrain] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [outlines, setOutlines] = useState<Record<string, { geometry: GeoJSON.Geometry; area_m2: number | null }>>({});

  const mapEl = useRef<HTMLDivElement>(null);
  const mv = useRef<MapView | null>(null);
  const ctx = useRef<{ place: string | null; last_text: string | null }>({ place: null, last_text: null });
  const nextId = useRef(1);
  const busyRef = useRef(false);
  const runRef = useRef(0);

  // ---------------- boot ----------------
  useEffect(() => {
    health().then((h) => {
      setHl(h);
      const qs = new URLSearchParams(window.location.search);
      const y = Number(qs.get("year")) || h.primary_year;
      setYear(y); setAoi(qs.get("aoi") ?? defaultAoi(h, y));
    }).catch(() => setHl(null));
  }, []);

  useEffect(() => {
    const m = new MapView(mapEl.current!);
    mv.current = m;
    // landing: a still aerial of the county core, sized so imagery fills the window (the page blurs it)
    const z = 12 + Math.log2(Math.max(window.innerWidth / 1440, window.innerHeight / 900, 0.6));
    m.map.jumpTo({ center: [-80.843, 35.222], zoom: z });
    m.setLanding(true);
    m.onResultClick = (ex) => setSel(ex);
    const ro = new ResizeObserver(() => m.resize());
    ro.observe(mapEl.current!);
    const qs = new URLSearchParams(window.location.search);
    const hb = qs.has("shot") ? setInterval(() => m.map.triggerRepaint(), 1000) : undefined;
    return () => { clearInterval(hb); ro.disconnect(); m.remove(); mv.current = null; };
  }, []);
  useEffect(() => { if (year) mv.current?.setYear(year); }, [year]);

  // ---------------- map: the active card's results ----------------
  const active = useMemo(() => {
    const m = msgs.find((x) => x.id === activeId);
    return m && m.role === "assistant" ? m.card : null;
  }, [msgs, activeId]);
  useEffect(() => {
    if (!active) { mv.current?.setResults({ type: "FeatureCollection", features: [] }); return; }
    const feats: Feature[] = active.fc.features.map((f) => {
      const ex = exampleOf(f), o = outlines[ex];
      const pending = !o && isPending(f);
      return { type: "Feature" as const, geometry: o?.geometry ?? (pending ? shapeOf(f) : f.geometry), properties: {
        example: ex, kind: pending ? "cell" : "outline", state: "hit", area_m2: o?.area_m2 ?? f.properties.area_m2 ?? null,
        change: "", sel: sel === ex, dim: !!active.keep && !active.keep.has(ex) } };
    }).filter((f) => f.geometry);
    mv.current?.setResults({ type: "FeatureCollection", features: feats }, { exhaustive: active.exhaustive });
  }, [active, outlines, sel]);

  /** Swap in outlines for results still shown as cells (cached SAM 2 outlines only; light, one call at a time). */
  const streamOutlines = useCallback(async (card: ResultCard, run: number) => {
    const done = new Set<string>();
    for (let i = 0; i < OUTLINE_POLL_MAX && runRef.current === run; i++) {
      const pend = card.fc.features.filter((f) => isPending(f) && !done.has(exampleOf(f)));
      if (!pend.length) return;
      try {
        const env = await tool("outline", { year, aoi: aoi || undefined, examples: pend.slice(0, OUTLINE_BATCH).map(exampleOf),
          max: OUTLINE_BATCH, cached_only: true, concept: card.env.result.metrics.concept ?? undefined });
        if (runRef.current !== run || env.status === "declined") return;
        const got: Record<string, { geometry: GeoJSON.Geometry; area_m2: number | null }> = {};
        for (const f of env.result.geojson.features) if (f.geometry) {
          const ex = (f.properties.example as string) ?? String(f.id); got[ex] = { geometry: f.geometry, area_m2: f.properties.area_m2 ?? null }; done.add(ex);
        }
        for (const r of env.result.metrics.rejected ?? []) done.add(String(r));
        if (Object.keys(got).length) setOutlines((o) => ({ ...o, ...got }));
      } catch { return; }
      await sleep(OUTLINE_POLL_MS);
    }
  }, [year, aoi]);

  // ---------------- conversation ----------------
  const patch = (id: number, p: Partial<Extract<Msg, { role: "assistant" }>>) =>
    setMsgs((l) => l.map((m) => (m.id === id && m.role === "assistant" ? { ...m, ...p } : m)));

  const enterChat = useCallback(() => {
    if (!mv.current) return;
    mv.current.inset = PANEL_INSET;
    mv.current.setLanding(false);
    setPhase("chat");
  }, []);

  const send = useCallback(async (raw: string) => {
    const text = raw.trim();
    if (!text || busyRef.current) return;
    busyRef.current = true; setBusy(true);
    enterChat();
    const uid = nextId.current++, aid = nextId.current++;
    setMsgs((l) => [...l, { id: uid, role: "user", text },
      { id: aid, role: "assistant", pending: true, text: "", steps: [], card: null, cands: null, places: [], error: null, declined: false }]);
    const run = ++runRef.current;
    let res: AgentResponse | null = null;
    let envs: Record<string, Envelope> = {};
    const says: string[] = [];
    let flew = false, resultEnv: Envelope | null = null, keep: Set<string> | null = null, metrics: Record<string, any> | null = null;
    let download: ResultCard["download"] = null, cands: Candidates | null = null, places: string[] = [], heat = false;
    const target: AgentTarget = {
      flyTo: (bbox) => { flew = true; mv.current?.fitBbox(bbox, { maxZoom: 15 }); },
      addLayer: (layerId, env) => {
        const def = CONTEXT_LAYERS.find((c) => c.key === layerId || c.key === `osm_${layerId}`);
        if (def) mv.current?.setContext(def, env.result.geojson, true); else mv.current?.setAgentLayer(layerId, env.result.geojson);
      },
      showCandidates: (env) => {
        const p = res?.plan ?? {};
        const feats = env.result.geojson.features;
        const chosen = (p.chosen_example as string) ?? feats.find((f) => f.properties.sense_id === p.chosen_sense)?.properties.example ?? null;
        cands = { feats, chosen, nots: [], concept: env.result.metrics.sense_list ?? null, place: p.place ?? null };
      },
      showMetrics: (env) => { metrics = env.result.metrics; },
      offerDownload: (env, format) => { const url = env.result.metrics.download; if (url) download = { url, format: format ?? env.result.metrics.format ?? "csv" }; },
      addResults: (_l, env) => { resultEnv = env; },
      setFilter: (_l, env) => { keep = new Set(env.result.geojson.features.map(exampleOf)); },
      heatmap: (env) => { heat = true; mv.current?.setHeat(env.result.geojson);
        const b = unionBbox(env.result.geojson.features.filter((f) => f.geometry).map((f) => geomBbox(f.geometry)));
        if (b && !flew) mv.current?.fitBbox(b, { maxZoom: 11.6, padding: 80 }); },
      suggestPlaces: (ps) => { places = ps; },
      say: (t) => says.push(cleanSay(t)),
    };
    try {
      res = await runPlanner(text, target, {
        aoi: aoi || undefined, context: { ...ctx.current },
        onError: (e) => console.warn("action:", e),
        onResponse: (r, ar) => { res = r; envs = ar.envelopes; },
      });
      const r = res;
      const plan = r.plan ?? {};
      setBrain(r.brain ?? r.planner ?? null);
      if (r.status !== "declined" && !plan.exported_from) {
        ctx.current = { place: plan.place ?? ctx.current.place, last_text: plan.effective_text ?? text };
      }
      if (!heat) mv.current?.setHeat(null);
      let card: ResultCard | null = null;
      const rEnv = resultEnv as Envelope | null;
      if (rEnv) {
        const countEnv = (r.current_ref && envs[r.current_ref]) || rEnv;
        const full = rEnv.result.metrics.mode !== "ranked_top_k", exhaustive = rEnv.result.metrics.mode === "exhaustive_scan";
        const sources = [...new Map(Object.values(envs).flatMap((e) => e.sources ?? []).map((s) => [s.name, s])).values()];
        card = { title: capital(String(plan.effective_text ?? text)), count: countOf(countEnv), countLabel: full ? "found" : "top matches",
          sub: measureLine(metrics ?? rEnv.result.metrics), fc: rEnv.result.geojson, keep, exhaustive, env: countEnv, sources, download,
          place: plan.place ?? null };
        if (!flew) {
          const b = unionBbox(rEnv.result.geojson.features.slice(0, 200).map(cellBboxOf).filter((x) => x.every(Number.isFinite)));
          if (b) mv.current?.fitBbox(b, { padding: 70, maxZoom: 16 });
        }
        setActiveId(aid); setSel(null);
        streamOutlines(card, run);
      } else if (heat) setActiveId(null);
      const declined = r.status === "declined";
      const reason = Object.values(envs).find((e) => e.status === "declined")?.declined_reason;
      patch(aid, { pending: false, text: says.join(" ") || (declined ? `I can't do that one${reason ? `: ${reason}` : "."}` : card ? "" : "Done."),
        steps: (r.steps ?? []).map((s) => stepLine(s.tool, s.envelope)), card, cands, places, declined });
    } catch (e) {
      patch(aid, { pending: false, error: String(e).replace(/^Error:\s*/, "") });
    } finally { busyRef.current = false; setBusy(false); }
  }, [aoi, enterChat, streamOutlines]);

  /** Ambiguity grid: pick a meaning (or mark one "not this") → find_all with that example; a new assistant turn. */
  const pickSense = useCallback(async (msgId: number, c: Candidates, example: string, nots: string[]) => {
    if (busyRef.current) return;
    busyRef.current = true; setBusy(true);
    patch(msgId, { cands: { ...c, chosen: example, nots } });
    const aid = nextId.current++;
    const label = c.feats.find((f) => f.properties.example === example)?.properties.sense_label ?? "that";
    setMsgs((l) => [...l, { id: aid, role: "assistant", pending: true, text: "", steps: [], card: null, cands: null, places: [], error: null, declined: false }]);
    const run = ++runRef.current;
    try {
      const soft = c.feats.filter((f) => !f.properties.no_clear_example && f.properties.example !== example && !nots.includes(f.properties.example))
        .map((f) => f.properties.example as string);
      const env = await tool("find_all", { year, aoi: aoi || undefined, examples: [example], exclude: nots, soft_exclude: soft, k: 200,
        concept: c.concept ?? undefined, rerank: true, outline_top: 200, ...(c.place ? { place: c.place } : {}) });
      if (env.status === "declined") { patch(aid, { pending: false, declined: true, text: `I can't do that one: ${env.declined_reason}` }); return; }
      const full = env.result.metrics.mode !== "ranked_top_k", exhaustive = env.result.metrics.mode === "exhaustive_scan";
      const card: ResultCard = { title: `${label}${c.place ? ` · ${c.place}` : ""}`, count: countOf(env), countLabel: full ? "found" : "top matches",
        sub: measureLine(env.result.metrics), fc: env.result.geojson, keep: null, exhaustive, env, sources: env.sources, download: null, place: c.place };
      patch(aid, { pending: false, text: `Here are the ${label.toLowerCase()} results.`, steps: [stepLine("find_all", env)], card });
      setActiveId(aid); setSel(null); mv.current?.setHeat(null);
      const b = unionBbox(env.result.geojson.features.slice(0, 200).map(cellBboxOf));
      if (b) mv.current?.fitBbox(b, { padding: 70, maxZoom: 16 });
      streamOutlines(card, run);
    } catch (e) { patch(aid, { pending: false, error: String(e).replace(/^Error:\s*/, "") }); }
    finally { busyRef.current = false; setBusy(false); }
  }, [year, aoi, streamOutlines]);

  const viewCard = useCallback((id: number, card: ResultCard) => {
    setActiveId(id); setSel(null); mv.current?.setHeat(null);
    const b = unionBbox(card.fc.features.slice(0, 200).map(cellBboxOf).filter((x) => x.every(Number.isFinite)));
    if (b) mv.current?.fitBbox(b, { padding: 70, maxZoom: 16 });
  }, []);
  const viewFeature = useCallback((id: number, f: Feature) => {
    setActiveId(id); setSel(exampleOf(f)); mv.current?.setHeat(null);
    mv.current?.fitBbox(f.properties.chip_bbox ?? cellBboxOf(f), { maxZoom: 18.5, padding: 40 });
  }, []);

  const newChat = () => {
    runRef.current++; setMsgs([]); setActiveId(null); setSel(null); setOutlines({});
    ctx.current = { place: null, last_text: null }; mv.current?.setHeat(null);
  };

  // deep link: ?agent=run&prompt=… (kept for the screenshot scripts) or ?q=…
  const linked = useRef(false);
  useEffect(() => {
    if (linked.current || !hl || !aoi) return;
    const qs = new URLSearchParams(window.location.search);
    const p = qs.get("q") ?? (qs.get("agent") ? qs.get("prompt") : null);
    linked.current = true;
    if (p) send(p);
  }, [hl, aoi, send]);

  const years = hl ? new Set(hl.indexes.map((i) => i.year)) : new Set<number>([2022]);
  const lastSources = useMemo(() => {
    for (let i = msgs.length - 1; i >= 0; i--) { const m = msgs[i]; if (m.role === "assistant" && m.card) return m.card.sources; }
    return [];
  }, [msgs]);

  return (
    <div className={`app ${phase}`}>
      <div className="mapwrap"><div ref={mapEl} className="map" /></div>
      <div className="veil" aria-hidden />

      <div className="wordmark">Groundtruth</div>

      <section className="shell" aria-label="Conversation">
        <header className="shell-head">
          <span className="sr-only">Groundtruth</span>
          <button className="icon-btn" title="New conversation" aria-label="New conversation" onClick={newChat} disabled={busy}><Compose /></button>
        </header>
        <Thread msgs={msgs} activeId={activeId} busy={busy} year={year} aoi={aoi}
          onSend={send} onView={viewCard} onFeature={viewFeature} onPick={pickSense} />
        <Composer onSend={send} busy={busy} year={year} autoFocus compact={phase === "chat"} />
        <footer className="foot">
          {brain ? <>Answered by {brain}</> : <>Rules planner or local model</>}
          {" · "}{lastSources.length ? lastSources.map((s) => s.name).join(", ") : `USDA NAIP ${year}`}
        </footer>
      </section>

      <div className="suggest" aria-label="Suggestions">
        {SUGGESTIONS.map((s) => <button key={s} className="pill" onClick={() => send(s)} tabIndex={phase === "landing" ? 0 : -1}>{s}</button>)}
      </div>

      <MapControls mv={mv} year={year} years={years} onYear={(y) => { setYear(y); if (hl) setAoi(defaultAoi(hl, y)); }} />
    </div>
  );
}

function defaultAoi(h: Health, y: number) {
  const idx = h.indexes.filter((i) => i.year === y);
  return idx.find((i) => i.aoi === "county")?.aoi ?? [...idx].sort((a, b) => b.chips - a.chips)[0]?.aoi ?? "";
}

// ---------------- map controls: one floating pill (year · layers · 2D) + zoom ----------------
function MapControls({ mv, year, years, onYear }: {
  mv: React.MutableRefObject<MapView | null>; year: number; years: Set<number>; onYear: (y: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const [on, setOn] = useState<Record<string, boolean>>({});
  const [spot, setSpot] = useState(true);
  const cache = useRef<Record<string, FC>>({});
  const toggle = async (key: string, v: boolean) => {
    const def = CONTEXT_LAYERS.find((c) => c.key === key);
    if (!def || !mv.current) return;
    setOn((s) => ({ ...s, [key]: v }));
    try {
      const vector = await mv.current.hasVector(key);
      if (!vector && def.vectorOnly) throw new Error("no tiles");
      if (v && !vector && !cache.current[key]) {
        let bbox: Bbox | undefined;
        if (def.bboxed) { const [w, s, e, n] = mv.current.bounds(); const dx = (e - w) * 1.5, dy = (n - s) * 1.5; bbox = [w - dx, s - dy, e + dx, n + dy]; }
        const env = await tool("add_layer", { name: key, ...(bbox ? { bbox } : {}) });
        if (env.status === "declined") throw new Error(String(env.declined_reason));
        cache.current[key] = env.result.geojson;
      }
      await mv.current.setContext(def, v ? cache.current[key] ?? null : null, v);
    } catch { setOn((s) => ({ ...s, [key]: false })); }
  };
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!(e.target as HTMLElement).closest(".mapctl")) setOpen(false); };
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [open]);
  return (
    <>
      <div className="mapctl">
        <div className="seg" role="group" aria-label="Imagery year">
          {[2022, 2020].map((y) => <button key={y} className={y === year ? "on" : ""} disabled={!years.has(y)} onClick={() => onYear(y)}
            title={years.has(y) ? `NAIP ${y}` : `No ${y} index yet`}>{y}</button>)}
        </div>
        <span className="sep" />
        <button className={`ctl ${open ? "on" : ""}`} onClick={() => setOpen(!open)} aria-expanded={open} title="Layers"><Layers /><span>Layers</span></button>
        <span className="sep" />
        <button className="ctl" disabled title="3D view comes later">2D</button>
        {open && (
          <div className="popover" role="dialog" aria-label="Layers">
            {CONTEXT_LAYERS.map((c) => (
              <label key={c.key} className="toggle">
                <input type="checkbox" checked={!!on[c.key]} onChange={(e) => toggle(c.key, e.target.checked)} />
                <span className="sw" style={{ background: c.color }} /><span>{c.label}</span>
              </label>))}
            <div className="hair" />
            <label className="toggle">
              <input type="checkbox" checked={spot} onChange={(e) => { setSpot(e.target.checked); mv.current?.setSpotlight(e.target.checked); }} />
              <span>Dim imagery under results</span>
            </label>
          </div>)}
      </div>
      <div className="zoom">
        <button aria-label="Zoom in" onClick={() => mv.current?.map.zoomIn({ duration: reduceMotion() ? 0 : 250 })}><Plus /></button>
        <span className="hair" />
        <button aria-label="Zoom out" onClick={() => mv.current?.map.zoomOut({ duration: reduceMotion() ? 0 : 250 })}><Minus /></button>
      </div>
    </>
  );
}
