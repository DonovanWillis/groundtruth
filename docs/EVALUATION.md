# Evaluation — **PARTIAL** (labels still being collected)

Generated 2026-11-07T14:37:30-05:00 · AOI `unc_charlotte` · NAIP 2022 · 342 indexed chips · 0 human labels on disk.

Definitions: **P@k** = labelled true-match chips in the top k ÷ k. This is a lower bound, because unlabelled matches count as misses. **hit@k** = true ÷ (true + look-alike) among the judged chips in the top k. **R@k** = share of all labelled true-match chips retrieved. find_similar is leave-one-out.

| concept | labels (T / L / in index) | +chips | search_text P@6 / P@12 / P@24 | hit@24 | R@24 | find_similar P@6 / P@24 | intended meaning in 6 picks? |
|---|---|---|---|---|---|---|---|
| swimming_pool | 0 / 0 / 0 | 0 | – | – | – | – | no true-match labels inside the indexed area yet |
| construction_site | 0 / 0 / 0 | 0 | – | – | – | – | no true-match labels inside the indexed area yet |
| warehouse | 0 / 0 / 0 | 0 | – | – | – | – | no true-match labels inside the indexed area yet |
| parking_lot | 0 / 0 / 0 | 0 | – | – | – | – | no true-match labels inside the indexed area yet |
| solar_installation | 0 / 0 / 0 | 0 | – | – | – | – | no true-match labels inside the indexed area yet |

Re-run with `python scripts/evaluate.py --aoi <aoi>` once more labels exist or the county index is built.
Only labels inside the indexed area can be scored; the rest wait for the full-county index.
