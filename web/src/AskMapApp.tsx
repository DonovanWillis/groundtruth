import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import maplibregl, { GeoJSONSource, Map as MapLibreMap, Marker } from "maplibre-gl";
import { Bbox, Envelope, Feature, Health, health, tool } from "./api";
import "./ask-map.css";

type GeocodeCandidate = { label: string; bbox: Bbox; center: [number, number]; source: string };
type SearchArea = { label: string; bbox: Bbox; source: string; kind: "address" | "drawn" };
type Message = { id: number; role: "user" | "assistant"; text: string };
type ResultSet = { title: string; features: Feature[]; envelope: Envelope; kind: "places" | "buildings" };

const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };
const START: [number, number] = [-80.8495, 35.054];
const aliases: [RegExp, string, "places" | "buildings"][] = [
  [/\b(food|eat|dining|restaurant|restaurants)\b/i, "restaurants", "places"],
  [/\b(grocery|groceries|supermarket)\b/i, "grocery stores", "places"],
  [/\b(parks?)\b/i, "parks", "places"],
  [/\b(schools?)\b/i, "schools", "places"],
  [/\b(hospitals?)\b/i, "hospitals", "places"],
  [/\b(gyms?|fitness)\b/i, "gyms", "places"],
  [/\b(buildings?|houses?|warehouses?)\b/i, "buildings", "buildings"],
];

function featureId(f: Feature, index: number): string {
  return String(f.properties.id ?? f.id ?? index);
}

function featureCenter(f: Feature): [number, number] | null {
  const g = f.geometry;
  if (!g) return null;
  if (g.type === "Point") return g.coordinates as [number, number];
  const coords: number[][] = [];
  const walk = (x: unknown): void => {
    if (!Array.isArray(x)) return;
    if (typeof x[0] === "number" && typeof x[1] === "number") coords.push(x as number[]);
    else x.forEach(walk);
  };
  if (g.type === "GeometryCollection") g.geometries.forEach((part) => { if (part.type !== "GeometryCollection") walk(part.coordinates); });
  else walk(g.coordinates);
  if (!coords.length) return null;
  return [coords.reduce((s, p) => s + p[0], 0) / coords.length,
    coords.reduce((s, p) => s + p[1], 0) / coords.length];
}

function around(center: [number, number]): Bbox {
  const [lon, lat] = center;
  const northSouth = 0.008;
  const eastWest = northSouth / Math.cos(lat * Math.PI / 180);
  return [lon - eastWest, lat - northSouth, lon + eastWest, lat + northSouth];
}

function areaFeature(bbox: Bbox): GeoJSON.FeatureCollection {
  const [w, s, e, n] = bbox;
  return { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: {
    type: "Polygon", coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
  } }] };
}

function resultLabel(f: Feature, index: number): string {
  return String(f.properties.name || f.properties.category || `Result ${index + 1}`);
}

export default function AskMapApp() {
  const mapNode = useRef<HTMLDivElement>(null);
  const map = useRef<MapLibreMap | null>(null);
  const markers = useRef<Marker[]>([]);
  const cards = useRef<Record<string, HTMLButtonElement | null>>({});
  const drawActive = useRef(false);
  const [drawMode, setDrawMode] = useState(false);
  const [area, setArea] = useState<SearchArea | null>(null);
  const [address, setAddress] = useState("");
  const [candidates, setCandidates] = useState<GeocodeCandidate[]>([]);
  const [query, setQuery] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [resultSet, setResultSet] = useState<ResultSet | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [locating, setLocating] = useState(false);
  const [problem, setProblem] = useState("");
  const [healthInfo, setHealthInfo] = useState<Health | null>(null);
  const [panelOpen, setPanelOpen] = useState(true);
  const selectedRef = useRef<string | null>(null);
  const messageId = useRef(0);
  const append = (role: Message["role"], text: string) =>
    setMessages((prev) => [...prev, { id: ++messageId.current, role, text }]);

  useEffect(() => { health().then(setHealthInfo).catch(() => setProblem("The map API is unavailable.")); }, []);

  useEffect(() => {
    if (!mapNode.current) return;
    const m = new maplibregl.Map({
      container: mapNode.current,
      style: { version: 8, sources: {}, layers: [{ id: "canvas", type: "background", paint: { "background-color": "#d8ddd8" } }] },
      center: START, zoom: 12.7, maxZoom: 19, attributionControl: false,
    });
    map.current = m;
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-left");
    m.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: "USDA NAIP imagery · Overture Maps · © OpenStreetMap contributors" }));
    m.dragRotate.disable();
    m.touchZoomRotate.disableRotation();
    m.on("load", () => {
      m.addSource("imagery", { type: "raster", tiles: ["/api/v1/tiles/naip/2022/{z}/{x}/{y}.png"], tileSize: 256, minzoom: 10, maxzoom: 18 });
      m.addLayer({ id: "imagery", type: "raster", source: "imagery", paint: { "raster-opacity": 0.86 } });
      m.addSource("search-area", { type: "geojson", data: EMPTY });
      m.addLayer({ id: "search-area-fill", type: "fill", source: "search-area", paint: { "fill-color": "#425b55", "fill-opacity": 0.12 } });
      m.addLayer({ id: "search-area-line", type: "line", source: "search-area", paint: { "line-color": "#233c36", "line-width": 2 } });
    });

    let start: [number, number] | null = null;
    m.on("mousedown", (e) => {
      if (!drawActive.current || e.originalEvent.button !== 0) return;
      e.preventDefault();
      start = [e.lngLat.lng, e.lngLat.lat];
      m.dragPan.disable();
    });
    m.on("mousemove", (e) => {
      if (!start) return;
      const bbox: Bbox = [Math.min(start[0], e.lngLat.lng), Math.min(start[1], e.lngLat.lat),
        Math.max(start[0], e.lngLat.lng), Math.max(start[1], e.lngLat.lat)];
      const source = m.getSource("search-area") as GeoJSONSource | undefined;
      source?.setData(areaFeature(bbox));
    });
    m.on("mouseup", (e) => {
      if (!start) return;
      const bbox: Bbox = [Math.min(start[0], e.lngLat.lng), Math.min(start[1], e.lngLat.lat),
        Math.max(start[0], e.lngLat.lng), Math.max(start[1], e.lngLat.lat)];
      start = null;
      m.dragPan.enable();
      drawActive.current = false;
      setDrawMode(false);
      if (bbox[2] - bbox[0] > 0.0002 && bbox[3] - bbox[1] > 0.0002) {
        setArea({ label: "Drawn area", bbox, source: "Area selected on map", kind: "drawn" });
        setResultSet(null);
        setSelected(null);
        setCandidates([]);
        setProblem("");
      }
    });
    return () => { markers.current.forEach((marker) => marker.remove()); m.remove(); map.current = null; };
  }, []);

  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const update = () => (m.getSource("search-area") as GeoJSONSource | undefined)?.setData(area ? areaFeature(area.bbox) : EMPTY);
    if (m.isStyleLoaded()) update(); else m.once("load", update);
  }, [area]);

  const selectResult = useCallback((id: string, feature?: Feature) => {
    selectedRef.current = id;
    setSelected(id);
    cards.current[id]?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    const center = feature ? featureCenter(feature) : null;
    if (center) map.current?.easeTo({ center, zoom: Math.max(map.current.getZoom(), 15), duration: 450 });
  }, []);

  useEffect(() => {
    markers.current.forEach((marker) => marker.remove());
    markers.current = [];
    const m = map.current;
    if (!m || !resultSet) return;
    resultSet.features.slice(0, 50).forEach((feature, index) => {
      const center = featureCenter(feature);
      if (!center) return;
      const id = featureId(feature, index);
      const element = document.createElement("button");
      element.type = "button";
      element.className = `ask-marker${selected === id ? " is-selected" : ""}`;
      element.textContent = String(index + 1);
      element.setAttribute("aria-label", `Select ${resultLabel(feature, index)}`);
      element.addEventListener("click", () => selectResult(id, feature));
      markers.current.push(new maplibregl.Marker({ element, anchor: "center" }).setLngLat(center).addTo(m));
    });
    return () => { markers.current.forEach((marker) => marker.remove()); markers.current = []; };
  }, [resultSet, selected, selectResult]);

  const chooseCandidate = (candidate: GeocodeCandidate) => {
    const bbox = around(candidate.center);
    setArea({ label: candidate.label, bbox, source: candidate.source, kind: "address" });
    setResultSet(null);
    setSelected(null);
    setCandidates([]);
    setAddress(candidate.label);
    setProblem("");
    map.current?.fitBounds([[bbox[0], bbox[1]], [bbox[2], bbox[3]]], { padding: 65, duration: 650 });
  };

  const locate = async (event: FormEvent) => {
    event.preventDefault();
    const q = address.trim();
    if (!q || locating) return;
    setLocating(true);
    setProblem("");
    try {
      const response = await fetch(`/api/v1/geocode?q=${encodeURIComponent(q)}`);
      if (!response.ok) throw new Error(`Address search returned HTTP ${response.status}`);
      const data = await response.json() as { candidates: GeocodeCandidate[] };
      setCandidates(data.candidates || []);
      if (!data.candidates?.length) setProblem("No matching address was found. Try a more complete Mecklenburg County address.");
      if (data.candidates?.length === 1) chooseCandidate(data.candidates[0]);
    } catch (error) { setProblem(`Address search is unavailable: ${String(error)}`); }
    finally { setLocating(false); }
  };

  const answerFollowUp = (text: string): boolean => {
    if (!resultSet) return false;
    if (/\b(rank|sort|order)\b.*\bprice\b|\bprice\b.*\b(rank|sort|order)\b/i.test(text)) {
      const priced = resultSet.features.map((f) => Number(f.properties.price_level ?? f.properties.price));
      const sourced = resultSet.features.every((f) => f.properties.price_source && Number.isFinite(Number(f.properties.price_level ?? f.properties.price)));
      if (!sourced) append("assistant", "I cannot rank these options by price. The current place source does not provide sourced prices for every result.");
      else {
        const sorted = [...resultSet.features].sort((a, b) => Number(a.properties.price_level ?? a.properties.price) - Number(b.properties.price_level ?? b.properties.price));
        setResultSet({ ...resultSet, features: sorted });
        append("assistant", `Reordered ${priced.length} options by their sourced price values.`);
      }
      return true;
    }
    const ordinal = text.match(/\b(top|first|second|third|fourth)\s+(?:option|result|place)\b/i);
    if (!ordinal) return false;
    const position = { top: 0, first: 0, second: 1, third: 2, fourth: 3 }[ordinal[1].toLowerCase() as "top" | "first" | "second" | "third" | "fourth"];
    const feature = resultSet.features[position];
    if (!feature) { append("assistant", "That option is not in the current result set."); return true; }
    selectResult(featureId(feature, position), feature);
    const label = resultLabel(feature, position);
    if (/\b(menu|food|serve|dish|eat)\b/i.test(text)) {
      const items = feature.properties.menu_items;
      if (Array.isArray(items) && feature.properties.menu_source) append("assistant", `${label}: ${items.join(", ")}. Source: ${feature.properties.menu_source}.`);
      else append("assistant", `I do not have a sourced menu for ${label}. The current place data only identifies the place and its category.`);
    } else append("assistant", `${label} is option ${position + 1} in the current results. Its listed category is ${feature.properties.category || "unavailable"}.`);
    return true;
  };

  const search = async (event: FormEvent) => {
    event.preventDefault();
    const text = query.trim();
    if (!text || busy) return;
    append("user", text);
    setQuery("");
    if (answerFollowUp(text)) return;
    if (!area) {
      append("assistant", /\bnear me\b/i.test(text)
        ? "Set an address or draw an area first. Groundtruth does not use your device location."
        : "Enter an address or draw an area on the map to set where I should search.");
      return;
    }
    const match = aliases.find(([pattern]) => pattern.test(text));
    if (!match) {
      append("assistant", "This first Ask Maps version can search restaurants, grocery stores, parks, schools, hospitals, gyms, and buildings in the chosen area. More imagery tools will be added next.");
      return;
    }
    const [, term, kind] = match;
    setBusy(true);
    setProblem("");
    try {
      const index = healthInfo?.indexes.find((item) => item.year === healthInfo.primary_year);
      const origin: [number, number] = [(area.bbox[0] + area.bbox[2]) / 2, (area.bbox[1] + area.bbox[3]) / 2];
      const envelope = await tool(kind === "places" ? "find_place" : "find_buildings", {
        ...(index ? { aoi: index.aoi } : {}), bbox: area.bbox, limit: 50,
        ...(kind === "places" ? { query: term, origin } : { kind: term }),
      });
      if (envelope.status === "declined") { append("assistant", envelope.declined_reason || "This search is unavailable."); return; }
      const features = envelope.result.geojson.features;
      setResultSet({ title: term, kind, features, envelope });
      setSelected(null);
      map.current?.fitBounds([[area.bbox[0], area.bbox[1]], [area.bbox[2], area.bbox[3]]], { padding: 80, duration: 550 });
      append("assistant", features.length
        ? `${envelope.result.metrics.truncated ? "Showing the first" : "Found"} ${features.length} ${term} in ${area.label}. Select a card or map number to inspect an option.`
        : `The available ${term} data returned no matches in ${area.label}.`);
    } catch (error) {
      append("assistant", `I could not complete that search. ${String(error)}`);
    } finally { setBusy(false); }
  };

  const toggleDraw = () => {
    drawActive.current = !drawActive.current;
    setDrawMode(drawActive.current);
    setCandidates([]);
  };

  return <div className="ask-app">
    <header className="ask-header">
      <div className="ask-brand"><span className="ask-brand-mark">G</span><span><strong>Groundtruth</strong><small>Mecklenburg County, North Carolina</small></span></div>
      <div className="ask-header-status">{healthInfo?.ok ? "Map engine ready" : "Connecting to map engine"}</div>
      <button className="ask-mobile-panel" type="button" onClick={() => setPanelOpen(!panelOpen)}>{panelOpen ? "View map" : "Open search"}</button>
    </header>

    <main className="ask-layout">
      <section className="ask-map-wrap" aria-label="Groundtruth map">
        <div className="ask-map" ref={mapNode} />
        <div className="ask-map-tools">
          <button type="button" className={drawMode ? "is-active" : ""} onClick={toggleDraw}>{drawMode ? "Drag on map to set area" : "Draw area"}</button>
          {area && <button type="button" onClick={() => { setArea(null); setResultSet(null); setSelected(null); }}>Clear area</button>}
        </div>
        <div className="ask-map-credit">2022 USDA NAIP imagery</div>
      </section>

      <aside className={`ask-panel${panelOpen ? " is-open" : ""}`} aria-label="Ask Groundtruth">
        <div className="ask-panel-head"><div className="ask-eyebrow">GROUNDTRUTH SEARCH</div><h1>Ask the map</h1><p>Choose an area, then explore what the map knows.</p></div>
        <div className="ask-context">
          <label htmlFor="ask-address">Search area</label>
          <form onSubmit={locate} className="ask-address-form"><input id="ask-address" value={address} onChange={(e) => setAddress(e.target.value)} placeholder="Enter an address in Mecklenburg County" /><button type="submit" disabled={locating}>{locating ? "Finding" : "Set area"}</button></form>
          {candidates.length > 0 && <div className="ask-candidates" role="listbox" aria-label="Address matches">{candidates.map((candidate, index) => <button type="button" key={`${candidate.label}-${index}`} onClick={() => chooseCandidate(candidate)}>{candidate.label}</button>)}</div>}
          {area ? <div className="ask-area-label"><strong>{area.label}</strong><span>{area.kind === "address" ? "Search covers about 900 m around this address" : "Search covers the drawn rectangle"}</span></div>
            : <p className="ask-context-hint">Enter an address or use Draw area on the map. Device location is never used.</p>}
        </div>
        {problem && <div className="ask-error" role="alert">{problem}</div>}

        <div className="ask-conversation" aria-live="polite">
          {messages.length === 0 && <div className="ask-intro"><strong>Start with a place search</strong><p>Try “find food near here” after setting an area. Then ask about the top option or price. Answers only use available source data.</p></div>}
          {messages.map((message) => <div key={message.id} className={`ask-message ${message.role}`}><span>{message.role === "user" ? "You" : "Groundtruth"}</span><p>{message.text}</p></div>)}
          {busy && <div className="ask-working" role="status">Searching the selected area</div>}
        </div>

        {resultSet && <section className="ask-results" aria-label="Map results"><div className="ask-results-head"><div><span>RESULTS</span><h2>{resultSet.title}</h2></div><strong>{resultSet.features.length}</strong></div>
          {resultSet.features.length > 0 && <div className="ask-card-list">{resultSet.features.map((feature, index) => {
            const id = featureId(feature, index);
            return <button key={`${id}-${index}`} ref={(node) => { cards.current[id] = node; }} type="button" className={`ask-result-card${selected === id ? " is-selected" : ""}`} onClick={() => selectResult(id, feature)}>
              <span className="ask-result-number">{index + 1}</span><span className="ask-result-copy"><strong>{resultLabel(feature, index)}</strong><small>{feature.properties.category || (resultSet.kind === "buildings" ? "Building" : "Place")}{typeof feature.properties.dist_m === "number" ? ` · ${Math.round(feature.properties.dist_m)} m straight-line` : ""}</small><small>{feature.properties.price_source ? "Price data available" : "Price and menu details unavailable"}</small></span>
            </button>;
          })}</div>}
          <p className="ask-source">Source: {resultSet.envelope.sources.map((source) => `${source.name} (${source.licence}, ${source.date})`).join(", ") || "Source unavailable"}. {resultSet.envelope.limits[0] || "Coverage varies by area."}</p>
        </section>}

        <form className="ask-prompt" onSubmit={search}><label htmlFor="ask-question">Ask a question</label><div><input id="ask-question" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Find food near here" /><button type="submit" disabled={busy || !query.trim()}>Ask</button></div></form>
      </aside>
    </main>
  </div>;
}
