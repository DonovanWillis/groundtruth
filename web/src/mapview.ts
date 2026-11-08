// Imperative MapLibre wrapper: NAIP imagery, county boundary, context layers, results (outline polygons or
// cell boxes), the picked examples, and agent-added layers. React state pushes data in; clicks come back out.
import maplibregl, { GeoJSONSource, Map as MlMap } from "maplibre-gl";
import type { Bbox, FC } from "./api";
import { COLORS, CONTEXT_LAYERS, LayerDef, RESULT_STYLE } from "./config";

const EMPTY: FC = { type: "FeatureCollection", features: [] };
/** One entry of GET /api/v1/vt: gzip MVT tiles, source-layer name == layer key. */
type VtLayer = { minzoom: number; maxzoom: number; url: string };

export class MapView {
  map: MlMap;
  private ready: Promise<void>;
  private year = 0;
  private vt: Record<string, VtLayer> = {};
  onResultClick: (example: string) => void = () => {};

  constructor(container: HTMLElement) {
    this.map = new maplibregl.Map({
      container,
      style: {
        version: 8,
        sources: {},
        layers: [{ id: "bg", type: "background", paint: { "background-color": "#e9e9e6" } }],
      },
      center: [-80.825, 35.058], zoom: 13.2, maxZoom: 19.5, attributionControl: false,
    });
    const m = this.map;
    m.addControl(new maplibregl.NavigationControl({ visualizePitch: false, showCompass: false }), "bottom-right");
    m.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
    m.addControl(new maplibregl.AttributionControl({
      compact: true,
      customAttribution: "NAIP (USDA, public domain) · © OpenStreetMap contributors · FEMA NFHL · US Census",
    }));
    // Bench hook (scripts/ui_bench.py): the map and the time of every 'idle' event, nothing else.
    const w = window as any;
    w.__gtMap = m; w.__gtIdleTimes = [];
    m.on("idle", () => { w.__gtMapIdle = true; w.__gtIdleTimes.push(performance.now()); });
    m.on("dataloading", () => { w.__gtMapIdle = false; });
    m.dragRotate.disable();
    m.touchZoomRotate.disableRotation();
    // Vector-tile catalogue; an older API without /vt (or an error) just means every layer falls back to GeoJSON.
    const vt: Promise<Record<string, VtLayer>> = fetch("/api/v1/vt").then((r) => (r.ok ? r.json() : {})).catch(() => ({}));
    const loaded = new Promise<void>((res) => m.on("load", () => { this.setup(); res(); }));
    this.ready = Promise.all([vt, loaded]).then(([v]) => { this.vt = v && typeof v === "object" ? v : {}; });
  }

  private setup() {
    const m = this.map;
    m.addSource("boundary", { type: "geojson", data: "/api/v1/boundary" });
    m.addLayer({ id: "anchor-imagery", type: "background", paint: { "background-opacity": 0 } });
    m.addLayer({ id: "boundary", type: "line", source: "boundary",
      paint: { "line-color": "#ffffff", "line-width": 1.4, "line-dasharray": [3, 2], "line-opacity": 0.9 } });
    m.addLayer({ id: "anchor-context", type: "background", paint: { "background-opacity": 0 } });
    for (const id of ["pick", "agent"]) m.addSource(id, { type: "geojson", data: EMPTY as any });
    this.addResultLayers();
    m.addLayer({ id: "pick", type: "line", source: "pick", paint: { "line-color": "#ffffff", "line-width": 3 } });
    m.addLayer({ id: "pick-inner", type: "line", source: "pick", paint: { "line-color": COLORS.pick, "line-width": 1.5 } });
    m.addLayer({ id: "agent-line", type: "line", source: "agent", paint: { "line-color": "#5847b8", "line-width": 2 } });
    this.wireResultEvents();
  }

  // ---------------- results: zoom-aware styling (C0) ----------------
  // Polygons ("results") are drawn from closeZ; below it every result is a glowing dot (centroid points). Exhaustive sets
  // go to the clustered point source ("results-cl", count bubbles below midZ); ranked top-k sets, rejected and filtered-out
  // results go to the plain point source ("results-pts") so a bubble never implies a total it does not have.
  private addResultLayers() {
    const m = this.map;
    const S = RESULT_STYLE;
    m.addLayer({ id: "spotlight", type: "background", layout: { visibility: "none" },
      paint: { "background-color": COLORS.spotlight, "background-opacity": S.spotlightOpacity } }, "boundary");
    m.addSource("results", { type: "geojson", data: EMPTY as any, promoteId: "example" });
    m.addSource("results-pts", { type: "geojson", data: EMPTY as any, promoteId: "example" });
    m.addSource("results-cl", { type: "geojson", data: EMPTY as any, promoteId: "example", cluster: true,
      clusterMaxZoom: S.midZ - 1, clusterRadius: 42,
      clusterProperties: { n_new: ["+", ["case", ["==", ["get", "change"], "new"], 1, 0]] } } as any);

    const hov: any = ["boolean", ["feature-state", "hover"], false];
    const isNew: any = ["==", ["get", "change"], "new"];
    const isAcc: any = ["==", ["get", "state"], "accepted"];
    const base: any = ["case", isNew, COLORS.new, ["==", ["get", "change"], "unsure"], COLORS.unsure, COLORS.hit];
    const color: any = ["case", hov, ["case", isNew, COLORS.newHover, COLORS.hitHover], base];
    /** a × (rejected → 0.12, filtered out → 0.18). */
    const fade = (a: number): any => ["case", ["==", ["get", "state"], "rejected"], a * 0.12,
      ["to-boolean", ["get", "dim"]], a * 0.18, a];
    /** Glow only for live results (rejected / filtered-out ones get no glow, so the counted set reads first). */
    const glowFade = (a: number): any => ["case", ["any", ["==", ["get", "state"], "rejected"], ["to-boolean", ["get", "dim"]]], 0, a];
    /** Small objects (< 150 m², e.g. a backyard pool) keep their ring at close zoom too: a 3-px outline alone is tiny. */
    const small: any = ["<", ["coalesce", ["get", "area_m2"], 0], 150];
    const z0 = S.closeZ - S.fadeZ, z1 = S.closeZ;
    /** Polygons fade in over [z0, z1]; dots fade out over [z0 + 0.3, z1 + 0.3]. */
    const polyIn = (a: number): any => ["interpolate", ["linear"], ["zoom"], z0, 0, z1, fade(a)];
    const dotOut = (a: number, from?: number): any => from == null
      ? ["interpolate", ["linear"], ["zoom"], z0 + 0.3, fade(a), z1 + 0.3, 0]
      : ["interpolate", ["linear"], ["zoom"], from - 0.5, 0, from, fade(a), z0 + 0.3, fade(a), z1 + 0.3, ["case", small, fade(a), 0]];
    // size factor from area: ~40 m² pool → 0.8, 64 m² → 1, ≥ 185 m² roof → 1.7 (unknown area → 1)
    const sz: any = ["min", 1.7, ["max", 0.7, ["/", ["sqrt", ["coalesce", ["get", "area_m2"], 64]], 8]]];
    const grow = (e: any): any => ["*", ["case", hov, 1.45, 1], e];
    const lin = (a: number, b: number): any => ["+", a, ["*", b, sz]];
    const dotR: any = ["interpolate", ["linear"], ["zoom"], 9, grow(lin(2, 1.4)), S.midZ, grow(lin(3, 2.6)), z1, grow(lin(5, 4))];
    const ringR: any = ["interpolate", ["linear"], ["zoom"], 9, grow(lin(5, 1.4)), S.midZ, grow(lin(8, 2.6)), z1, grow(lin(11, 4)), 18, grow(lin(15, 5))];
    const glowR: any = ["interpolate", ["linear"], ["zoom"], 9, grow(lin(6, 4)), S.midZ, grow(lin(9, 6)), z1, grow(lin(14, 8))];
    const halo = COLORS.halo, hop = S.haloOpacity;
    const outline: any = ["==", ["get", "kind"], "outline"], cell: any = ["==", ["get", "kind"], "cell"];

    // close zoom: 25 % fill, 2-px dark halo, 3-px outline (accepted: green), pending cells dashed
    m.addLayer({ id: "results-fill", type: "fill", source: "results", filter: outline,
      paint: { "fill-color": color, "fill-opacity": ["interpolate", ["linear"], ["zoom"], z0, 0, z1,
        ["case", hov, fade(0.45), fade(S.fillOpacity)]] } as any });
    m.addLayer({ id: "results-halo", type: "line", source: "results",
      layout: { "line-join": "round" }, paint: { "line-color": halo, "line-width": ["case", hov, S.lineWidth + 6, S.lineWidth + 4],
        "line-opacity": polyIn(hop) } as any });
    m.addLayer({ id: "results-line", type: "line", source: "results", filter: outline, layout: { "line-join": "round" },
      paint: { "line-color": ["case", isAcc, COLORS.accepted, color], "line-width": ["case", hov, S.lineWidth + 1.5, S.lineWidth],
        "line-opacity": polyIn(1) } as any });
    m.addLayer({ id: "results-cell", type: "line", source: "results", filter: cell,
      paint: { "line-color": ["case", isAcc, COLORS.accepted, color], "line-width": 2.2, "line-dasharray": [2, 1.5],
        "line-opacity": polyIn(0.95) } as any });
    m.addLayer({ id: "results-hit", type: "fill", source: "results", paint: { "fill-color": "#000", "fill-opacity": 0.001 } });
    m.addLayer({ id: "results-sel", type: "line", source: "results", filter: ["==", ["get", "sel"], true],
      paint: { "line-color": "#ffffff", "line-width": 1.5, "line-opacity": polyIn(1) } as any });

    // zoomed out / mid zoom: glow + dot (+ ring from midZ), on both point sources
    const unclustered: any = ["!", ["has", "point_count"]];
    for (const src of PT_SRCS) {
      m.addLayer({ id: `${src}-glow`, type: "circle", source: src, filter: unclustered,
        paint: { "circle-color": color, "circle-radius": glowR, "circle-blur": 1,
          "circle-opacity": ["interpolate", ["linear"], ["zoom"], z0 + 0.3, glowFade(0.55), z1 + 0.3, 0] } as any });
      m.addLayer({ id: `${src}-ringhalo`, type: "circle", source: src, filter: unclustered, minzoom: S.midZ - 0.5,
        paint: { "circle-radius": ringR, "circle-opacity": 0, "circle-stroke-color": halo,
          "circle-stroke-width": ["case", isAcc, 5, 4.2], "circle-stroke-opacity": dotOut(hop, S.midZ) } as any });
      m.addLayer({ id: `${src}-ring`, type: "circle", source: src, filter: unclustered, minzoom: S.midZ - 0.5,
        paint: { "circle-radius": ringR, "circle-opacity": 0, "circle-stroke-color": ["case", isAcc, COLORS.accepted, color],
          "circle-stroke-width": ["case", isAcc, 3, ["case", hov, 3, 2.2]], "circle-stroke-opacity": dotOut(1, S.midZ) } as any });
      m.addLayer({ id: `${src}-dot`, type: "circle", source: src, filter: unclustered,
        paint: { "circle-color": color, "circle-radius": dotR,
          "circle-stroke-color": ["case", isAcc, COLORS.accepted, hov, "#ffffff", halo],
          "circle-stroke-width": ["case", isAcc, 2.5, hov, 2, 1.3], "circle-opacity": dotOut(1), "circle-stroke-opacity": dotOut(1) } as any });
      m.addLayer({ id: `${src}-pulse`, type: "circle", source: src, filter: ["all", unclustered, ["==", ["get", "sel"], true]],
        paint: { "circle-radius": 14, "circle-opacity": 0, "circle-stroke-color": "#ffffff", "circle-stroke-width": 3,
          "circle-stroke-opacity": 0.9 } as any });
    }
    // exhaustive sets only: cluster bubbles below midZ (orange edge when the cluster holds "new since 2020" results)
    const clustered: any = ["has", "point_count"];
    const bubR: any = ["step", ["get", "point_count"], 13, 10, 16, 50, 20, 200, 25];
    m.addLayer({ id: "results-cl-bglow", type: "circle", source: "results-cl", filter: clustered,
      paint: { "circle-color": COLORS.hit, "circle-radius": ["*", 1.9, bubR], "circle-blur": 1, "circle-opacity": 0.5 } as any });
    m.addLayer({ id: "results-cl-bubble", type: "circle", source: "results-cl", filter: clustered,
      paint: { "circle-color": COLORS.hit, "circle-radius": bubR, "circle-opacity": 0.95,
        "circle-stroke-color": ["case", [">", ["get", "n_new"], 0], COLORS.new, halo],
        "circle-stroke-width": ["case", [">", ["get", "n_new"], 0], 3, 1.5], "circle-stroke-opacity": 0.85 } as any });
  }

  private hoverId: string | null = null;
  private popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 12, className: "gt-area-pop" });

  /** Topmost result under the cursor (dot, ring, cluster bubble or polygon), ±6 px so small dots are easy to hit. */
  private resultAt(p: { x: number; y: number }) {
    const layers = [...PT_SRCS.flatMap((s) => [`${s}-dot`, `${s}-ring`]), "results-cl-bubble", "results-hit"];
    const fs = this.map.queryRenderedFeatures([[p.x - 6, p.y - 6], [p.x + 6, p.y + 6]], { layers });
    return fs.find((f) => f.properties?.point_count != null || (f.properties?.example && f.properties?.state !== "rejected"));
  }

  private setHover(id: string | null) {
    if (id === this.hoverId) return;
    const m = this.map;
    for (const [hid, on] of [[this.hoverId, false], [id, true]] as const)
      if (hid) for (const source of ["results", ...PT_SRCS]) m.setFeatureState({ source, id: hid }, { hover: on });
    this.hoverId = id;
  }

  private wireResultEvents() {
    const m = this.map;
    m.on("mousemove", (e) => {
      const f = this.resultAt(e.point);
      m.getCanvas().style.cursor = f ? "pointer" : "";
      const ex = f?.properties?.point_count == null ? (f?.properties?.example as string | undefined) : undefined;
      this.setHover(ex ?? null);
      const a = f?.properties?.area_m2;
      if (ex && a != null && a !== "") this.popup.setLngLat(e.lngLat).setText(`${Math.round(Number(a)).toLocaleString()} m²`).addTo(m);
      else this.popup.remove();
    });
    m.getCanvas().addEventListener("mouseleave", () => { this.setHover(null); this.popup.remove(); });
    m.on("click", async (e) => {
      const f = this.resultAt(e.point);
      if (!f) return;
      if (f.properties?.point_count != null) {
        const z = await (m.getSource("results-cl") as GeoJSONSource).getClusterExpansionZoom(f.properties.cluster_id);
        m.easeTo({ center: (f.geometry as GeoJSON.Point).coordinates as [number, number], zoom: z + 0.2 });
      } else if (f.properties?.example) this.onResultClick(f.properties.example);
    });
    // cluster counts as HTML markers (the style has no glyphs); refreshed when the view or the clustered data settles
    m.on("moveend", () => this.updateClusterLabels());
    m.on("sourcedata", (e: any) => { if (e.sourceId === "results-cl" && e.isSourceLoaded) this.updateClusterLabels(); });
  }

  private clusterMarks = new Map<number, maplibregl.Marker>();
  private updateClusterLabels() {
    const m = this.map;
    const keep = new Set<number>();
    if (this.exhaustive && this.hasResults && m.getZoom() < RESULT_STYLE.midZ) {
      for (const f of m.querySourceFeatures("results-cl", { filter: ["has", "point_count"] as any })) {
        const id = f.properties!.cluster_id as number;
        if (keep.has(id)) continue;
        keep.add(id);
        if (this.clusterMarks.has(id)) continue;
        const el = document.createElement("div");
        el.className = "gt-cluster-n";
        el.textContent = Number(f.properties!.point_count).toLocaleString();
        this.clusterMarks.set(id, new maplibregl.Marker({ element: el })
          .setLngLat((f.geometry as GeoJSON.Point).coordinates as [number, number]).addTo(m));
      }
    }
    for (const [id, mk] of this.clusterMarks) if (!keep.has(id)) { mk.remove(); this.clusterMarks.delete(id); }
  }

  // selected result: a pulsing ring (one paint update per ~33 ms). It pulses for PULSE_MS after a new selection, then
  // settles to a steady ring, so the map can go idle again (no endless repaint while something stays selected).
  private raf = 0;
  private lastPulse = 0;
  private pulseStart = 0;
  private selId: string | null = null;
  private pulse = (t: number) => {
    if (!this.pulseStart) this.pulseStart = t;
    const done = t - this.pulseStart > PULSE_MS;
    this.raf = done ? 0 : requestAnimationFrame(this.pulse);
    if (!done && t - this.lastPulse < 33) return;
    this.lastPulse = t;
    const p = done ? 0.35 : ((t - this.pulseStart) % 1400) / 1400;
    this.setPulsePaint(p, done ? 0.95 : 0.95 * (1 - p));
  };
  private setPulsePaint(p: number, opacity: number) {
    const r: any = ["interpolate", ["linear"], ["zoom"], 9, 9 + 12 * p, 13, 13 + 14 * p, 16, 20 + 16 * p, 19, 34 + 22 * p];
    for (const src of PT_SRCS) {
      this.map.setPaintProperty(`${src}-pulse`, "circle-radius", r);
      this.map.setPaintProperty(`${src}-pulse`, "circle-stroke-opacity", opacity);
    }
  }
  private setPulsing(selId: string | null) {
    if (selId === this.selId) return;
    this.selId = selId;
    if (this.raf) { cancelAnimationFrame(this.raf); this.raf = 0; }
    if (selId) { this.pulseStart = 0; this.raf = requestAnimationFrame(this.pulse); }
  }

  private spot = true;
  private hasResults = false;
  private exhaustive = false;
  /** Spotlight: dim the imagery ~30 % while results are showing (toggle in the UI, default on). */
  async setSpotlight(on: boolean) {
    await this.ready;
    this.spot = on;
    this.map.setLayoutProperty("spotlight", "visibility", on && this.hasResults ? "visible" : "none");
  }

  whenReady() { return this.ready; }

  async setYear(year: number) {
    await this.ready;
    if (year === this.year) return;
    this.year = year;
    const m = this.map;
    if (m.getLayer("naip")) m.removeLayer("naip");
    if (m.getSource("naip")) m.removeSource("naip");
    m.addSource("naip", { type: "raster", tiles: [`/api/v1/tiles/naip/${year}/{z}/{x}/{y}.png`], tileSize: 256, minzoom: 10, maxzoom: 18 });
    m.addLayer({ id: "naip", type: "raster", source: "naip", paint: { "raster-fade-duration": 200 } }, "anchor-imagery");
  }

  /** Results: polygons (close zoom) + centroid points (dots). `exhaustive` (find_all exhaustive_scan) allows clustering. */
  async setResults(fc: FC, opts: { exhaustive?: boolean } = {}) {
    await this.ready;
    const m = this.map;
    const pts: GeoJSON.Feature[] = [], cl: GeoJSON.Feature[] = [];
    this.exhaustive = !!opts.exhaustive;
    let selId: string | null = null;
    for (const f of fc.features) {
      const c = f.geometry ? centroid(f.geometry) : null;
      if (!c) continue;
      const p = f.properties;
      if (p.sel) selId = String(p.example);
      const pt: GeoJSON.Feature = { type: "Feature", geometry: { type: "Point", coordinates: c }, properties: p };
      (this.exhaustive && p.state !== "rejected" && !p.dim ? cl : pts).push(pt);
    }
    (m.getSource("results") as GeoJSONSource).setData(fc as any);
    (m.getSource("results-pts") as GeoJSONSource).setData({ type: "FeatureCollection", features: pts });
    (m.getSource("results-cl") as GeoJSONSource).setData({ type: "FeatureCollection", features: cl });
    this.hasResults = fc.features.some((f) => f.properties.state !== "rejected");
    m.setLayoutProperty("spotlight", "visibility", this.spot && this.hasResults ? "visible" : "none");
    this.setPulsing(selId);
    if (!this.hasResults) { this.setHover(null); this.popup.remove(); }
    this.updateClusterLabels();
  }

  async setPick(fc: FC) {
    await this.ready;
    (this.map.getSource("pick") as GeoJSONSource).setData(fc as any);
  }

  /** True when the API serves this context layer as vector tiles (then no GeoJSON fetch is needed). */
  async hasVector(key: string) {
    await this.ready;
    return key in this.vt && !CONTEXT_LAYERS.find((l) => l.key === key)?.geojsonOnly;
  }

  /** Context layer: vector tiles when /api/v1/vt lists it, else the GeoJSON passed in (fallback). */
  async setContext(def: LayerDef, data: FC | null, visible: boolean) {
    await this.ready;
    const m = this.map;
    const id = `ctx-${def.key}`;
    const vt = def.geojsonOnly ? undefined : this.vt[def.key];
    if (vt) {
      // Tiles cover the whole county, so any envelope GeoJSON (agent add_layer) is already on screen.
      if (visible && !m.getSource(id)) {
        m.addSource(id, { type: "vector", tiles: [`${window.location.origin}${vt.url}`], minzoom: vt.minzoom,
          maxzoom: vt.maxzoom, ...(def.attribution ? { attribution: def.attribution } : {}) });
        this.addContextLayers(def, id, def.key);
      }
    } else if (data) {
      if (m.getSource(id)) (m.getSource(id) as GeoJSONSource).setData(data as any);
      else {
        m.addSource(id, { type: "geojson", data: data as any, ...(def.attribution ? { attribution: def.attribution } : {}) });
        this.addContextLayers(def, id);
      }
    }
    for (const lid of [id, `${id}-edge`, `${id}-casing`])
      if (m.getLayer(lid)) m.setLayoutProperty(lid, "visibility", visible ? "visible" : "none");
  }

  private addContextLayers(def: LayerDef, id: string, sourceLayer?: string) {
    const m = this.map;
    const src: any = sourceLayer ? { source: id, "source-layer": sourceLayer } : { source: id };
    if (def.kind === "fill") {
      m.addLayer({ id, type: "fill", ...src, paint: { "fill-color": def.color, "fill-opacity": def.opacity ?? 0.4 } }, "anchor-context");
      m.addLayer({ id: `${id}-edge`, type: "line", ...src, paint: { "line-color": def.edge ?? "#e8f6ff", "line-width": 1,
        "line-opacity": def.opacity != null ? Math.min(1, def.opacity * 2) : 0.8 } }, "anchor-context");
    } else if (def.kind === "circle") {
      const r = def.radius ?? 5;
      m.addLayer({ id, type: "circle", ...src, paint: { "circle-color": def.color, "circle-radius": r,
        "circle-stroke-color": "#fff", "circle-stroke-width": r < 4 ? 0.8 : 1.5 } });
    } else {
      m.addLayer({ id: `${id}-casing`, type: "line", ...src, paint: { "line-color": "#ffffff", "line-width": 5.5, "line-opacity": 0.85 },
        layout: { "line-cap": "round", "line-join": "round" } }, "anchor-context");
      m.addLayer({ id, type: "line", ...src, paint: { "line-color": def.color, "line-width": 3 },
        layout: { "line-cap": "round", "line-join": "round" } }, "anchor-context");
    }
  }

  /** Agent-provided layer (add_layer with source "envelope"). Known context keys reuse their style. */
  async setAgentLayer(layerId: string, data: FC, style?: Record<string, any>) {
    const known = CONTEXT_LAYERS.find((l) => l.key === layerId || `osm_${layerId}` === l.key);
    if (known) return this.setContext(known, data, true);
    await this.ready;
    (this.map.getSource("agent") as GeoJSONSource).setData(data as any);
    if (style?.color) this.map.setPaintProperty("agent-line", "line-color", style.color);
  }

  fitBbox(b: Bbox | number[], opts: { maxZoom?: number; padding?: number; duration?: number } = {}) {
    const [w, s, e, n] = b;
    this.map.fitBounds([[w, s], [e, n]], { padding: opts.padding ?? 60, maxZoom: opts.maxZoom ?? 17, duration: opts.duration ?? 900 });
  }

  bounds(): Bbox {
    const b = this.map.getBounds();
    return [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
  }

  resize() { this.map.resize(); }
  remove() { this.setPulsing(null); this.map.remove(); }
}

const PT_SRCS = ["results-pts", "results-cl"] as const;
const PULSE_MS = 6000;

/** Area-weighted centroid of a polygon's outer ring (largest part of a MultiPolygon); vertex mean if degenerate. */
export function centroid(g: GeoJSON.Geometry): [number, number] | null {
  let ring: number[][] | undefined;
  if (g.type === "Point") return g.coordinates as [number, number];
  if (g.type === "Polygon") ring = g.coordinates[0];
  else if (g.type === "MultiPolygon") {
    let best = -1;
    for (const poly of g.coordinates) { const a = Math.abs(ringArea(poly[0])); if (a > best) { best = a; ring = poly[0]; } }
  }
  if (!ring || !ring.length) return null;
  // Shoelace on coordinates relative to the first vertex: raw lon/lat products (~2.8e3) cancel catastrophically for
  // objects of a few m² and push the centroid tens of metres off.
  const [x0, y0] = ring[0];
  let a = 0, cx = 0, cy = 0;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0] - x0, yi = ring[i][1] - y0, xj = ring[j][0] - x0, yj = ring[j][1] - y0;
    const k = xj * yi - xi * yj;
    a += k; cx += (xj + xi) * k; cy += (yj + yi) * k;
  }
  if (Math.abs(a) < 1e-20) {
    let sx = 0, sy = 0;
    for (const p of ring) { sx += p[0]; sy += p[1]; }
    return [sx / ring.length, sy / ring.length];
  }
  return [x0 + cx / (3 * a), y0 + cy / (3 * a)];
}
function ringArea(r: number[][]) {
  let a = 0;
  const [x0, y0] = r[0];
  for (let i = 0, j = r.length - 1; i < r.length; j = i++) a += (r[j][0] - x0) * (r[i][1] - y0) - (r[i][0] - x0) * (r[j][1] - y0);
  return a / 2;
}

export function unionBbox(boxes: number[][]): Bbox | null {
  if (!boxes.length) return null;
  let [w, s, e, n] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const b of boxes) { w = Math.min(w, b[0]); s = Math.min(s, b[1]); e = Math.max(e, b[2]); n = Math.max(n, b[3]); }
  return [w, s, e, n];
}

export function inside(b: number[], view: Bbox) {
  return b[2] >= view[0] && b[0] <= view[2] && b[3] >= view[1] && b[1] <= view[3];
}
