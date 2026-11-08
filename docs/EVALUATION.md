# Evaluation — 2026-11-08 (PARTIAL: labels are still being collected)

Index `chips224s192-g0.6-v3c8p192` · AOI `county` · NAIP 2022 · 107,770 chips · k = 24 · models: DINOv2 `dinov2-vitb14-cells8x8-pca192-v3`, OpenCLIP `openclip-vitb16-laion2b_s34b_b88k-whole-v3`, SAM `sam2.1-hiera-tiny` · 66 human labels (read-only).

**Bias warning:** 51 of the 59 swimming-pool labels sit in one 1.7 km stretch of the Lake Norman waterfront (see `scripts/label_qa.py`), so these scores mostly describe lakefront estates, not the whole county.

**How to read:** a hit counts as correct if its matched 16.8 m cell contains a hand-labelled true match *or* touches an OSM-mapped object of the concept. Unlabelled, unmapped real matches count as misses, so all precision numbers are **lower bounds**. `labels only` ignores OSM. find_all is leave-one-out from each true-match label, searched in a ~1.6 × 1.5 km box around it. Look-alike rejection = share of nearby look-alike labels that do *not* appear in the top k.

| concept | labels T/L (in index) | search_text P@k (labels+OSM / labels) | find_all P@k, leave-one-out (labels+OSM / labels) | look-alike rejection (direct) | intended meaning in 6 picks | OSM recall, top 200 in place | outline IoU vs OSM (median, n) |
|---|---|---|---|---|---|---|---|
| swimming_pool | 52/7 (52/5) | 0.583 / 0.0 | 0.492 / 0.485 (20 queries) | 2/5 (0.4) | no | Ballantyne: 14/25 (0.56) | 0.379 (14) |
| construction_site | 0/0 (0/0) | 0.125 / 0.0 | – / – (0 queries) | – | no | – | – (0) |
| warehouse | 0/0 (0/0) | 0.25 / 0.0 | – / – (0 queries) | – | yes | – | – (0) |
| parking_lot | 7/0 (7/0) | 0.292 / 0.0 | 0.512 / 0.018 (7 queries) | – | yes | Uptown: 337/407 (0.828) | 0.095 (30) |
| solar_installation | 0/0 (0/0) | 0.0 / 0.0 | – / – (0 queries) | – | no | – | – (0) |

**Reading the numbers honestly**
- *Intended meaning in 6 picks* uses the same lower-bound rule. A tile counts only if its cell is labelled or OSM-mapped, so a correct 'backyard pool' tile on an unlabelled, unmapped pool scores *no*. Check `data/out/*pick_candidates*.png` by eye.
- *find_all leave-one-out* draws its queries from the Lake Norman cluster (the bias above).
- *Look-alike rejection* tests each look-alike label directly: a box around it, searched from 3 true-match examples. The look-alikes are lake water, blue roofs and tennis courts.
- *OSM recall* counts only OSM-mapped objects in the place; most backyard pools are unmapped, so it can't measure precision. The 3 typical-size mapped objects used as examples are excluded.
- *Outline IoU* compares SAM 2.1 outlines prompted by one 16.8 m cell with OSM polygons. For pools the outline often includes the pool deck. For parking lots, one cell prompt outlines only part of a large lot, so IoU is low by design.
- By-eye top-24 counts for the re-rank (county) are in `docs/STATUS_FOR_MONISH.md` and the build log.

Reproduce: `bash scripts/gtg.sh python scripts/evaluate.py --aoi county` (raw numbers in `data/out/evaluation.json`).

## Checkpoint evaluation (2026-11-08, competition-ready checkpoint)
Index `chips224s192-g0.6-v3c8p192` (DINOv2 ViT-B/14 cells PCA-192, OpenCLIP ViT-B-16), SAM 2.1 hiera-tiny, Grounding DINO
tiny; dense `v1`; lidar 3DEP 2016. **Bias:** the hand labels sit mostly in the Lake Norman cluster (51 of 52 pool
labels); Ballantyne has none, so Ballantyne is scored against OSM pools (incomplete: OSM misses pools, and some
mapped pools are gone or covered).

| set | standard | dense | notes |
|---|---|---|---|
| Ballantyne, demo pick (soft negatives), OSM pools found | 16/28 | **19/28** | 261 → 373 objects |
| Ballantyne, backyard-only (OSM pools ≤ 150 m²) | 8/16 | **11/16** | |
| Ballantyne, evaluate.py examples (3 OSM pools), OSM found | 15/25 | 20/25 | 248 → 428 objects |
| Lake Norman, your labels (true pools found / look-alikes counted) | 41/51 · 0 | **46/51** · 0 | 1,208 → 1,587 objects |
| Pick semantics A/B (Ballantyne dense): hard negatives → soft | 12/28 · backyard 6/16 | 19/28 · 11/16 | soft = unpicked senses only nudge the query |
| Lidar height verifier (median nDSM ≤ 1.5 m) | 561 objects | 442 objects | same recall; roofs removed |
| Shadow rule (dark + > 8 m within 30 m) | — | removes 2/112 (Ballantyne), 1/52 (Uptown) | < 3/50 gain: OFF |
| Eye precision: dense top 50 / dense additions | — | ~49/50 / ~38/50 | Uptown additions ~7/50 → dense OFF in Uptown |

Open vocabulary (county-wide CLIP top 500 chips, top 12 by eye, baseline → adopted CLIP crop verifier + box-clipped
masks): boat dock 12 → 12, school bus lot 9 → 11, golf green 6 → 6, baseball diamond 6 → 6, construction crane 4 → 6,
tennis court 4 → 5, water tower 4 → 3, basketball court 2 → 3, cemetery 1 → 1; trampoline 0 (below 0.6 m). 48 → 53/108.

Other: lidar vs Overture building height (Uptown, 1,652 buildings) median |Δ| 3.9 m, r 0.73 · new since 2020 in
Ballantyne: 17 "new", ~9 clearly new by eye · planner: plan 35/35, declines 49/49.
