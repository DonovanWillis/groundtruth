# Status for Monish (unattended run, started 16:38 ET; updated 17:15)

## 1. What you can try right now
- **Demo UI** (this PC, localhost only): http://localhost:8000/
  - Hero flow on the residential slice:
    http://localhost:8000/?aoi=south_charlotte&q=find%20swimming%20pools&pick=backyard_pool&layers=osm_i485
  - Mock agent run (clearly labelled MOCK; real tool calls): http://localhost:8000/?aoi=south_charlotte&agent=mock&tab=agent
  - When the county index lands (~18:40) the UI switches to it automatically (prefers aoi "county").
- **Labelling page:** http://localhost:8765/label (unchanged, still running).
- **Hero-flow check:** `wsl.exe -d Ubuntu-24.04 -- bash /mnt/c/Users/orynt/GeoSpatial/Geospatial-SearchEngine/scripts/demo_check.sh`
  prints PASS/FAIL and timings. Add `--record` to refresh the replay fallback.
- **Replay fallback** (if live breaks during the demo): restart the API with `GROUNDTRUTH_REPLAY=1`. Responses are marked
  `[REPLAY]` in method, steps and limits.
- **Screenshots:** `docs/media/01_ask.png` … `08_new_since_2020.png`.

## 2. Numbers
| what | number |
|---|---|
| backyard re-rank, pools in top 24 by eye (south-Charlotte slice) | 1 backyard 5–6 → **~18–20** · 3 backyard 4–5 → **~14–16** (target ≥12 ✓) · community 12–13 → **~17–18** |
| latency, warm (GPU query-time) | pick **0.8–0.9 s** (was 3.2 s) · find_all **2.1–2.5 s** · refine **45–110 ms** (360–420 ms while 200 SAM outlines run in the background) · filter 55–76 ms · measure 0.65 s · PDF 0.2 s |
| hero flow (`demo_check.sh`, slice) | PASS ×3; budgets met when warm (pick < 2 s, find_all < 3 s, refine < 1 s); a cold start right after an API restart is over budget, hence the new startup warm-up |
| compare_years (slice top 24) | 3 new / 20 existing / 1 unsure; the 3 "new" look right by eye |
| county precompute 2022 | scene 21/51 at 17:14, ~2.6 min/scene, ETA ~18:35; 2020 after that (~20:20) |
| county evaluation | PENDING (needs the county index) |

## Resume run (18:44 →): county results
- **County 2022 index verified:** 54/54 scenes, **107,770 chips**, 11.9 GB, built 18:14. 2020 started automatically at 18:14
  (scene 15/54 at 18:42, ETA ~20:40).
- **Memory 18:44:** Windows 3.4 GB free of 31.9; WSL 12.5 GB available. Mine: 2020 precompute 5.4 GB, GPU API 2.2 GB → 5.3 GB
  once the county loaded (FAISS can't mmap from /mnt/c). Windows free fell to 1.0 GB, so I **stopped my API** for the
  standalone steps (back to 2.6 GB free). Not mine (left alone): Cursor server, next-server, ORYN front.mjs.
- **County latency (warm, API on GPU, sharing it with the 2020 precompute):** pick 1.9 s · find_all county-wide 3.5 s ·
  find_all Ballantyne 3.1 s · refine 420–460 ms.
- **Re-rank on the county (3 backyard pools, top 24, by eye):** Ballantyne ~5–7 → **~21**; Lake Norman → **~19–21** with re-rank.
  The misses are blue tennis/sport courts, a blue roof and one ambiguous teal structure. Re-rank cost 5–12 s cold (thumbnail reads
  from /mnt/c + shared GPU). Sheets: `data/out/county_rerank_*.png`.
- **Evaluation (county, `docs/EVALUATION.md`):** pools: search_text P@24 0.58 (labels+OSM, lower bound) · find_all
  leave-one-out P@24 0.45 · look-alike rejection 3/5 · OSM recall in Ballantyne top 200: 16/25 (64%) · outline IoU vs OSM
  median 0.29 (outlines include the deck). Parking: OSM recall Uptown 141/407, IoU 0.09 (one cell outlines part of a lot).
  **Biased:** 51 of 59 pool labels are at Lake Norman.
- **ASUS laptop: STOPPED as instructed.** WSL has only Docker Desktop's internal `docker-desktop` distro (stopped), no
  Linux distro, so installing Ubuntu is your call. Laptop: 47.2 GB free of 63.2, 16 logical cores, 588 GB free disk. Nothing
  installed or changed there.

## ⚠ 17:16: memory pressure on this PC (earlier)
- Windows had **2.3 GB free of 31.9 GB**. Claude Code stopped two of my background tasks for that reason: the county-index
  **watcher** and the **tile-cache warm** (part done). I have **not** restarted them and started nothing new.
- Still running and healthy at 17:16: the county precompute (2022, scene 21/51; ~5.1 GB RSS), the API (~2.3 GB) and the
  label page (0.22 s).
- Because the watcher is gone, nothing wakes me when the 2022 index lands (~18:35), so the county steps (eval, county
  numbers, outline warm) **wait for you or for my next turn**. To resume:
  1. Check the index: `ls data/precompute/chips224s192-g0.6-v3c8p192/county/2022/index.json`
  2. `bash scripts/gtg.sh python scripts/evaluate.py --aoi county`
  3. `bash scripts/demo_check.sh` (it uses county automatically)
  4. `bash scripts/demo_warm.sh` (tiles + outlines)
- If memory stays tight: stop my API with `kill $(cat data/logs/api.pid)` (it frees ~2.3 GB; the UI needs it, the precompute
  doesn't). There's also a `next-server` process in WSL that isn't mine; I left it alone.

## 3. Decisions needed (max 5)
1. **Tailnet demo access:** run `scripts/tailnet_serve.sh --i-am-monish-and-approve` (`tailscale serve`, tailnet only, port 8000,
   no Funnel) when you want Don or judges on the tailnet to see it. Prepared, NOT enabled.
2. **Ping Don:** contract **v0.3.1** is tagged (find_all, compare_years = his request, refine why, outline cached_only).
   No PRs from him yet.

## Progress
| item | state | notes |
|---|---|---|
| 1 precompute | in progress | 2022 auto-builds its index at the end, then 2020 starts automatically |
| 2 backyard re-rank | done (slice) | county numbers after 2022 lands |
| 3 find-all | done | `find_all` + background outline queue; UI streams outlines |
| 4 refine | done | why = nearest accepted; outline geometry attached when cached |
| 5 filter/measure/export, contract | done | `contract-v0.3`, then `contract-v0.3.1` (fixes from the UI review) |
| 6 search across time | done (slice) | `compare_years`; county once 2020 lands |
| 7 UI | done | Devin-style; ask / pick (multi) / results / layers / filter / export / work log / MOCK agent; screenshots in docs/media |
| 8 evaluation | script ready, dry-run OK | runs on the county index |
| 9 demo hardening | mostly done | check + replay + warm (tiles running; outlines after county) |
| 10 write-up material | draft | county numbers + screenshots to fill |
| 11 ORYN merge plan | todo | after 8 + 10 |

## Decisions I made
- 16:38 Session lock at `docs/.session-lock`, HEAD `ca18aa0`. No foreign commits since.
- 16:45 Re-rank colour rules in `engine/groundtruth/conf/concepts.json` (pool cyan HSV 165–210°, weight 0.4).
- 16:45 GPU back-off: Groundtruth uses CUDA only while ≥1.5 GB VRAM is free; otherwise CPU.
- 16:50 Neighbourhood boxes from OSM Nominatim → `conf/places.json` (18 places). UNC Charlotte from the OSM campus outline.
- 16:54 compare_years: cross-year cell similarity first, colour then only supporting (NAIP 2020 is darker).
- 16:48 find_all `count_detected` = confidence ≥ 0.5, where confidence = relative score × outline quality (heuristic; said in limits).
- 17:12 UI built by one subagent (Opus) scoped to `web/src` + `docs/media`; I reviewed screenshots and committed.
- 17:14 Corrected stale method/limit text ("33.6 m / 4×4") to the actual 8×8, 16.8 m format.
- 17:14 Startup warm-up in the API (models + default index) so the first demo call is warm.
- Threaded GDAL warp isn't supported by this build (`WARP_EXTRAS` ignored), so warping stays single-threaded; precompute is CPU-bound.
- Fixed BUILD_LOG timestamps that I'd written ahead of the real time (they now match the commit times).

## Notes
- The GPU query-time approval line was present, so query-time GPU is used until Sun 12:00, capped at 4 GB.
- Donovan's branch `donovan/mcp-agent` (read-only look): MCP + mock agent + `agent/map_actions.schema.json`; no
  `agent/INTEGRATION.md`. The UI's MOCK agent follows his schema; the real SSE hook is `realAgentStream()` in
  `web/src/agent.ts` (untested; event names are an assumption). His branch is based on `5c703ab` (earlier mystery commit).
- The label test set is 59 pool labels (51 at Lake Norman) + 7 parking-lot labels at last read.
