"""Evaluate against Monish's hand labels (read-only) + the OSM weak reference set. Writes docs/EVALUATION.md.

  python scripts/evaluate.py [--aoi county] [--year 2022] [--k 24]

Per concept with labels:
- search_text P@k: hits whose matching cell contains a true-match label OR touches an OSM-mapped object of the concept
  (known positives; unlabelled real matches count as misses → lower bound). Also P@k by labels only.
- find_all (re-ranked) leave-one-out from each true-match label (searched inside a 1.5 km box around it so local labels
  can be found), P@k with the same rule; look-alike rejection rate = 1 − (look-alike labels hit ÷ look-alikes nearby).
- pick_candidates: is a true-match chip (or an OSM-positive cell) among the 6 tiles?
OSM reference (swimming pools): recall of OSM pools inside each label cluster's box by find_all top 200; outline IoU vs
OSM pool polygons for outlined hits that overlap one.
Labels are never modified. Model versions are recorded in the report.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
from shapely.geometry import box, shape
from shapely.strtree import STRtree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
from groundtruth import config  # noqa: E402
from groundtruth.geo import MEASURE_CRS, WGS84, to_measure, transformer  # noqa: E402
from groundtruth.labels import CONCEPTS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
QUERIES = {"swimming_pool": "swimming pool", "construction_site": "construction site", "warehouse": "warehouse",
           "parking_lot": "parking lot", "solar_installation": "solar panels"}


def label_cell(index, lon: float, lat: float) -> tuple[int, int] | None:
    """Chip containing the click where it is most central, and the 8×8 cell under the click."""
    x, y = transformer(WGS84, MEASURE_CRS).transform(lon, lat)
    m = index.meta
    cand = np.where((m["x0_m"] <= x) & (x < m["x0_m"] + config.CHIP_M) & (m["y0_m"] <= y) & (y < m["y0_m"] + config.CHIP_M))[0]
    if not len(cand):
        return None
    cx, cy = m["x0_m"][cand] + config.CHIP_M / 2, m["y0_m"][cand] + config.CHIP_M / 2
    i = int(cand[np.argmin((cx - x) ** 2 + (cy - y) ** 2)])
    size = config.CHIP_M / index.grid
    col = int((x - m["x0_m"][i]) // size)
    row = int((m["y0_m"][i] + config.CHIP_M - y) // size)
    return i, row * index.grid + col


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aoi", default="county")
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--k", type=int, default=24)
    ap.add_argument("--max-loo", type=int, default=20, help="max leave-one-out queries per concept")
    a = ap.parse_args()
    from groundtruth.embed import CLIP_ID, DINO_ID
    from groundtruth.providers.public import PublicDataProvider
    from groundtruth.tools import Engine

    eng = Engine(PublicDataProvider(), aoi=a.aoi, year=a.year)
    k = a.k
    labels = json.loads((config.DATA / "labels" / "labels.geojson").read_text())["features"]
    by_c: dict[str, dict[str, list]] = defaultdict(lambda: {"true_match": [], "look_alike": []})
    for f in labels:
        p = f["properties"]
        lc = label_cell(eng.index, *f["geometry"]["coordinates"][:2])
        by_c[p["concept"]][p["kind"]].append({"id": p["id"], "lonlat": f["geometry"]["coordinates"][:2], "cell": lc})
    results: dict[str, dict] = {}
    for c in CONCEPTS:
        L = by_c.get(c, {"true_match": [], "look_alike": []})
        tm = [x for x in L["true_match"] if x["cell"]]
        la = [x for x in L["look_alike"] if x["cell"]]
        r: dict = {"labels": {"true_match": len(L["true_match"]), "look_alike": len(L["look_alike"]),
                              "true_in_index": len(tm), "lookalike_in_index": len(la)}}
        osm_p = config.DATA / "reference" / f"osm_{c}.geojson"
        osm = [shape(f["geometry"]) for f in json.loads(osm_p.read_text())["features"]] if osm_p.exists() else []
        osm_m = [to_measure(g if g.geom_type != "Point" else g.buffer(0.00004)) for g in osm]
        tree = STRtree(osm_m) if osm_m else None
        true_cells = {(x["cell"][0], x["cell"][1]) for x in tm}
        look_cells = {(x["cell"][0], x["cell"][1]) for x in la}

        def cell_box_m(i: int, cell: int):
            return box(*eng.index.cell_bounds_m(i, cell))

        def is_pos(i: int, cell: int, labels_only: bool = False) -> bool:
            b = cell_box_m(i, cell)
            for (li, lcell) in true_cells:
                if box(*eng.index.cell_bounds_m(li, lcell)).intersects(b):
                    return True
            return (not labels_only) and tree is not None and len(tree.query(b, predicate="intersects")) > 0

        def is_look(i: int, cell: int) -> bool:
            b = cell_box_m(i, cell)
            return any(box(*eng.index.cell_bounds_m(li, lcell)).intersects(b) for (li, lcell) in look_cells)

        if not tm and not osm:
            r["note"] = "no labels or reference for this concept"
            results[c] = r
            continue
        # search_text
        st = eng.search_text(QUERIES[c], k=k)
        hits = [(eng.index.pos[f["id"]], f["properties"]["cell"]) for f in st.result.geojson["features"]]
        r["search_text"] = {"P@k_labels_or_osm": round(sum(is_pos(i, cc) for i, cc in hits) / k, 3),
                            "P@k_labels_only": round(sum(is_pos(i, cc, True) for i, cc in hits) / k, 3)}
        # pick_candidates
        pc = eng.pick_candidates(QUERIES[c])
        reps = [(eng.index.pos[f["properties"]["chip_id"]], f["properties"]["cell"], f["properties"]["sense_id"])
                for f in pc.result.geojson["features"]]
        r["pick_candidates"] = {"intended_in_6": any(is_pos(i, cc) for i, cc, _ in reps),
                                "senses_with_positive": [s for i, cc, s in reps if is_pos(i, cc)]}
        # find_all leave-one-out, local box
        if tm:
            ps, ps_lab, look_hit, look_near, ious = [], [], 0, 0, []
            for x in tm[: a.max_loo]:
                lon, lat = x["lonlat"]
                bb = [lon - 0.009, lat - 0.007, lon + 0.009, lat + 0.007]  # ~1.6 × 1.5 km
                env = eng.find_all([f"{eng.index.ids[x['cell'][0]]}#{x['cell'][1]}"], k=k, bbox=bb, concept=c,
                                   rerank=True, outline_top=0)
                fh = [(eng.index.pos[f["properties"]["chip_id"]], f["properties"]["cell"]) for f in env.result.geojson["features"]]
                fh = [h for h in fh if h != tuple(x["cell"])]
                ps.append(sum(is_pos(i, cc) for i, cc in fh) / k)
                ps_lab.append(sum(is_pos(i, cc, True) for i, cc in fh) / k)
                bbm = to_measure(box(*bb))
                near = [lc for lc in look_cells if bbm.intersects(box(*eng.index.cell_bounds_m(*lc)))]
                look_near += len(near)
                look_hit += sum(1 for i, cc in fh if is_look(i, cc))
                for f in env.result.geojson["features"]:
                    if f["properties"]["geometry_kind"] == "outline" and tree is not None:
                        g = to_measure(shape(f["geometry"]))
                        for j in tree.query(g, predicate="intersects"):
                            o = osm_m[int(j)]
                            if o.geom_type in ("Polygon", "MultiPolygon"):
                                ious.append(g.intersection(o).area / max(g.union(o).area, 1e-9))
            r["find_all_loo"] = {"queries": len(ps), "P@k_labels_or_osm": round(float(np.mean(ps)), 3),
                                 "P@k_labels_only": round(float(np.mean(ps_lab)), 3),
                                 "lookalike_rejection": None if not look_near else round(1 - look_hit / look_near, 3),
                                 "lookalikes_nearby": look_near,
                                 "outline_iou_vs_osm_median": round(float(np.median(ious)), 3) if ious else None,
                                 "outline_iou_n": len(ious)}
        # OSM recall inside the main label cluster box (pools)
        if tm and osm:
            lons = [x["lonlat"][0] for x in tm]; lats = [x["lonlat"][1] for x in tm]
            bb = [float(np.median(lons)) - 0.01, float(np.median(lats)) - 0.008,
                  float(np.median(lons)) + 0.01, float(np.median(lats)) + 0.008]
            bbm = to_measure(box(*bb))
            in_box = [o for o in osm_m if o.intersects(bbm)]
            x = tm[0]
            env = eng.find_all([f"{eng.index.ids[x['cell'][0]]}#{x['cell'][1]}"], k=200, bbox=bb, concept=c,
                               rerank=True, outline_top=0)
            cells = [to_measure(box(*f["properties"]["cell_bbox"])) for f in env.result.geojson["features"]]
            found = sum(1 for o in in_box if any(o.intersects(cb) for cb in cells))
            r["osm_recall_top200_in_cluster_box"] = {"osm_objects": len(in_box), "found": found,
                                                     "recall": round(found / len(in_box), 3) if in_box else None,
                                                     "bbox": [round(v, 4) for v in bb]}
        results[c] = r
        print(c, json.dumps(r)[:400])
    out = {"generated": datetime.now().astimezone().isoformat(timespec="seconds"), "aoi": a.aoi, "year": eng.year,
           "index_version": config.INDEX_VERSION, "index_chips": len(eng.index), "k": k,
           "models": {"dino": DINO_ID, "clip": CLIP_ID, "sam": "sam2.1-hiera-tiny"}, "labels_total": len(labels),
           "results": results}
    (config.DATA / "out").mkdir(parents=True, exist_ok=True)
    (config.DATA / "out" / "evaluation.json").write_text(json.dumps(out, indent=1))
    write_md(out)


def write_md(o: dict) -> None:
    L = [f"# Evaluation — {o['generated'][:10]} (PARTIAL: labels are still being collected)", "",
         f"Index `{o['index_version']}` · AOI `{o['aoi']}` · NAIP {o['year']} · {o['index_chips']:,} chips · k = {o['k']} · "
         f"models: DINOv2 `{o['models']['dino']}`, OpenCLIP `{o['models']['clip']}`, SAM `{o['models']['sam']}` · "
         f"{o['labels_total']} human labels (read-only).", "",
         "**Bias warning:** 51 of the 59 swimming-pool labels sit in one 1.7 km stretch of the Lake Norman waterfront "
         "(see `scripts/label_qa.py`), so these scores mostly describe lakefront estates, not the whole county.", "",
         "**How to read:** a hit counts as correct if its matched 16.8 m cell contains a hand-labelled true match *or* touches an "
         "OSM-mapped object of the concept. Unlabelled, unmapped real matches count as misses, so all precision numbers are "
         "**lower bounds**. `labels only` ignores OSM. find_all is leave-one-out from each true-match label, searched in a "
         "~1.6 × 1.5 km box around it. Look-alike rejection = share of nearby look-alike labels that do *not* appear in the "
         "top k.", "",
         "| concept | labels T/L (in index) | search_text P@k (labels+OSM / labels) | find_all P@k (labels+OSM / labels) | look-alike rejection | intended meaning in 6 picks | OSM recall top 200 (cluster box) | outline IoU vs OSM (median, n) |",
         "|---|---|---|---|---|---|---|---|"]
    for c, r in o["results"].items():
        lab = r["labels"]
        if "search_text" not in r:
            L.append(f"| {c} | {lab['true_match']}/{lab['look_alike']} | – | – | – | – | – | – |")
            continue
        st, fa = r["search_text"], r.get("find_all_loo", {})
        rec = r.get("osm_recall_top200_in_cluster_box", {})
        L.append(f"| {c} | {lab['true_match']}/{lab['look_alike']} ({lab['true_in_index']}/{lab['lookalike_in_index']}) | "
                 f"{st['P@k_labels_or_osm']} / {st['P@k_labels_only']} | "
                 f"{fa.get('P@k_labels_or_osm', '–')} / {fa.get('P@k_labels_only', '–')} | {fa.get('lookalike_rejection', '–')} "
                 f"({fa.get('lookalikes_nearby', 0)} nearby) | {'yes' if r['pick_candidates']['intended_in_6'] else 'no'} | "
                 f"{rec.get('found', '–')}/{rec.get('osm_objects', '–')} ({rec.get('recall', '–')}) | "
                 f"{fa.get('outline_iou_vs_osm_median', '–')} ({fa.get('outline_iou_n', 0)}) |")
    L += ["", "Reproduce: `bash scripts/gtg.sh python scripts/evaluate.py --aoi county` (raw numbers in `data/out/evaluation.json`)."]
    (ROOT / "docs" / "EVALUATION.md").write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
