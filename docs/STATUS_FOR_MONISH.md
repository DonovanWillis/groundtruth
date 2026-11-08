# Status for Monish: master build queue (started 2026-11-07 20:40 ET)

Older status (Part 1, contract v0.4) is in git history (`git show ce3359f:docs/STATUS_FOR_MONISH.md`).

## Try it now
- Demo UI: http://localhost:8000/. The landing chips are the four measured requests (rules planner).
- Hero-flow check: `wsl.exe -d Ubuntu-24.04 -- bash /mnt/c/Users/orynt/GeoSpatial/Geospatial-SearchEngine/scripts/demo_check.sh`
- Planner check: `bash scripts/gt.sh python scripts/planner_check.py` (WSL, repo root)
- Restart + full warm-up: `bash scripts/restart_and_warm.sh`

## Phase reports

### PHASE 0: done (licence gate)
- Full table: `docs/LICENCE_GATE.md`. Summary appended to `docs/SOURCES.md`.
- **PASS:**
  - Tools: TiTiler, rio-tiler, PDAL, Valhalla, OSRM, deck.gl, PMTiles, tippecanoe, Planetiler, Martin, TorchGeo code, MCP Python SDK, llama.cpp.
  - Data: USGS 3DEP (public domain).
  - Weights: SAM 2/2.1, Clay v1.5, Qwen3 1.7B/4B/8B, Phi-3.5/4-mini, Mistral-7B-v0.3.
  - Overture places.
- **PASS with a note** (permissive weights, but non-commercial datasets in their training lineage):
  - Weights: Grounding DINO, Florence-2.
  - DuckDB spatial: bundles GEOS, which is LGPL-2.1.
  - ODbL share-alike: Overture buildings, Geofabrik NC.
- **UNCLEAR, so not used:**
  - GeoAI SolarPanel / ParkingSplot / Car detector weights: the training data is undocumented, and the car model is trained on 7 cm imagery.
  - Satlas NAIP, DOFA, Panopticon weights.
- **FAIL:**
  - DINOv3 (custom licence: termination and changeable terms; no weapons/military use; same-licence redistribution).
  - OWLv2 (trained by Google on WebLI).
  - SAM 3, Qwen2.5-3B (non-commercial), Llama, Gemma.
  - TorchGeo CC-BY-NC weights, OlmoEarth.

### PHASE 1.4: done (demo scope)
- **Landing chips** (rules planner): "find swimming pools", "pools within 1 km of I-485 in Ballantyne", "pools in flood zones in Matthews", "new pools since 2020 in Ballantyne".
- **Solar and parking:** still typeable. Their envelopes carry an `EXPERIMENTAL` limit (`conf/concepts.json` → `experimental`).
- **Warm-up:**
  1. The hero flow runs first; health turns ok at about 20–31 s.
  2. In the background: pool find_all for all 8 neighbourhoods plus the 4 landing chips (about 4.5 min).
- **Caches:**
  - Scan results (scan cache).
  - Deterministic envelopes are memoised: pick, find_all once its outlines are final, compare_years, add_layer.
  - A memoised reply shows a single `memo` step that states the original compute time.
- **Landing chips, warm (ms):**

| request | before caches | after |
|---|---|---|
| find swimming pools | 1,476 | 77 |
| pools within 1 km of I-485 in Ballantyne | 747 | 153 |
| pools in flood zones in Matthews | 2,407 | 1,438 (memo applies from the next warm-up) |
| new pools since 2020 in Ballantyne | 2,286 | 163 |

## Decisions I made
- **Licence lineage:** I accepted weights released under Apache/MIT even when their training datasets are research-only. This is the same reading the repo already applied to SAM 2.1 and OpenCLIP. It lets Grounding DINO and Florence-2 enter the A/Bs. Listed below for your veto.
- **OWLv2 is out:** I read "anything Google" as including weights Google trained on its own WebLI data. Grounding DINO is the open-vocabulary detector.
- **GeoAI solar, parking and car detectors are not used:** their weights are UNCLEAR, and the rule says unclear means don't use. Phase 3 therefore uses only BuildingFootprintExtractor (PASS with a note), and solar and parking get the Grounding DINO / inventory route instead.
- **DINOv3 is out.** The bake-off is DINOv2 vs Clay v1.5.
- **Disk space:** the WSL disk lives on C:, which has 80 GB free, so I count C: free space as the limit for local COGs.

## Decisions needed (max 3)
1. **Licence lineage:** do you accept Grounding DINO and Florence-2? Their weights are Apache/MIT, but their training data includes Objects365 and Flickr30k, which are academic or non-commercial. If you say no, open-vocabulary search falls back to CLIP only.
2. **OWLv2** is Apache-2.0 but trained by Google on WebLI. Does your Google ban cover Google-trained weights? I assumed yes.
3. **GeoAI solar, parking and car weights** are tagged MIT, but their training data is undocumented. Should I test them as internal-only baselines, or skip them (current choice)?

## Free RAM / VRAM / disk
See the latest phase entry in `docs/BUILD_LOG.md`.
