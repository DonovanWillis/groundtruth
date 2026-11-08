// Chat model + the small pure helpers that turn planner output (actions, step envelopes) into quiet chat text.
import type { Envelope, FC, Feature } from "./api";
import { pretty } from "./config";

export type StepLine = { text: string; ms: number; cached: boolean };
export type ResultCard = {
  title: string;
  count: number | null;
  countLabel: string;            // "found" | "top matches"
  sub: string | null;            // one quiet line of measurements ("37.4 ac in total · median 187 m²")
  fc: FC;                        // the features of the add_results step (the map shows exactly these)
  keep: Set<string> | null;      // set_filter: the ids that pass (others are dimmed)
  exhaustive: boolean;
  env: Envelope;                 // the envelope behind the count (details: method, assumptions, limits, confidence)
  sources: Envelope["sources"];
  download: { url: string; format: string } | null;
  place: string | null;
};
export type Candidates = { feats: Feature[]; chosen: string | null; nots: string[]; concept: string | null; place: string | null };
export type Msg =
  | { id: number; role: "user"; text: string }
  | { id: number; role: "assistant"; pending: boolean; text: string; steps: StepLine[]; card: ResultCard | null;
      cands: Candidates | null; places: string[]; error: string | null; declined: boolean };

/** "432 boat docks in Lake Norman (step_1); 37.3509 acres in total (step_2)." → plain sentences, no refs, 1-decimal numbers. */
export function cleanSay(s: string): string {
  return s
    .replace(/\s*\((?:step_\d+(?:\s*[,;]\s*|\s+and\s+)?)+\)/g, "")
    .replace(/\bstep_\d+\b/g, "")
    .replace(/\d+\.\d{3,}/g, (x) => Number(x).toFixed(1))
    .replace(/\s+([.,;:!?])/g, "$1")
    .replace(/\s{2,}/g, " ")
    .trim();
}

const n = (v: unknown) => Number(v ?? 0).toLocaleString();
const msOf = (env: Envelope) => env.steps.reduce((s, x) => s + (Number(x.ms) || 0), 0);
export const fmtMs = (ms: number) => (ms < 1 ? "<1 ms" : ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`);

/** One quiet line per step envelope: what the tool did, in words, from its tool + metrics. */
export function stepLine(tool: string, env: Envelope): StepLine {
  const m = env.result.metrics ?? {};
  const cached = env.steps.some((s) => s.phase === "memo") || !!m.from_disk_cache;
  const what = String(m.concept ?? m.prompt ?? "").replace(/_/g, " ");
  let text: string;
  if (env.status === "declined") text = `${pretty(tool)} declined${env.declined_reason ? `: ${env.declined_reason}` : ""}`;
  else switch (tool) {
    case "pick_candidates": text = `Found ${n(m.count)} things “${what || "it"}” could mean`; break;
    case "find_all":
      text = m.mode === "ranked_top_k" ? `Ranked the county for ${what || "matches"} (top matches)`
        : m.chips_in_box != null ? `Scanned ${n(m.chips_in_box)} tiles · ${n(m.count_detected)} ${what}`.trim()
        : `Searched the index · ${n(m.count_detected)} ${what}`.trim();
      if (m.mode !== "ranked_top_k" && m.outlined) text += ` · outlined ${n(m.outlined)} · SAM 2`;
      break;
    case "find_anything":
      text = `Searched ${n(m.chips_searched ?? m.chips_in_box)} of ${n(m.chips_in_box)} tiles for “${what}”`;
      if (m.outlined) text += ` · outlined ${n(m.outlined)} · SAM 2`;
      break;
    case "find_buildings": text = `Matched ${n(m.count ?? m.count_detected ?? env.result.geojson.features.length)} building footprints`; break;
    case "measure": text = m.area_acres_total != null ? `Measured ${n(m.count)} outlines · ${Number(m.area_acres_total).toFixed(1)} ac` : `Measured ${n(m.count)}`; break;
    case "filter": text = `Kept ${n(m.count_out)} of ${n(m.count_in)}`; break;
    case "export": text = `Prepared a ${String(m.format ?? "file").toUpperCase()} · ${n(m.count)} rows`; break;
    case "add_layer": text = `Loaded ${pretty(String(m.name ?? m.layer ?? "a layer"))}`; break;
    case "compare_years": text = `Compared 2020 with 2022`; break;
    case "outline": text = `Outlined ${n(env.result.geojson.features.length)} · SAM 2`; break;
    default: text = pretty(tool);
  }
  return { text, ms: msOf(env), cached };
}

/** The count behind a result card: never a features.length of a step whose features were omitted. */
export function countOf(env: Envelope): number | null {
  const m = env.result.metrics ?? {};
  const v = m.count_detected ?? m.count ?? m.count_out;
  if (v != null) return Number(v);
  return m.features_omitted ? null : env.result.geojson.features.length;
}

export function measureLine(m: Record<string, any> | null | undefined): string | null {
  if (!m) return null;
  const bits: string[] = [];
  if (m.area_acres_total != null && Number(m.area_acres_total) > 0) bits.push(`${Number(m.area_acres_total).toFixed(1)} ac in total`);
  if (m.median_area_m2 != null) bits.push(`median ${Math.round(Number(m.median_area_m2)).toLocaleString()} m²`);
  const near = Object.entries(m).find(([k]) => k.startsWith("median_dist_m_to_"));
  if (near) bits.push(`median ${Math.round(Number(near[1])).toLocaleString()} m to ${pretty(near[0].replace("median_dist_m_to_", "").replace(/^osm_/, ""))}`);
  return bits.length ? bits.join(" · ") : null;
}

export const capital = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);
