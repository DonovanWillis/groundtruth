// Imperative MapLibre wrapper: NAIP imagery, county boundary, context layers, results (outline polygons or
// cell boxes), the picked examples, and agent-added layers. React state pushes data in; clicks come back out.
import maplibregl, { GeoJSONSource, Map as MlMap } from "maplibre-gl";
import type { Bbox, FC } from "./api";
import { COLORS, CONTEXT_LAYERS, LayerDef } from "./config";

const EMPTY: FC = { type: "FeatureCollection", features: [] };

export class MapView {
  map: MlMap;
  private ready: Promise<void>;
  private year = 0;
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
    m.dragRotate.disable();
    m.touchZoomRotate.disableRotation();
    this.ready = new Promise((res) => m.on("load", () => { this.setup(); res(); }));
  }

  private setup() {
    const m = this.map;
    m.addSource("boundary", { type: "geojson", data: "/api/v1/boundary" });
    m.addLayer({ id: "anchor-imagery", type: "background", paint: { "background-opacity": 0 } });
    m.addLayer({ id: "boundary", type: "line", source: "boundary",
      paint: { "line-color": "#ffffff", "line-width": 1.4, "line-dasharray": [3, 2], "line-opacity": 0.9 } });
    m.addLayer({ id: "anchor-context", type: "background", paint: { "background-opacity": 0 } });
    for (const id of ["results", "pick", "agent"]) m.addSource(id, { type: "geojson", data: EMPTY as any });
    const color: any = ["case",
      ["==", ["get", "state"], "accepted"], COLORS.accepted,
      ["==", ["get", "change"], "new"], COLORS.new,
      ["==", ["get", "change"], "existing"], COLORS.existing,
      ["==", ["get", "change"], "unsure"], COLORS.unsure,
      COLORS.hit];
    m.addLayer({ id: "results-fill", type: "fill", source: "results", filter: ["==", ["get", "kind"], "outline"],
      paint: { "fill-color": color, "fill-opacity": ["case", ["get", "dim"], 0.08, 0.38] } });
    m.addLayer({ id: "results-line", type: "line", source: "results", filter: ["==", ["get", "kind"], "outline"],
      paint: { "line-color": color, "line-width": ["interpolate", ["linear"], ["zoom"], 14, 1.2, 18, 2.4],
        "line-opacity": ["case", ["get", "dim"], 0.35, 1] } });
    m.addLayer({ id: "results-cell", type: "line", source: "results", filter: ["==", ["get", "kind"], "cell"],
      paint: { "line-color": color, "line-width": 1.4, "line-dasharray": [2, 1.5],
        "line-opacity": ["case", ["get", "dim"], 0.3, 0.95] } });
    m.addLayer({ id: "results-hit", type: "fill", source: "results", paint: { "fill-color": "#000", "fill-opacity": 0.001 } });
    m.addLayer({ id: "results-sel", type: "line", source: "results", filter: ["==", ["get", "sel"], true],
      paint: { "line-color": "#191919", "line-width": 3.2 } });
    m.addLayer({ id: "pick", type: "line", source: "pick", paint: { "line-color": "#ffffff", "line-width": 3 } });
    m.addLayer({ id: "pick-inner", type: "line", source: "pick", paint: { "line-color": COLORS.pick, "line-width": 1.5 } });
    m.addLayer({ id: "agent-line", type: "line", source: "agent", paint: { "line-color": "#5847b8", "line-width": 2 } });
    m.on("click", "results-hit", (e) => {
      const ex = e.features?.[0]?.properties?.example;
      if (ex) this.onResultClick(ex);
    });
    m.on("mouseenter", "results-hit", () => (m.getCanvas().style.cursor = "pointer"));
    m.on("mouseleave", "results-hit", () => (m.getCanvas().style.cursor = ""));
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

  async setResults(fc: FC) {
    await this.ready;
    (this.map.getSource("results") as GeoJSONSource).setData(fc as any);
  }

  async setPick(fc: FC) {
    await this.ready;
    (this.map.getSource("pick") as GeoJSONSource).setData(fc as any);
  }

  async setContext(def: LayerDef, data: FC | null, visible: boolean) {
    await this.ready;
    const m = this.map;
    const id = `ctx-${def.key}`;
    if (data) {
      if (m.getSource(id)) (m.getSource(id) as GeoJSONSource).setData(data as any);
      else {
        m.addSource(id, { type: "geojson", data: data as any });
        if (def.kind === "fill") {
          m.addLayer({ id, type: "fill", source: id, paint: { "fill-color": def.color, "fill-opacity": 0.4 } }, "anchor-context");
          m.addLayer({ id: `${id}-edge`, type: "line", source: id, paint: { "line-color": "#e8f6ff", "line-width": 1, "line-opacity": 0.8 } }, "anchor-context");
        } else if (def.kind === "circle") {
          m.addLayer({ id, type: "circle", source: id, paint: { "circle-color": def.color, "circle-radius": 5,
            "circle-stroke-color": "#fff", "circle-stroke-width": 1.5 } });
        } else {
          m.addLayer({ id: `${id}-casing`, type: "line", source: id, paint: { "line-color": "#ffffff", "line-width": 5.5, "line-opacity": 0.85 },
            layout: { "line-cap": "round", "line-join": "round" } }, "anchor-context");
          m.addLayer({ id, type: "line", source: id, paint: { "line-color": def.color, "line-width": 3 },
            layout: { "line-cap": "round", "line-join": "round" } }, "anchor-context");
        }
      }
    }
    for (const lid of [id, `${id}-edge`, `${id}-casing`])
      if (m.getLayer(lid)) m.setLayoutProperty(lid, "visibility", visible ? "visible" : "none");
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
  remove() { this.map.remove(); }
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
