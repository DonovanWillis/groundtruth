// Chat panel pieces: the composer, the thread, assistant turns (text · steps · result card · pick grid · place pills).
import { KeyboardEvent, useEffect, useRef, useState } from "react";
import { Feature, exampleOf, geomBbox, thumb, tool } from "./api";
import { Candidates, Msg, ResultCard, StepLine, fmtMs } from "./turns";
import { ArrowUp, Chevron, Close, Download, More, Pin } from "./icons";
import { pct } from "./config";

type Assistant = Extract<Msg, { role: "assistant" }>;

// ---------------- composer ----------------
export function Composer({ onSend, busy, year, autoFocus, compact }: {
  onSend: (t: string) => void; busy: boolean; year: number; autoFocus?: boolean; compact?: boolean;
}) {
  const [text, setText] = useState("");
  const ta = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { // grow with the text, up to 6 lines
    const el = ta.current; if (!el) return;
    el.style.height = "auto"; el.style.height = `${Math.min(el.scrollHeight, 6 * 22)}px`;
  }, [text, compact]);
  useEffect(() => { if (compact) ta.current?.focus({ preventScroll: true }); }, [compact]);
  const submit = () => { if (!text.trim() || busy) return; onSend(text); setText(""); };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); }
  };
  return (
    <form className="composer" onSubmit={(e) => { e.preventDefault(); submit(); }}>
      <textarea ref={ta} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey} rows={compact ? 1 : 2} autoFocus={autoFocus}
        placeholder={compact ? "Ask a follow-up…" : "Find anything you can see from above…"} aria-label="Ask Groundtruth" />
      <div className="composer-row">
        <span className="scope">Mecklenburg County · NAIP {year}</span>
        <button className="send" type="submit" disabled={busy || !text.trim()} aria-label="Send"><ArrowUp size={18} /></button>
      </div>
    </form>
  );
}

// ---------------- thread ----------------
export function Thread(p: {
  msgs: Msg[]; activeId: number | null; busy: boolean; year: number; aoi: string;
  onSend: (t: string) => void; onView: (id: number, c: ResultCard) => void; onFeature: (id: number, f: Feature) => void;
  onPick: (id: number, c: Candidates, example: string, nots: string[]) => void;
}) {
  const end = useRef<HTMLDivElement>(null);
  const last = p.msgs[p.msgs.length - 1];
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [p.msgs.length, last && last.role === "assistant" && last.pending]);
  return (
    <div className="thread">
      {p.msgs.map((m) => m.role === "user"
        ? <div key={m.id} className="msg user"><div className="bubble">{m.text}</div></div>
        : <AssistantTurn key={m.id} m={m} {...p} />)}
      <div ref={end} />
    </div>
  );
}

function AssistantTurn({ m, activeId, busy, year, aoi, onSend, onView, onFeature, onPick }: {
  m: Assistant; activeId: number | null; busy: boolean; year: number; aoi: string; onSend: (t: string) => void;
  onView: (id: number, c: ResultCard) => void; onFeature: (id: number, f: Feature) => void;
  onPick: (id: number, c: Candidates, example: string, nots: string[]) => void;
}) {
  if (m.pending) return <div className="msg assistant"><div className="working" aria-live="polite"><i /><i /><i /><span className="sr-only">Working</span></div></div>;
  return (
    <div className="msg assistant">
      {m.error ? <p className="say err">Something went wrong: {m.error}</p> : m.text && <p className={`say ${m.declined ? "muted" : ""}`}>{m.text}</p>}
      {m.steps.length > 0 && <Steps steps={m.steps} />}
      {m.cands && <PickGrid c={m.cands} busy={busy} onPick={(ex, nots) => onPick(m.id, m.cands!, ex, nots)} />}
      {m.card && <Card card={m.card} active={activeId === m.id} year={year} aoi={aoi}
        onView={() => onView(m.id, m.card!)} onFeature={(f) => onFeature(m.id, f)} />}
      {m.places.length > 0 && (
        <div className="places">
          {m.places.map((pl) => <button key={pl} className="pill small" disabled={busy} onClick={() => onSend(`in ${pl}`)}><Pin size={14} />{pl}</button>)}
        </div>)}
    </div>
  );
}

function Steps({ steps }: { steps: StepLine[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={`steps ${open ? "open" : ""}`}>
      <button className="steps-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
        <Chevron size={14} /><span>{steps.length} step{steps.length === 1 ? "" : "s"}</span>
      </button>
      {open && <ol>{steps.map((s, i) => <li key={i}><span>{s.text}</span><span className="ms">{fmtMs(s.ms)}{s.cached ? " · cached" : ""}</span></li>)}</ol>}
    </div>
  );
}

// ---------------- result card ----------------
function Card({ card, active, year, aoi, onView, onFeature }: {
  card: ResultCard; active: boolean; year: number; aoi: string; onView: () => void; onFeature: (f: Feature) => void;
}) {
  const [menu, setMenu] = useState(false);
  const [details, setDetails] = useState(false);
  const [exporting, setExporting] = useState<string | null>(null);
  const [exportErr, setExportErr] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const detailsRef = useRef<HTMLDivElement>(null);
  useEffect(() => { if (details) detailsRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [details]);
  useEffect(() => {
    if (!menu) return;
    const close = (e: MouseEvent) => { if (!menuRef.current?.contains(e.target as Node)) setMenu(false); };
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [menu]);
  const shown = card.keep ? card.fc.features.filter((f) => card.keep!.has(exampleOf(f))) : card.fc.features;
  const thumbs = shown.filter((f) => f.properties.chip_id && String(exampleOf(f)).includes("#")).slice(0, 4);
  const doExport = async (format: "csv" | "geojson" | "pdf") => {
    // the planner already prepared this file (offer_download): hand it over instead of exporting again
    if (card.download && card.download.format === format && !card.keep) { window.open(card.download.url, "_blank"); setMenu(false); return; }
    setExporting(format); setExportErr(null);
    try {
      const env = await tool("export", { year, aoi: aoi || undefined, geojson: { type: "FeatureCollection", features: shown }, format,
        title: card.title, summary: { query: card.title, place: card.place, year, count: card.count } });
      const url = env.result.metrics.download;
      if (url) window.open(url, "_blank"); else setExportErr("No file came back.");
    } catch (e) { setExportErr(String(e).replace(/^Error:\s*/, "").slice(0, 120)); }
    finally { setExporting(null); setMenu(false); }
  };
  const e = card.env;
  return (
    <div className={`card ${active ? "active" : ""}`}>
      <div className="card-head">
        <div className="card-title">{card.title}</div>
        <div className="menu-wrap" ref={menuRef}>
          <button className="icon-btn" aria-label="More" aria-expanded={menu} onClick={() => setMenu(!menu)}><More size={18} /></button>
          {menu && (
            <div className="menu" role="menu">
              {(["csv", "geojson", "pdf"] as const).map((f) => (
                <button key={f} role="menuitem" disabled={!!exporting} onClick={() => doExport(f)}>
                  <Download size={15} />Export {f === "geojson" ? "GeoJSON" : f.toUpperCase()}{exporting === f ? "…" : ""}
                </button>))}
            </div>)}
        </div>
      </div>
      <div className="card-count">
        {card.count != null ? <><span className="n">{card.count.toLocaleString()}</span> {card.countLabel}</> : card.countLabel}
        {card.sub && <span className="muted"> · {card.sub}</span>}
      </div>
      {thumbs.length > 0 && (
        <div className="thumbs">{thumbs.map((f) => (
          <button key={exampleOf(f)} className="thumb" onClick={() => onFeature(f)} aria-label="Show this one on the map"><Crop f={f} /></button>))}
        </div>)}
      <div className="card-foot">
        <button className="link" onClick={onView}>View on map</button>
        <button className={`link quiet ${details ? "on" : ""}`} onClick={() => setDetails(!details)} aria-expanded={details}>
          Details<Chevron size={13} />
        </button>
      </div>
      {exportErr && <div className="note err">{exportErr}</div>}
      {details && (
        <div className="details" ref={detailsRef}>
          {e.confidence != null && <div className="drow"><span>Confidence</span><span>{pct(e.confidence)} <span className="muted">(heuristic)</span></span></div>}
          {e.method && <div className="dblock"><span>Method</span><p>{e.method}</p></div>}
          {e.assumptions.length > 0 && <div className="dblock"><span>Assumptions</span>{e.assumptions.map((a, i) => <p key={i}>{a}</p>)}</div>}
          {e.limits.length > 0 && <div className="dblock"><span>Limits</span>{e.limits.map((a, i) => <p key={i}>{a}</p>)}</div>}
        </div>)}
    </div>
  );
}

/** Chip image cropped onto the object: its outline (or 16.8 m cell) centred, zoomed so it fills about half the tile. */
function Crop({ f, zoomMax = 3.2 }: { f: Feature; zoomMax?: number }) {
  const p = f.properties;
  const src = thumb(p.thumb_url ?? `/api/v1/chips/${p.chip_id}.jpg`);
  const cb: number[] | undefined = p.chip_bbox;
  let style: React.CSSProperties = { width: "100%", height: "100%", left: 0, top: 0 };
  if (cb) {
    const gb = f.geometry && f.geometry.type !== "Point" ? geomBbox(f.geometry) : null;
    const tb: number[] = gb && gb.every(Number.isFinite) && gb[0] >= cb[0] && gb[2] <= cb[2] ? gb : p.cell_bbox ?? cb;
    const cw = cb[2] - cb[0], ch = cb[3] - cb[1];
    const z = Math.max(1, Math.min(zoomMax, 0.5 / Math.max((tb[2] - tb[0]) / cw, (tb[3] - tb[1]) / ch, 1e-6)));
    const fx = ((tb[0] + tb[2]) / 2 - cb[0]) / cw, fy = (cb[3] - (tb[1] + tb[3]) / 2) / ch;
    const clamp = (v: number) => Math.min(0, Math.max(1 - z, v));
    style = { width: `${z * 100}%`, height: `${z * 100}%`, left: `${clamp(0.5 - fx * z) * 100}%`, top: `${clamp(0.5 - fy * z) * 100}%` };
  }
  return <span className="crop"><img src={src} alt="" loading="lazy" style={style} /></span>;
}

// ---------------- "Which do you mean?" ----------------
function PickGrid({ c, busy, onPick }: { c: Candidates; busy: boolean; onPick: (example: string, nots: string[]) => void }) {
  const tiles = c.feats.slice(0, 6);
  const chosenLabel = tiles.find((t) => t.properties.example === c.chosen)?.properties.sense_label;
  return (
    <div className="pick">
      <div className="pick-q">Which do you mean?{chosenLabel && <span className="muted"> I went with {chosenLabel.toLowerCase()}.</span>}</div>
      <div className="pick-grid">
        {tiles.map((t) => {
          const ex = t.properties.example as string;
          const nce = !!t.properties.no_clear_example;
          const not = c.nots.includes(ex);
          return (
            <div key={ex ?? t.properties.sense_id} className={`ptile ${ex === c.chosen ? "chosen" : ""} ${not ? "not" : ""} ${nce ? "nce" : ""}`}>
              <button className="ptile-main" disabled={busy || nce || not} onClick={() => onPick(ex, c.nots)} title={t.properties.sense_label}>
                {t.properties.chip_id ? <Crop f={t} zoomMax={2.4} /> : <span className="crop" />}
                <span className="plabel">{t.properties.sense_label}</span>
              </button>
              {!nce && ex !== c.chosen && (
                <button className="ptile-x" disabled={busy} aria-label={`Not ${t.properties.sense_label}`} title="Not this"
                  onClick={() => onPick(c.chosen ?? ex, not ? c.nots.filter((x) => x !== ex) : [...c.nots, ex])}><Close size={12} /></button>)}
            </div>);
        })}
      </div>
    </div>
  );
}
