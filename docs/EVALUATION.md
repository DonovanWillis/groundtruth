# Evaluation — 2026-11-07 (PARTIAL: labels are still being collected)

Index `chips224s192-g0.6-v3c8p192` · AOI `county` · NAIP 2022 · 107,770 chips · k = 24 · models: DINOv2 `dinov2-vitb14-cells8x8-pca192-v3`, OpenCLIP `openclip-vitb16-laion2b_s34b_b88k-whole-v3`, SAM `sam2.1-hiera-tiny` · 66 human labels (read-only).

**Bias warning:** 51 of the 59 swimming-pool labels sit in one 1.7 km stretch of the Lake Norman waterfront (see `scripts/label_qa.py`), so these scores mostly describe lakefront estates, not the whole county.

**How to read:** a hit counts as correct if its matched 16.8 m cell contains a hand-labelled true match *or* touches an OSM-mapped object of the concept. Unlabelled, unmapped real matches count as misses, so all precision numbers are **lower bounds**. `labels only` ignores OSM. find_all is leave-one-out from each true-match label, searched in a ~1.6 × 1.5 km box around it. Look-alike rejection = share of nearby look-alike labels that do *not* appear in the top k.

| concept | labels T/L (in index) | search_text P@k (labels+OSM / labels) | find_all P@k, leave-one-out (labels+OSM / labels) | look-alike rejection (direct) | intended meaning in 6 picks | OSM recall, top 200 in place | outline IoU vs OSM (median, n) |
|---|---|---|---|---|---|---|---|
| swimming_pool | 52/7 (52/5) | 0.583 / 0.0 | 0.496 / 0.487 (20 queries) | 2/5 (0.4) | no | Ballantyne: 14/25 (0.56) | 0.379 (14) |
| construction_site | 0/0 (0/0) | 0.125 / 0.0 | – / – (0 queries) | – | no | – | – (0) |
| warehouse | 0/0 (0/0) | 0.25 / 0.0 | – / – (0 queries) | – | yes | – | – (0) |
| parking_lot | 7/0 (7/0) | 0.292 / 0.0 | 0.512 / 0.018 (7 queries) | – | yes | Uptown: 338/407 (0.83) | 0.095 (30) |
| solar_installation | 0/0 (0/0) | 0.0 / 0.0 | – / – (0 queries) | – | no | – | – (0) |

**Reading the numbers honestly**
- *Intended meaning in 6 picks* uses the same lower-bound rule. A tile counts only if its cell is labelled or OSM-mapped, so a correct 'backyard pool' tile on an unlabelled, unmapped pool scores *no*. Check `data/out/*pick_candidates*.png` by eye.
- *find_all leave-one-out* draws its queries from the Lake Norman cluster (the bias above).
- *Look-alike rejection* tests each look-alike label directly: a box around it, searched from 3 true-match examples. The look-alikes are lake water, blue roofs and tennis courts.
- *OSM recall* counts only OSM-mapped objects in the place; most backyard pools are unmapped, so it can't measure precision. The 3 typical-size mapped objects used as examples are excluded.
- *Outline IoU* compares SAM 2.1 outlines prompted by one 16.8 m cell with OSM polygons. For pools the outline often includes the pool deck. For parking lots, one cell prompt outlines only part of a large lot, so IoU is low by design.
- By-eye top-24 counts for the re-rank (county) are in `docs/STATUS_FOR_MONISH.md` and the build log.

Reproduce: `bash scripts/gtg.sh python scripts/evaluate.py --aoi county` (raw numbers in `data/out/evaluation.json`).
