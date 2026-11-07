// Agent slot. The real agent (separate branch, not merged) emits map actions per this schema; the UI applies them
// through `applyAction`. Until /api/v1/events exists, `mockAgentStream` replays a SCRIPTED example that makes the
// real tool calls (step_1..step_N are genuine envelopes) but whose plan and wording are hard-coded. It is a mock,
// not an LLM, and the UI labels it "MOCK agent stream" everywhere.
import { Bbox, Envelope, FC, tool } from "./api";

export type MapAction =
  | { action: "fly_to"; bbox: Bbox; label?: string; approximate?: boolean }
  | { action: "add_layer"; layer_id: string; source: "envelope"; envelope_ref: string; style?: Record<string, any> }
  | { action: "show_candidates" | "show_metrics" | "offer_download"; envelope_ref: string; format?: string }
  | { action: "add_results"; layer_id: string; envelope_ref: string; style?: Record<string, any> }
  | { action: "set_filter"; layer_id: string; envelope_ref: string }
  | { action: "say"; text: string };

/** What a stream yields: a tool envelope (becomes step_N, in order) or a batch of map actions. */
export type AgentEvent =
  | { type: "envelope"; env: Envelope }
  | { type: "actions"; actions: MapAction[] }
  | { type: "done" }
  | { type: "error"; message: string };

/** The UI surface the adapter drives. App.tsx implements it. */
export interface AgentTarget {
  flyTo(bbox: Bbox, label?: string, approximate?: boolean): void;
  addLayer(layerId: string, env: Envelope, style?: Record<string, any>): void;
  showCandidates(env: Envelope): void;
  showMetrics(env: Envelope): void;
  offerDownload(env: Envelope, format?: string): void;
  addResults(layerId: string, env: Envelope, style?: Record<string, any>): void;
  setFilter(layerId: string, env: Envelope): void;
  say(text: string): void;
}

export class AgentRun {
  envelopes: Envelope[] = [];
  constructor(private target: AgentTarget) {}

  ref(r: string): Envelope {
    const m = /^step_(\d+)$/.exec(r);
    const env = m ? this.envelopes[Number(m[1]) - 1] : undefined;
    if (!env) throw new Error(`unknown envelope_ref "${r}" (have ${this.envelopes.length} steps)`);
    return env;
  }

  handle(ev: AgentEvent) {
    if (ev.type === "envelope") this.envelopes.push(ev.env);
    if (ev.type === "actions") for (const a of ev.actions) this.apply(a);
  }

  apply(a: MapAction) {
    const t = this.target;
    switch (a.action) {
      case "fly_to": return t.flyTo(a.bbox, a.label, a.approximate);
      case "add_layer": return t.addLayer(a.layer_id, this.ref(a.envelope_ref), a.style);
      case "show_candidates": return t.showCandidates(this.ref(a.envelope_ref));
      case "show_metrics": return t.showMetrics(this.ref(a.envelope_ref));
      case "offer_download": return t.offerDownload(this.ref(a.envelope_ref), a.format);
      case "add_results": return t.addResults(a.layer_id, this.ref(a.envelope_ref), a.style);
      case "set_filter": return t.setFilter(a.layer_id, this.ref(a.envelope_ref));
      case "say": return t.say(a.text);
      default: throw new Error(`unknown action ${(a as any).action}`);
    }
  }
}

// ---------------- REAL stream hook (not implemented server-side yet) ----------------
/** Swap point for Donovan's agent: GET /api/v1/events (SSE) currently answers 501. Expected wire format (assumed,
 *  to be confirmed when the agent merges): `event: envelope` + JSON Envelope, `event: actions` + JSON MapAction[],
 *  `event: done`. Not used by the UI today. */
export async function* realAgentStream(prompt: string, opts: { aoi?: string; year?: number } = {}): AsyncGenerator<AgentEvent> {
  const qs = new URLSearchParams({ prompt, ...(opts.aoi ? { aoi: opts.aoi } : {}), ...(opts.year ? { year: String(opts.year) } : {}) });
  const queue: AgentEvent[] = [];
  let wake: (() => void) | null = null;
  const es = new EventSource(`/api/v1/events?${qs}`);
  const push = (e: AgentEvent) => { queue.push(e); wake?.(); };
  es.addEventListener("envelope", (m) => push({ type: "envelope", env: JSON.parse((m as MessageEvent).data) }));
  es.addEventListener("actions", (m) => push({ type: "actions", actions: JSON.parse((m as MessageEvent).data) }));
  es.addEventListener("done", () => { push({ type: "done" }); es.close(); });
  es.onerror = () => { push({ type: "error", message: "agent stream unavailable (/api/v1/events not implemented yet)" }); es.close(); };
  while (true) {
    if (!queue.length) await new Promise<void>((r) => (wake = r));
    const e = queue.shift()!;
    yield e;
    if (e.type === "done" || e.type === "error") return;
  }
}

// ---------------- MOCK stream ----------------
/** Scripted replay of "pools within 1 km of I-485 in Ballantyne". Real API calls; hard-coded plan. */
export async function* mockAgentStream(ctx: { aoi?: string; year: number; places: Record<string, Bbox> }): AsyncGenerator<AgentEvent> {
  const common = { aoi: ctx.aoi, year: ctx.year };
  const call = async (name: string, body: Record<string, unknown>) => {
    const env = await tool(name, { ...common, ...body }, "agent");
    return env;
  };
  const place = "Ballantyne";
  const bbox = ctx.places[place];
  yield { type: "actions", actions: [{ action: "say", text: "Plan: find swimming pools, restrict to Ballantyne, keep those within 1 km of I-485, measure, export a PDF." }] };
  if (bbox) yield { type: "actions", actions: [{ action: "fly_to", bbox, label: place, approximate: true }] };

  const s1 = await call("pick_candidates", { query: "swimming pool", n: 6 });
  yield { type: "envelope", env: s1 };
  if (s1.status === "declined") { yield { type: "error", message: `pick_candidates declined: ${s1.declined_reason}` }; return; }
  const backyard = s1.result.geojson.features.find((f) => f.properties.sense_id === "backyard_pool") ?? s1.result.geojson.features[0];
  yield { type: "actions", actions: [
    { action: "show_candidates", envelope_ref: "step_1" },
    { action: "say", text: `"Pools" is ambiguous — taking the "${backyard?.properties.sense_label ?? "first"}" sense as the example.` },
  ] };

  const s2 = await call("find_all", { examples: [backyard.properties.example], k: 200, place, concept: s1.result.metrics.sense_list,
    rerank: true, outline_top: 200 });
  yield { type: "envelope", env: s2 };
  yield { type: "actions", actions: [{ action: "add_results", layer_id: "pools", envelope_ref: "step_2" }] };

  const s3 = await call("add_layer", { name: "osm_i485" });
  yield { type: "envelope", env: s3 };
  yield { type: "actions", actions: [{ action: "add_layer", layer_id: "osm_i485", source: "envelope", envelope_ref: "step_3" }] };

  const s4 = await call("filter", { geojson: s2.result.geojson as FC, where: {
    within_m_of: { layer: "osm_i485", m: 1000 }, min_confidence: s2.result.metrics.confidence_cut ?? 0.5 } });
  yield { type: "envelope", env: s4 };
  yield { type: "actions", actions: [{ action: "set_filter", layer_id: "pools", envelope_ref: "step_4" }] };

  const s5 = await call("measure", { geojson: s4.result.geojson, to_layers: ["osm_i485"] });
  yield { type: "envelope", env: s5 };
  yield { type: "actions", actions: [{ action: "show_metrics", envelope_ref: "step_5" }] };

  const m = s5.result.metrics;
  const s6 = await call("export", { geojson: s4.result.geojson, format: "pdf", title: "Pools within 1 km of I-485 — Ballantyne",
    summary: { count: m.count, area_acres_total: m.area_acres_total, median_dist_m_to_osm_i485: m.median_dist_m_to_osm_i485,
      note: "MOCK agent stream (scripted replay)" } });
  yield { type: "envelope", env: s6 };
  yield { type: "actions", actions: [
    { action: "offer_download", envelope_ref: "step_6", format: "pdf" },
    { action: "say", text: `${m.count ?? 0} detected pools in Ballantyne (confidence ≥ ${s2.result.metrics.confidence_cut ?? 0.5}) lie within 1 km of I-485, out of ${s2.result.metrics.count_returned ?? "?"} ranked matches. Areas sum outlined pools only; confidence is a heuristic, not a probability.` },
  ] };
  yield { type: "done" };
}
