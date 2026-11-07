"""Step 6: evaluate the engine against the human labels in data/labels/ (read-only; never writes labels).

  python scripts/evaluate.py [--aoi unc_charlotte] [--year 2022]

A chip is a POSITIVE for a concept if a "true_match" label of that concept falls inside it, a LOOK-ALIKE if only
"look_alike" labels do. Labels are sparse (not every pool is labelled), so we report:
  P@k        positives in top-k / k          (lower bound: unlabelled true matches count as misses)
  hit@k      positives in top-k / (positives + look-alikes in top-k)   (precision among judged chips)
  R@k        positives in top-k / all positive chips in the index
find_similar is leave-one-out: each positive chip queries for the other positives.
pick_candidates: does a true-match chip appear among the 6 representatives (and does a look-alike)?
Writes docs/EVALUATION.md (marked PARTIAL until labels are complete) and data/out/evaluation.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
from groundtruth import config  # noqa: E402
from groundtruth.geo import MEASURE_CRS, WGS84, transformer  # noqa: E402
from groundtruth.labels import CONCEPTS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
QUERIES = {"swimming_pool": "swimming pool", "construction_site": "construction site", "warehouse": "warehouse",
           "parking_lot": "parking lot", "solar_installation": "solar panels"}
KS = (6, 12, 24)


def load_labels() -> list[dict]:
    p = config.DATA / "labels" / "labels.geojson"
    if not p.exists():
        return []
    return json.loads(p.read_text())["features"]


def chips_containing(index, lon: float, lat: float) -> list[int]:
    x, y = transformer(WGS84, MEASURE_CRS).transform(lon, lat)
    m = index.meta
    hit = np.where((m["x0_m"] <= x) & (x < m["x0_m"] + config.CHIP_M) &
                   (m["y0_m"] <= y) & (y < m["y0_m"] + config.CHIP_M))[0]
    return [int(i) for i in hit]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aoi", default="unc_charlotte")
    ap.add_argument("--year", type=int, default=None)
    a = ap.parse_args()
    from groundtruth.providers.public import PublicDataProvider
    from groundtruth.tools import Engine

    prov = PublicDataProvider()
    eng = Engine(prov, aoi=a.aoi, year=a.year)
    labels = load_labels()
    pos: dict[str, set[int]] = defaultdict(set)
    neg: dict[str, set[int]] = defaultdict(set)
    n_lab = defaultdict(lambda: {"true_match": 0, "look_alike": 0, "in_index": 0})
    for f in labels:
        p = f["properties"]
        c, k = p["concept"], p["kind"]
        n_lab[c][k] += 1
        ids = chips_containing(eng.index, *f["geometry"]["coordinates"][:2])
        if ids:
            n_lab[c]["in_index"] += 1
        (pos if k == "true_match" else neg)[c].update(ids)
    for c in CONCEPTS:
        neg[c] -= pos[c]

    results = {}
    for c in CONCEPTS:
        r: dict = {"query": QUERIES[c], "labels": dict(n_lab[c]), "positive_chips": len(pos[c]),
                   "lookalike_chips": len(neg[c])}
        if not pos[c]:
            r["note"] = "no true-match labels inside the indexed area yet"
            results[c] = r
            continue
        st = eng.search_text(QUERIES[c], k=max(KS))
        ranked = [eng.index.pos[f["id"]] for f in st.result.geojson["features"]]
        r["search_text"] = {}
        for k in KS:
            top = ranked[:k]
            tp = sum(i in pos[c] for i in top)
            fp_judged = sum(i in neg[c] for i in top)
            r["search_text"][f"@{k}"] = {"P": round(tp / k, 3),
                                         "hit": round(tp / (tp + fp_judged), 3) if tp + fp_judged else None,
                                         "R": round(tp / len(pos[c]), 3)}
        pc = eng.pick_candidates(QUERIES[c])
        reps = [eng.index.pos[f["id"]] for f in pc.result.geojson["features"]]
        r["pick_candidates"] = {"intended_in_first_6": any(i in pos[c] for i in reps),
                                "true_match_reps": sum(i in pos[c] for i in reps),
                                "lookalike_reps": sum(i in neg[c] for i in reps)}
        if len(pos[c]) >= 2:
            per_k = {k: [] for k in KS}
            for q in sorted(pos[c]):
                fs = eng.find_similar([eng.index.ids[q]], exclude_ids=[eng.index.ids[i] for i in neg[c]], k=max(KS))
                got = [eng.index.pos[f["id"]] for f in fs.result.geojson["features"]]
                others = pos[c] - {q}
                for k in KS:
                    per_k[k].append(sum(i in others for i in got[:k]) / k)
            r["find_similar_loo"] = {f"@{k}": {"P": round(float(np.mean(v)), 3)} for k, v in per_k.items()}
        results[c] = r

    total = len(labels)
    out = {"generated": datetime.now().astimezone().isoformat(timespec="seconds"), "aoi": a.aoi,
           "year": eng.year, "index_chips": len(eng.index), "labels_total": total, "partial": True,
           "results": results}
    (config.DATA / "out").mkdir(parents=True, exist_ok=True)
    (config.DATA / "out" / "evaluation.json").write_text(json.dumps(out, indent=1))
    write_md(out)
    print(json.dumps(out, indent=1))


def write_md(out: dict) -> None:
    L = [f"# Evaluation — **PARTIAL** (labels still being collected)", "",
         f"Generated {out['generated']} · AOI `{out['aoi']}` · NAIP {out['year']} · {out['index_chips']} indexed chips · "
         f"{out['labels_total']} human labels on disk.", "",
         "Definitions: **P@k** = labelled true-match chips in the top k ÷ k. This is a lower bound, because unlabelled "
         "matches count as misses. **hit@k** = true ÷ (true + look-alike) among the judged chips in the top k. "
         "**R@k** = share of all labelled true-match chips retrieved. find_similar is leave-one-out.", "",
         "| concept | labels (T / L / in index) | +chips | search_text P@6 / P@12 / P@24 | hit@24 | R@24 | "
         "find_similar P@6 / P@24 | intended meaning in 6 picks? |",
         "|---|---|---|---|---|---|---|---|"]
    for c, r in out["results"].items():
        lab = r["labels"]
        base = f"| {c} | {lab.get('true_match', 0)} / {lab.get('look_alike', 0)} / {lab.get('in_index', 0)} | {r['positive_chips']} "
        if "search_text" not in r:
            L.append(base + f"| – | – | – | – | {r.get('note', '')} |")
            continue
        s = r["search_text"]
        fs = r.get("find_similar_loo", {})
        L.append(base + f"| {s['@6']['P']} / {s['@12']['P']} / {s['@24']['P']} | {s['@24']['hit']} | {s['@24']['R']} | "
                 f"{fs.get('@6', {}).get('P', '–')} / {fs.get('@24', {}).get('P', '–')} | "
                 f"{'yes' if r['pick_candidates']['intended_in_first_6'] else 'no'} "
                 f"({r['pick_candidates']['true_match_reps']} true, {r['pick_candidates']['lookalike_reps']} look-alike) |")
    L += ["", "Re-run with `python scripts/evaluate.py --aoi <aoi>` once more labels exist or the county index is built.",
          "Only labels inside the indexed area can be scored; the rest wait for the full-county index."]
    (ROOT / "docs" / "EVALUATION.md").write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
