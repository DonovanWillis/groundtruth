# Groundtruth API contract — v0.3

Every tool, whether an engine function, an HTTP route or an agent action, returns **one envelope**. Implementation:
`engine/groundtruth/envelope.py` (pydantic, validated). Example responses for every tool: `docs/fixtures/<tool>.json`.

## Transport
| | |
|---|---|
| base URL | `http://<host>:8000/api/v1` (host is announced separately; Tailscale only) |
| tool call | `POST /api/v1/tools/{tool}` with a JSON body (below) → `200` + envelope |
| health | `GET /api/v1/health` → `{ok, contract, engine_version, indexes: [{aoi, year, chips, index_version}]}` |
| tool list | `GET /api/v1/tools` → `[{tool, implemented, version}]` |
| chip image | `GET /api/v1/chips/{chip_id}.jpg?year=2022` → 224×224 JPEG (this is the `thumb_url` in features) |
| layers | `GET /api/v1/layers` → `[name]` (inputs to `add_layer`) |
| display tiles | `GET /api/v1/tiles/naip/{year}/{z}/{x}/{y}.png` (XYZ, z 10–18; USDA NAIP via Planetary Computer, cached) |
| boundary | `GET /api/v1/boundary` → the Mecklenburg County GeoJSON Feature |
| places | `GET /api/v1/places` → `{source, places: {name: [w,s,e,n]}}`: neighbourhood boxes (OSM Nominatim, ODbL) for `place` / `inside_place` |
| export files | `GET /api/v1/exports/{name}` → the file that an `export` call wrote (`metrics.download`) |
| agent stream | `GET /api/v1/events` (SSE). **Reserved**; not implemented in v0.1 |

Errors: a tool that will not answer still returns **HTTP 200** with `status: "declined"` and a `declined_reason`.
HTTP 4xx is used only for malformed requests (wrong JSON shape), and 5xx only for server faults.

## Envelope
```jsonc
{
  "tool": "search_text",                 // tool name
  "version": "0.2.0",                    // engine tool version (semver)
  "status": "ok",                        // ok | partial | declined
  "result": {
    "geojson": { "type": "FeatureCollection", "features": [] },  // always EPSG:4326
    "metrics": { "count": 24 }                                     // units in key names
  },
  "confidence": null,                    // 0..1, or null when not meaningful (similarity scores are not probabilities)
  "method": "…",                         // one line: what was computed
  "assumptions": ["…"],
  "limits": ["…"],
  "sources": [{ "name": "USDA NAIP 2022", "url": "…", "date": "2022-06-02/2022-09-27", "licence": "Public domain …" }],
  "steps": [{ "phase": "embed_query", "detail": "…", "ms": 41.2 }],   // for the work-log panel
  "declined_reason": null                // string iff status == "declined"
}
```
- `partial`: usable but incomplete. The usual cause is that only a slice is indexed, not the county; `limits` says why.
- `declined`: no result. `declined_reason` is a short code or a sentence. **`"not_implemented"`** means the route exists but the tool
  is not built yet.
- Units are in field names: `area_m2`, `area_acres`, `perimeter_m`, `dist_m_to_<layer>`. Measurements are computed in EPSG:32617.
- Deterministic: the same request on the same index version gives the same order. Ties are broken by `chip_id`.

## Ids
- **chip_id** `"{year}_e{col}_n{row}"`: a 224×224 px NAIP chip (134.4 m) on a fixed EPSG:32617 grid (stride 115.2 m).
- **cell**: 0–63, row-major from the chip's north-west corner (8×8 grid of 16.8 m cells).
- **example id**: `"chip_id"` or `"chip_id#cell"`, e.g. `"2022_e4472_n33675#30"`. Use the `example` property that
  `pick_candidates` returns. Without `#cell`, the engine guesses the cell.

## Result features (search tools)
`Polygon` = the chip footprint. Properties:
`chip_id, year, scene_id, thumb_url, chip_bbox [w,s,e,n], cell, cell_bbox [w,s,e,n], score, rank` plus tool-specific fields.
`cell_bbox` is the matched 16.8 m sub-cell. Use it to draw the hit and to prompt `outline`.

## Tools

Common optional body fields for the search tools: `year` (default = primary year, 2022) and `aoi` (default = `"county"` when
built, otherwise the largest indexed slice).

| tool | status | request body | result |
|---|---|---|---|
| `search_text` | ✅ | `{query: str, k?: int=50}` | ranked chips for a text query; `metrics.count, indexed_chips, score_max` |
| `pick_candidates` | ✅ | `{query: str, n?: int=6}` | `n` tiles, one per meaning. Properties add `sense_id, sense_label, example, raw_score, group_members[]`; `metrics.senses` |
| `find_similar` | ✅ | `{examples: [id], exclude?: [id], k?: int=50, bbox?: [w,s,e,n], rerank?: bool=false, concept?: str}` | chips whose best 16.8 m cell matches mean(examples) − 0.5·mean(exclude); overlapping duplicates removed. `rerank` (v0.3): the top ~400 are re-scored with full-resolution DINOv2 patches (8.4 m) + the concept's colour (`conf/concepts.json`); `properties.rerank {patch_sim, colour}` |
| `find_all` | ✅ (v0.3) | `{examples: [id], exclude?: [id], k?: int=200, bbox?\|place?: str, concept?: str, rerank?: bool=true, outline_top?: int=200}` | **the core tool.** Ranked, deduped matches (county, bbox or named place). `geometry` = outline polygon when cached, else the matching cell box. Properties: `example, rank, score, confidence, geometry_kind ("outline"\|"cell"), area_m2, area_acres` + the chip fields. Metrics: `count_detected` (confidence ≥ `confidence_cut`), `count_returned, outlined, outlines_queued, area_acres_total, median_area_m2`. Outlines for the top `outline_top` are computed in the background; poll `outline` for those still `cell` |
| `refine` | ✅ | `{session_id?: str, accept?: [id], reject?: [id], k?: int=50, bbox?\|place?, concept?}` | re-ranked hits from a per-session logistic regression on cell vectors; `metrics.session_id, refine_ms`. Send the returned `session_id` back to accumulate feedback. v0.3 adds `properties.confidence` (= P(match)) and `properties.why {nearest_accepted, similarity}`; < 100 ms after the first call |
| `compare_years` | ✅ (v0.3) | `{examples: [id], from_year?: int=2020, to_year?: int (= year), concept?: str}` | per example: `properties.change` = `new \| existing \| unsure \| no_data`, `change_sim, colour_now, colour_then, thumb_url_then`; metrics = counts per class. Declined when the `from_year` index for that `aoi` isn't built |
| `measure` | ✅ | `{geojson: FeatureCollection, to_layer?: str, to_layers?: [str]}` | same features with `area_m2, area_acres, perimeter_m, dist_m_to_<layer>`; metrics `count, area_acres_total, median_area_m2, min_dist_m_to_<layer>, median_dist_m_to_<layer>` |
| `add_layer` | ✅ | `{name: str, bbox?: [w,s,e,n]}` | the reference layer (see `/layers`: `osm_i485, osm_i77, osm_i85, osm_motorways, osm_light_rail, osm_light_rail_stations, osm_water, osm_unc_charlotte_campus, fema_flood_zones`) |
| `filter` | ✅ | `{geojson, where: {within_m_of?: {layer, m} \| [..], inside_place?: str, min_area_acres?, max_area_acres?, min_confidence?, min_score?, intersects_layer?, layer_where?, not_intersects_layer?}}` | features passing all predicates (ANDed); `metrics.count_in, count_out`. `within_m_of` / `inside_place` are new in v0.3 |
| `export` | ✅ | `{geojson, format: "geojson"\|"csv"\|"pdf", title?, summary?: {}}` | `metrics.file, download, bytes, content` (inline for text < 2 MB). `pdf` (v0.3) is a one-page summary with thumbnails, sources and limits |
| `outline` | ✅ (v0.2) | `{examples: [id with #cell], max?: int=12}` | one polygon per id (SAM 2.1 hiera-tiny, prompt = cell box + 5 m + centre point). Properties: `area_m2, area_acres, sam_score, ms, cached`; `metrics.area_acres_total, ms_per_outline`. **Lazy:** call it only for results on screen. Cost: ~1.2 s per new outline on CPU, ~4 ms cached. Pools often include part of the deck |

## Open fields (may change before v1)
- `/api/v1/events` (agent SSE): reserved; the event shape is not defined yet.
- `confidence` is `null` for the search tools. Calibrated probabilities are planned once labels exist.
- `aoi`: `"county"` appears when the full-county index lands. Until then only slices (`unc_charlotte`, `south_charlotte`).

## Changelog
- **v0.3 (2026-11-07)**: new tools `find_all` (core: pick → county/place results → dedupe → background outlines →
  count/acres/median) and `compare_years` (new / existing / unsure since 2020, answering Donovan's request).
  `find_similar` gains `bbox, rerank, concept`; `refine` gains `bbox/place/concept`, `properties.confidence` and `why`;
  `filter` gains `within_m_of`, `inside_place`, `min_confidence`; `measure` gains `to_layers` and median/min distances;
  `export` gains `pdf` and `metrics.download`. New routes `GET /places`, `GET /exports/{name}`. All additions are optional
  fields or new tools; v0.2 requests still work unchanged.
- **v0.2.1 (2026-11-07)**: `thumb_url` now points to the real route `/api/v1/chips/{id}.jpg` (it was `/api/chips/...`).
  Added `docs/fixtures/declined.json`. No other changes.
- **v0.2 (2026-11-07)**: `outline` implemented (was `declined: not_implemented`). No other request/response changes.
  The `/health` `contract` field is now `"0.2"`. Also added `GET /api/v1/tiles/naip/{year}/{z}/{x}/{y}.png` (display tiles) and
  `GET /api/v1/boundary` (county outline).
- **v0.1.1 (2026-11-07)**: fixtures only, no API change. `add_layer.json` shrank from 1.67 M lines (raw FEMA geometry)
  to 7 KB. Fixture geometries are simplified for readability (`_fixture.geometry_simplified_deg`). `add_layer` serves
  the simplified web build of heavy layers by default (FEMA: regulatory 1% + 0.2% zones, ~3 m simplification).
- **v0.1 (2026-11-07)**: first published contract.
  - Envelope as above; routes `/api/v1/tools/{tool}`, `/health`, `/tools`, `/chips`, `/layers`; `/events` reserved.
  - Ids `chip_id` and `chip_id#cell` on an 8×8 cell grid (index format v3, `chips224s192-g0.6-v3c8p192`).
  - `outline` declined with `not_implemented`.
