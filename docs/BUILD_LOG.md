# Build log

Times are local (America/New_York).

| time | milestone |
|---|---|
| 2026-11-07 14:09 | Start. Repo foundation: MIT licence, CLAUDE.md rules, envelope + DataProvider interface, docs skeleton. |
| 2026-11-07 14:12 | Mecklenburg boundary fetched (Census TIGERweb, 1,413.18 km²). NAIP coverage check on Planetary Computer: full-county years 2022, 2020, 2018, 2016, 2014, 2012 → primary 2022, secondary 2020 (both 0.6 m). |
| 2026-11-07 14:34 | Working slice: UNC Charlotte AOI, 342 chips (NAIP 2022, 2 scenes), DINOv2 + OpenCLIP + FAISS. CPU throughput 4.4 chips/s (8 threads). Remote windowed COG reads were 265 s per AOI, so we switched to a whole-scene download (~10 MB/s with 16 streams). |
| 2026-11-07 14:40 | **Import pre-existing ORYN assets** (see docs/PRIOR_WORK.md): NC OSM extract (431 MB, data only), the shared DINOv2 weight cache, and design tokens → `web/shared/tokens.css`. Inventory in docs/ORYN_INVENTORY.md. No ORYN product code copied. |
| 2026-11-07 15:50 | **Format v3 approved and locked (tag `precompute-v3`):** DINOv2 8×8 cells, PCA-192 (fixed basis in repo, 91.9% variance) + whole-chip CLIP. find_similar from a pool cell: 2/24 → 10/24. pick_candidates: sense prompts from `conf/senses.json` + CLIP cell localisation, ≥4 distinct meanings incl. pond on both slices. Colab notebook + SHA-256 shard hand-off (tamper-tested). FEMA web layer 8.4 MB. API (`api/app.py`, all 9 tool routes; outline = not_implemented). Contract v0.1 tagged, then v0.1.1 (fixture size fix). Mac mini: SSH OK, setup on hold (ORYN services present). |
| 2026-11-07 14:55 | Label page fix: an invalid MapLibre style (`glyphs: undefined`) stopped the map from loading, plus a boot race. Server restarted (approved) to apply the Lake Norman geocode fix. Verified in headless Edge. |
| 2026-11-07 15:20 | **Storage format locked (v2):** DINOv2 4×4 patch-cell grid (N,16,768) fp16 + whole-chip OpenCLIP (N,1,512) fp16. CLIP 2×2 sub-crops cost 2.6× embed time and added 0 clear pools in the A/B (6 vs 6 of 24), so they are dropped everywhere. Engine v0.2: sub-cell find_similar, sense-prompt pick_candidates, refine, measure, filter, export. FEMA NFHL: 34,704 polygons. |
| 2026-11-07 14:38 | Overture 2026-10-21.0 clipped to the county via DuckDB: 79,385 places, 393,968 buildings (98% OSM-sourced). The OSM/FEMA pass was stopped by host memory pressure; still to do. Evaluation hook runs (0 labels so far). Full-county precompute estimated at ~7 h/year on CPU, so it was **not started here**; see docs/PRECOMPUTE.md. |
| 2026-11-07 14:30 | Labelling page live at http://localhost:8765/label: NAIP 2022 tiles (cached PC mosaic proxy), 5 concepts, T/L/U/1–5 keys, OSM place search, journal + atomic snapshot + backup on every click, CSV/GeoJSON export. LabelStore tests pass (5). |
