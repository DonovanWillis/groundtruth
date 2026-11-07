# Groundtruth tool contract

Every Groundtruth tool — engine function, API route, or agent action — returns **one envelope**.
Implementation: `engine/groundtruth/envelope.py` (pydantic, validated).

## Envelope

```jsonc
{
  "tool": "search_text",             // tool name
  "version": "0.1.0",                // tool version (semver; bump on behaviour change)
  "status": "ok",                    // ok | partial | declined
  "result": {
    "geojson": { "type": "FeatureCollection", "features": [ ... ] },  // EPSG:4326 always
    "metrics": { "count": 24, "area_acres_total": 3.1 }              // units in field names
  },
  "confidence": 0.62,                // 0..1 or null when not meaningful
  "method": "OpenCLIP ViT-B/32 text→image cosine over NAIP 2022 chips (FAISS IP)",
  "assumptions": ["NAIP 2022 is representative of today"],
  "limits": ["0.6 m/px: objects < ~3 m are not resolvable"],
  "sources": [{ "name": "USDA NAIP 2022", "url": "...", "date": "2022-06-02/2022-09-27", "licence": "Public domain" }],
  "steps": [{ "phase": "embed_query", "detail": "1 text", "ms": 41.2 }],
  "declined_reason": null            // required iff status == "declined"
}
```

Rules
- `status = partial` when the answer is usable but incomplete (e.g. only part of the AOI is indexed); say what is
  missing in `limits`.
- `status = declined` when the tool will not answer (out of area, asks for data about people, no index);
  `declined_reason` is mandatory, `result` is empty.
- Geometry in `result.geojson` is EPSG:4326. Measurements are computed in EPSG:32617 and carry units in the
  key: `area_m2`, `area_acres`, `dist_m`, `length_m`.
- Deterministic: same inputs + same index version ⇒ same output order (ties broken by `chip_id`).
- Features carry `id` and at least `score` (when ranked) in `properties`.

## Chip feature (returned by search tools)

```jsonc
{ "type": "Feature", "id": "2022_r0123_c0456",
  "geometry": { "type": "Polygon", "coordinates": [...] },
  "properties": { "chip_id": "2022_r0123_c0456", "score": 0.31, "rank": 1, "year": 2022,
                  "scene_id": "nc_m_3508043_sw_17_060_20220927", "thumb_url": "/chips/2022_r0123_c0456.png" } }
```

## Planned tools

| tool | input | output (`result`) | status |
|---|---|---|---|
| `search_text` | `query: str, k: int=50, year?, bbox?` | ranked chips for a text query (CLIP text→image) | slice |
| `pick_candidates` | `query: str, n: int=6, pool: int=200` | `n` diverse representative chips covering different meanings (clustered from top `pool`) + `metrics.groups` | slice |
| `find_similar` | `chip_ids: [str], exclude_ids: [str]=[], k: int=50` | chips similar to positives, pushed away from negatives (DINOv2) | slice |
| `outline` | `chip_ids` or `bbox`, `concept` | polygons of the object(s) within chips (segmentation) with `area_m2`/`area_acres` | planned |
| `refine` | `session_id, accept_ids, reject_ids` | re-ranked matches after live feedback (linear probe on embeddings) | planned |
| `add_layer` | `name` (osm_roads, fema_flood, overture_buildings, …), `bbox?` | the layer as GeoJSON | planned |
| `filter` | `features, where` (spatial/attribute predicates, e.g. `within flood zone AE`, `dist_m < 500 from I-485`) | filtered features + counts | planned |
| `measure` | `features, what` (`area_acres`, `count`, `dist_m to layer`) | per-feature + total metrics | planned |
| `export` | `features, format` (`geojson`, `csv`, `kml`) | file reference + `metrics.count` | planned |

All tools receive a `DataProvider` (dependency-injected); none fetch data themselves.
