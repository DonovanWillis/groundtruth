# Build log

Times are local (America/New_York).

| time | milestone |
|---|---|
| 2026-11-07 14:09 | Start. Repo foundation: MIT licence, CLAUDE.md rules, envelope + DataProvider interface, docs skeleton. |
| 2026-11-07 14:12 | Mecklenburg boundary fetched (Census TIGERweb, 1,413.18 km²). NAIP coverage check on Planetary Computer: full-county years 2022, 2020, 2018, 2016, 2014, 2012 → primary 2022, secondary 2020 (both 0.6 m). |
| 2026-11-07 14:34 | Working slice: UNC Charlotte AOI, 342 chips (NAIP 2022, 2 scenes), DINOv2 + OpenCLIP + FAISS. CPU throughput 4.4 chips/s (8 threads). Remote windowed COG reads were 265 s per AOI, so we switched to a whole-scene download (~10 MB/s with 16 streams). |
| 2026-11-07 14:40 | **Import pre-existing ORYN assets** (see docs/PRIOR_WORK.md): NC OSM extract (431 MB, data only), the shared DINOv2 weight cache, and design tokens → `web/shared/tokens.css`. Inventory in docs/ORYN_INVENTORY.md. No ORYN product code copied. |
| 2026-11-07 14:30 | Labelling page live at http://localhost:8765/label: NAIP 2022 tiles (cached PC mosaic proxy), 5 concepts, T/L/U/1–5 keys, OSM place search, journal + atomic snapshot + backup on every click, CSV/GeoJSON export. LabelStore tests pass (5). |
