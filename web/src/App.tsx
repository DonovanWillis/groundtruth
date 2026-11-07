import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import maplibregl, { GeoJSONSource, Map as MlMap } from "maplibre-gl";
import { Envelope, FC, Feature, Health, health, tool } from "./api";

type LogEntry = { id: number; tool: string; status: string; wallMs: number; env: Envelope };
const exampleOf = (f: Feature) => `${f.id}#${f.properties.cell}`;
const PRESETS = ["swimming pool", "parking lot", "solar panels", "warehouse", "construction site"];
const OUTLINE_N = 12;
const CONTEXT = [
  { key: "osm_i485", label: "I-485", color: "#ff6a2b", kind: "line" as const },
  { key: "osm_light_rail", label: "Light rail (LYNX)", color: "#5847b8", kind: "line" as const },
  { key: "osm_light_rail_stations", label: "Light-rail stations", color: "#5847b8", kind: "circle" as const },
  { key: "fema_flood_zones", label: "Flood zones (FEMA)", color: "#0a6283", kind: "fill" as const },
];

function boxPoly(b: number[]): GeoJSON.Polygon {
  const [w, s, e, n] = b;
  return { type: "Polygon", coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]] };
}

export default function App() {
  const [hl, setHl] = useState<Health | null>(null);
  const [year, setYear] = useState<number>(2022);
  const [aoi, setAoi] = useState<string>("");
  const [query, setQuery] = useState("swimming pool");
  const [cands, setCands] = useState<Feature[]>([]);
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [picked, setPicked] = useState<string | null>(null);
  const [results, setResults] = useState<Feature[]>([]);
  const [outlines, setOutlines] = useState<Record<string, Feature>>({});
  const [accepted, setAccepted] = useState<Set<string>>(new Set());
  const [rejected, setRejected] = useState<Set<string>>(new Set());
  const [session, setSession] = useState<string | null>(null);
  const [refined, setRefined] = useState(false);
  const [layersOn, setLayersOn] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [log, setLog] = useState<LogEntry[]>([]);
  const mapRef = useRef<MlMap | null>(null);
  const layerCache = useRef<Record<string, FC>>({});
  const logId = useRef(0);

  // ---------------- API helper with work-log ----------------
  const call = useCallback(async (name: string, body: Record<string, unknown>) => {
    const env = await tool(name, { year, aoi: aoi || undefined, ...body });
    setLog((l) => [{ id: ++logId.current, tool: name, status: env.status, wallMs: env.wallMs, env }, ...l].slice(0, 60));
    if (env.status === "declined") throw new Error(`${name}: ${env.declined_reason}`);
    return env;
  }, [year, aoi]);

  // ---------------- boot ----------------
  useEffect(() => {
    health().then((h) => {
      setHl(h);
      setYear(h.primary_year);
      const idx = h.indexes.filter((i) => i.year === h.primary_year);
      const county = idx.find((i) => i.aoi === "county");
      setAoi(county ? "county" : (idx.sort((a, b) => b.chips - a.chips)[0]?.aoi ?? ""));
    }).catch((e) => setErr(`API not reachable: ${e}`));
  }, []);

  // ---------------- map ----------------
  useEffect(() => {
    const map = new maplibregl.Map({
      container: "map",
      style: { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": "#efefed" } }] },
      center: [-80.825, 35.058], zoom: 14.5, maxZoom: 19, attributionControl: false,
    });
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "imperial" }), "bottom-right");
    map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution:
      "USDA NAIP (public domain) via Microsoft Planetary Computer · © OpenStreetMap contributors · FEMA NFHL · US Census" }));
    map.dragRotate.disable();
    map.on("load", () => {
      map.addSource("boundary", { type: "geojson", data: "/api/v1/boundary" });
      map.addLayer({ id: "boundary", type: "line", source: "boundary", paint: { "line-color": "#191919", "line-width": 1.2, "line-dasharray": [3, 2] } });
      for (const id of ["hits", "outlines", "pick"]) map.addSource(id, { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({ id: "hits", type: "line", source: "hits", paint: {
        "line-color": ["match", ["get", "state"], "accepted", "#13794a", "rejected", "#b42318", "#ff6a2b"], "line-width": 2 } });
      map.addLayer({ id: "outlines-fill", type: "fill", source: "outlines", paint: { "fill-color": "#ff6a2b", "fill-opacity": 0.25 } });
      map.addLayer({ id: "outlines", type: "line", source: "outlines", paint: { "line-color": "#ffffff", "line-width": 1.5 } });
      map.addLayer({ id: "pick", type: "line", source: "pick", paint: { "line-color": "#191919", "line-width": 3 } });
      map.on("click", "hits", (e) => {
        const ex = e.features?.[0]?.properties?.example;
        if (ex) document.getElementById(`res-${ex}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
      });
      map.on("mouseenter", "hits", () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", "hits", () => (map.getCanvas().style.cursor = ""));
    });
    mapRef.current = map;
    return () => map.remove();
  }, []);

  // imagery for the selected year
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      if (map.getLayer("naip")) map.removeLayer("naip");
      if (map.getSource("naip")) map.removeSource("naip");
      map.addSource("naip", { type: "raster", tiles: [`/api/v1/tiles/naip/${year}/{z}/{x}/{y}.png`], tileSize: 256, minzoom: 10, maxzoom: 18 });
      map.addLayer({ id: "naip", type: "raster", source: "naip" }, "boundary");
    };
    if (map.isStyleLoaded() && map.getLayer("boundary")) apply(); else map.once("load", apply);
  }, [year]);

  // hits + outlines → map
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getSource("hits")) return;
    const hits: FC = { type: "FeatureCollection", features: results.map((f) => {
      const ex = exampleOf(f);
      return { type: "Feature", geometry: boxPoly(f.properties.cell_bbox), properties: {
        example: ex, state: accepted.has(ex) ? "accepted" : rejected.has(ex) ? "rejected" : "hit" } };
    }) };
    (map.getSource("hits") as GeoJSONSource).setData(hits as any);
    const ol: FC = { type: "FeatureCollection", features: Object.values(outlines).filter((f) => f.geometry) };
    (map.getSource("outlines") as GeoJSONSource).setData(ol as any);
  }, [results, outlines, accepted, rejected]);

  // ---------------- context layers ----------------
  const toggleLayer = async (key: string, on: boolean) => {
    setLayersOn((s) => ({ ...s, [key]: on }));
    const map = mapRef.current!;
    const def = CONTEXT.find((c) => c.key === key)!;
    if (!on) { if (map.getLayer(`ctx-${key}`)) map.setLayoutProperty(`ctx-${key}`, "visibility", "none"); return; }
    try {
      if (!layerCache.current[key]) {
        setBusy(`loading ${def.label}…`);
        const env = await call("add_layer", { name: key });
        layerCache.current[key] = env.result.geojson;
      }
      if (!map.getSource(`ctx-${key}`)) {
        map.addSource(`ctx-${key}`, { type: "geojson", data: layerCache.current[key] as any });
        const paint: any = def.kind === "line" ? { "line-color": def.color, "line-width": 2.5 }
          : def.kind === "circle" ? { "circle-color": def.color, "circle-radius": 5, "circle-stroke-color": "#fff", "circle-stroke-width": 1.5 }
          : { "fill-color": def.color, "fill-opacity": 0.28 };
        map.addLayer({ id: `ctx-${key}`, type: def.kind, source: `ctx-${key}`, paint } as maplibregl.AddLayerObject, "hits");
      } else map.setLayoutProperty(`ctx-${key}`, "visibility", "visible");
    } catch (e) { setErr(String(e)); setLayersOn((s) => ({ ...s, [key]: false })); }
    finally { setBusy(null); }
  };

  // ---------------- flow ----------------
  const fitTo = (feats: Feature[]) => {
    const map = mapRef.current;
    if (!map || !feats.length) return;
    const b = new maplibregl.LngLatBounds();
    for (const f of feats) { const [w, s, e, n] = f.properties.chip_bbox; b.extend([w, s]); b.extend([e, n]); }
    map.fitBounds(b, { padding: 60, maxZoom: 17, duration: 800 });
  };

  const ask = async (q: string) => {
    if (!q.trim()) return;
    setErr(null); setBusy("finding the different things you might mean…");
    setCands([]); setPicked(null); setExcluded(new Set()); setResults([]); setOutlines({});
    setAccepted(new Set()); setRejected(new Set()); setSession(null); setRefined(false);
    try {
      const env = await call("pick_candidates", { query: q, n: 6 });
      setCands(env.result.geojson.features);
      fitTo(env.result.geojson.features);
    } catch (e) { setErr(String(e)); } finally { setBusy(null); }
  };

  const outlineTop = async (feats: Feature[]) => {
    const todo = feats.slice(0, OUTLINE_N).map(exampleOf).filter((ex) => !outlines[ex]);
    if (!todo.length) return;
    setBusy(`outlining ${todo.length} on screen (SAM 2)…`);
    try {
      const env = await call("outline", { examples: todo, max: OUTLINE_N });
      setOutlines((o) => { const n = { ...o }; for (const f of env.result.geojson.features) n[f.properties.example] = f; return n; });
    } catch (e) { setErr(String(e)); } finally { setBusy(null); }
  };

  const findAll = async (ex: string) => {
    setPicked(ex); setErr(null); setBusy("finding every match…");
    try {
      const pickF = cands.find((c) => c.properties.example === ex);
      if (pickF && mapRef.current?.getSource("pick"))
        (mapRef.current.getSource("pick") as GeoJSONSource).setData({ type: "FeatureCollection",
          features: [{ type: "Feature", geometry: boxPoly(pickF.properties.cell_bbox), properties: {} }] } as any);
      const env = await call("find_similar", { examples: [ex], exclude: [...excluded], k: 100 });
      setResults(env.result.geojson.features); setRefined(false);
      fitTo(env.result.geojson.features.slice(0, 30));
      setBusy(null);
      await outlineTop(env.result.geojson.features);
    } catch (e) { setErr(String(e)); setBusy(null); }
  };

  const judge = async (ex: string, ok: boolean) => {
    const acc = new Set(accepted), rej = new Set(rejected);
    if (ok) { acc.add(ex); rej.delete(ex); } else { rej.add(ex); acc.delete(ex); }
    setAccepted(acc); setRejected(rej);
    setBusy("refining from your feedback…");
    try {
      const accept = session ? (ok ? [ex] : []) : [picked!, ...acc];
      const reject = session ? (ok ? [] : [ex]) : [...excluded, ...rej];
      const env = await call("refine", { session_id: session, accept, reject, k: 100 });
      setSession(env.result.metrics.session_id); setRefined(true);
      setResults(env.result.geojson.features);
      setBusy(null);
      await outlineTop(env.result.geojson.features);
    } catch (e) { setErr(String(e)); setBusy(null); }
  };

  // ---------------- deep link: ?q=swimming+pool&pick=community_pool&layers=osm_i485,fema_flood_zones ----------------
  const auto = useRef(new URLSearchParams(window.location.search));
  useEffect(() => {
    const q = auto.current.get("q");
    if (!aoi || !q) return;
    auto.current.delete("q");
    setQuery(q);
    ask(q);
    for (const k of (auto.current.get("layers") ?? "").split(",").filter(Boolean)) toggleLayer(k, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aoi]);
  useEffect(() => {
    const sense = auto.current.get("pick");
    if (!sense || !cands.length) return;
    auto.current.delete("pick");
    const c = cands.find((x) => x.properties.sense_id === sense) ?? cands[0];
    findAll(c.properties.example);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cands]);

  // ---------------- derived ----------------
  const shown = results.filter((f) => !rejected.has(exampleOf(f)));
  const likely = refined ? shown.filter((f) => f.properties.score >= 0.5).length : shown.length;
  const outlinedAcres = useMemo(() => shown.reduce((s, f) => s + (outlines[exampleOf(f)]?.properties.area_acres ?? 0), 0), [shown, outlines]);
  const years = hl ? [...new Set(hl.indexes.map((i) => i.year))].sort((a, b) => b - a) : [];
  const aois = hl ? hl.indexes.filter((i) => i.year === year) : [];

  return (
    <div className="app">
      <div className="panel left">
        <div className="brand">Groundtruth<small>Teach the map anything · Mecklenburg County, NC</small></div>
        <div className="section">
          <form className="ask" onSubmit={(e) => { e.preventDefault(); ask(query); }}>
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="What are you looking for?" />
            <button className="btn primary" disabled={!!busy || !aoi}>Ask</button>
          </form>
          <div className="chips">{PRESETS.map((p) => <button key={p} className="chip" onClick={() => { setQuery(p); ask(p); }}>{p}</button>)}</div>
          <div className="row" style={{ marginTop: 12 }}>
            <div className="seg">{[2022, 2020].map((y) => (
              <button key={y} className={y === year ? "on" : ""} disabled={!years.includes(y)} title={years.includes(y) ? "" : "not indexed yet"}
                onClick={() => { setYear(y); const i = hl!.indexes.filter((x) => x.year === y); setAoi(i.find((x) => x.aoi === "county")?.aoi ?? i[0]?.aoi ?? ""); }}>{y}</button>))}
            </div>
            <select className="btn" value={aoi} onChange={(e) => setAoi(e.target.value)} title="indexed area">
              {aois.map((i) => <option key={i.aoi} value={i.aoi}>{i.aoi.replace(/_/g, " ")} · {i.chips.toLocaleString()} chips</option>)}
            </select>
          </div>
          {busy && <div className="hint" style={{ marginTop: 10 }}>{busy}</div>}
          {err && <div className="err" style={{ marginTop: 10 }}>{err}</div>}
        </div>

        {cands.length > 0 && (
          <div className="section">
            <div className="label">Which did you mean? Pick one · mark the rest “not this”</div>
            <div className="cands">
              {cands.map((c) => {
                const ex = c.properties.example as string;
                const [w, s, e, n] = c.properties.chip_bbox, [cw, cs, ce, cn] = c.properties.cell_bbox;
                const st = { left: `${((cw - w) / (e - w)) * 100}%`, top: `${((n - cn) / (n - s)) * 100}%`,
                  width: `${((ce - cw) / (e - w)) * 100}%`, height: `${((cn - cs) / (n - s)) * 100}%` };
                return (
                  <div key={ex} className={`cand ${picked === ex ? "picked" : ""} ${excluded.has(ex) ? "excluded" : ""}`}
                       onClick={() => !excluded.has(ex) && findAll(ex)}>
                    <div style={{ position: "relative" }}><img src={c.properties.thumb_url} alt="" /><div className="cellbox" style={st} /></div>
                    <div className="meta">
                      <span className="sense">{c.properties.sense_label}</span>
                      <button className="not" onClick={(ev) => { ev.stopPropagation(); const n2 = new Set(excluded);
                        n2.has(ex) ? n2.delete(ex) : n2.add(ex); setExcluded(n2); }}>{excluded.has(ex) ? "✕ not this" : "not this"}</button>
                    </div>
                  </div>);
              })}
            </div>
          </div>)}

        {results.length > 0 && (
          <div className="section">
            <div className="stats">
              <div className="stat"><b>{likely}</b><span>{refined ? "likely matches (p≥0.5)" : `shown (top ${results.length})`}</span></div>
              <div className="stat"><b>{outlinedAcres.toFixed(2)}</b><span>acres outlined</span></div>
              <div className="stat"><b>{accepted.size}/{rejected.size}</b><span>accepted / rejected</span></div>
            </div>
            <div className="label" style={{ marginTop: 12 }}>Accept ✓ or reject ✕ any result. Each judgement re-trains the ranking live.</div>
            <div className="results">
              {results.slice(0, 60).map((f) => {
                const ex = exampleOf(f);
                const o = outlines[ex];
                return (
                  <div id={`res-${ex}`} key={ex} className={`res ${accepted.has(ex) ? "accepted" : ""} ${rejected.has(ex) ? "rejected" : ""}`}
                       onClick={() => { const [w, s, e, n] = f.properties.cell_bbox; mapRef.current?.fitBounds([[w, s], [e, n]], { maxZoom: 19, padding: 120 }); }}>
                    <img src={f.properties.thumb_url} alt="" />
                    <div><div className="t">#{f.properties.rank} {o ? `${o.properties.area_m2.toFixed(0)} m² · ${o.properties.area_acres.toFixed(3)} ac` : ""}</div>
                      <div className="s">{refined ? "p" : "sim"} {Number(f.properties.score).toFixed(3)}</div></div>
                    <div className="acts" onClick={(e) => e.stopPropagation()}>
                      <button className="ok" title="accept" disabled={!!busy} onClick={() => judge(ex, true)}>✓</button>
                      <button className="no" title="reject" disabled={!!busy} onClick={() => judge(ex, false)}>✕</button>
                    </div>
                  </div>);
              })}
            </div>
          </div>)}

        <div className="section toggles">
          <div className="label">Context layers</div>
          {CONTEXT.map((c) => (
            <label key={c.key}><input type="checkbox" checked={!!layersOn[c.key]} onChange={(e) => toggleLayer(c.key, e.target.checked)} />
              <span className="swatch" style={{ background: c.color }} />{c.label}</label>))}
        </div>
      </div>

      <div className="map-wrap"><div id="map" />
        <div className="badge">NAIP {year} · 0.6 m · {aoi ? aoi.replace(/_/g, " ") : "no index"}</div>
      </div>

      <div className="panel right">
        <div className="brand" style={{ fontSize: 16 }}>Work log<small>every tool call: envelope steps (phase · ms)</small></div>
        <div className="log">
          {log.length === 0 && <div className="hint">Tool calls will appear here.</div>}
          {log.map((l) => (
            <div className="entry" key={l.id}>
              <div className="tool"><span>{l.tool} <span className={`status-${l.status}`}>{l.status}</span></span><span>{l.wallMs} ms</span></div>
              {l.env.steps.map((s, i) => <div className="step" key={i}><span title={s.detail}>{s.phase} · {s.detail}</span><span>{Math.round(s.ms)}</span></div>)}
              {l.env.declined_reason && <div className="step"><span>declined: {l.env.declined_reason}</span></div>}
            </div>))}
        </div>
        <div className="agent-slot">Agent stream: reserved. This panel will consume <code>/api/v1/events</code> (SSE) once the agent lands.</div>
      </div>
    </div>
  );
}
