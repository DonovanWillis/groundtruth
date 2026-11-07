// Thin client for the Groundtruth API (docs/CONTRACT.md). Every tool returns an Envelope.

export type Step = { phase: string; detail: string; ms: number };
export type Feature = {
  type: "Feature";
  id?: string;
  geometry: GeoJSON.Geometry | null;
  properties: Record<string, any>;
};
export type FC = { type: "FeatureCollection"; features: Feature[] };
export type Envelope = {
  tool: string;
  version: string;
  status: "ok" | "partial" | "declined";
  result: { geojson: FC; metrics: Record<string, any> };
  confidence: number | null;
  method: string;
  assumptions: string[];
  limits: string[];
  sources: { name: string; url: string; date: string; licence: string }[];
  steps: Step[];
  declined_reason: string | null;
};
export type Health = {
  ok: boolean;
  contract: string;
  engine_version: string;
  primary_year: number;
  indexes: { aoi: string; year: number; chips: number; index_version: string }[];
};

const BASE = "/api/v1";

export async function health(): Promise<Health> {
  const r = await fetch(`${BASE}/health`);
  if (!r.ok) throw new Error(`health ${r.status}`);
  return r.json();
}

export async function tool(name: string, body: Record<string, unknown>): Promise<Envelope & { wallMs: number }> {
  const t0 = performance.now();
  const r = await fetch(`${BASE}/tools/${name}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${name}: HTTP ${r.status} ${(await r.text()).slice(0, 200)}`);
  const env = (await r.json()) as Envelope;
  return { ...env, wallMs: Math.round(performance.now() - t0) };
}

export const chipUrl = (thumb: string) => thumb; // already /api/v1/chips/<id>.jpg
