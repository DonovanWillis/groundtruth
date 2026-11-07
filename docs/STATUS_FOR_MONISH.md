# Status for Monish (unattended run, started 16:38 ET; updated 16:55)

## 1. What you can try right now
- Labelling page: http://localhost:8765/label (unchanged, still running).
- Demo UI + API on this PC (localhost only): http://localhost:8000/ (slice indexes; the county index lands ~18:30).
  - Hero deep link: http://localhost:8000/?q=swimming%20pool&pick=backyard_pool
- API smoke (WSL): `bash scripts/gtg.sh python scripts/smoke_v03.py south_charlotte` runs pick → find_all → refine ×3 → filter
  within 1 km of I-485 → measure → CSV + PDF export.

## 2. Numbers so far
| what | number |
|---|---|
| backyard re-rank, pools in top 24 by eye (south-Charlotte slice) | 1 backyard 5–6 → **~18–20** · 3 backyard 4–5 → **~14–16** (target ≥12 ✓) · community 12–13 → **~17–18** |
| re-rank cost | ~1.8 s/query on the 4060 (400 candidates), faster once patches are cached |
| find_all (slice, warm) | 2.1 s · refine 45–100 ms after the first call · filter 76 ms · measure 0.65 s · PDF 0.2 s |
| compare_years (slice top 24) | 3 new / 20 existing / 1 unsure; the 3 "new" look right by eye |
| county precompute 2022 | scene 12/51 at 16:54, ~17 chips/s overall (65 chips/s on the GPU; CPU warp is the bottleneck), ETA ~18:30; 2020 after that (~20:10) |

## 3. Decisions needed (max 5)
- (none blocking yet)

## Progress
| item | state | notes |
|---|---|---|
| 1 precompute | in progress | 2022 12/51; auto-continues to 2020 |
| 2 backyard re-rank | done (slice) | county numbers once the 2022 index lands |
| 3 find-all | done | `find_all`: background outline queue, dedupe, confidence, honest limits |
| 4 refine | done | session pool, why = nearest accepted |
| 5 filter/measure/export, contract v0.3 | done | tag `contract-v0.3` pushed → **ping Don: contract-v0.3** (adds find_all + compare_years, his request) |
| 6 search across time | done (slice) | `compare_years`; county once 2020 lands |
| 7 UI | in progress | subagent working in `web/` |
| 8 evaluation | script ready | needs the county index |
| 9 demo hardening | todo | |
| 10 write-up material | todo | |
| 11 ORYN merge plan | todo | |

## Decisions I made
- 16:38 Session lock at `docs/.session-lock`, HEAD `ca18aa0`. No foreign commits since.
- 16:45 Re-rank colour rules live in `engine/groundtruth/conf/concepts.json` (pool cyan HSV 165–210°, weight 0.4).
- 16:45 GPU back-off: Groundtruth uses CUDA only while ≥1.5 GB VRAM is free (`GROUNDTRUTH_GPU_MIN_FREE_GB`); otherwise CPU.
- 16:50 Neighbourhood boxes from OSM Nominatim → `conf/places.json` (18 places). UNC Charlotte comes from the OSM campus outline.
- 17:00 compare_years: cross-year cell similarity is the primary signal, colour then is only supporting (NAIP 2020 is darker).
- 17:00 find_all `count_detected` = confidence ≥ 0.5, where confidence = relative score × outline quality (heuristic, stated in limits).
- Threaded GDAL warp is not supported by this rasterio/GDAL build (`WARP_EXTRAS` ignored), so warping stays single-threaded.

## Notes
- The GPU query-time approval line was present, so query-time GPU is used until Sun 12:00, capped at 4 GB.
- Donovan's branch `donovan/mcp-agent` (read-only look) has MCP + mock agent and `agent/map_actions.schema.json`;
  no `agent/INTEGRATION.md`. His branch is based on `5c703ab` (one of the earlier mystery commits).
