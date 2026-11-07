"""Engine tools. Each returns an Envelope (docs/CONTRACT.md).

    eng = Engine(PublicDataProvider(), aoi="unc_charlotte")
    eng.search_text("swimming pool", k=24)

Examples ("ids") are ``chip_id`` or ``chip_id#cell`` (cell 0–15, row-major from the chip's NW corner). Without an
explicit cell, the chip's most salient cell (least like a typical patch) is used.
"""

from __future__ import annotations

import csv
import io
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np
from shapely.geometry import box, mapping, shape

from groundtruth import config
from groundtruth.envelope import Envelope, Result, StepTimer, declined, feature_collection
from groundtruth.geo import SQM_PER_ACRE, length_m, to_measure
from groundtruth.index import ChipIndex, view_cells
from groundtruth.providers.base import DataProvider

VERSION = "0.2.0"
PEOPLE_TERMS = ("owner", "who lives", "resident", "income", "race", "ethnicity", "crime", "school rating",
                "demographic", "home address of")
NOT_IMPLEMENTED = "not_implemented"


def _people(query: str) -> bool:
    q = query.lower()
    return any(t in q for t in PEOPLE_TERMS)


def load_senses() -> dict[str, Any]:
    return {k: v for k, v in json.loads(config.SENSES_PATH.read_text()).items() if not k.startswith("_")}


def senses_for(query: str) -> tuple[str | None, list[dict[str, Any]]]:
    q = " ".join(query.lower().strip().split())
    for key, entry in load_senses().items():
        if q == key or q in entry["aliases"]:
            return key, entry["senses"]
    return None, []


def parse_example(s: str) -> tuple[str, int | None]:
    if "#" in s:
        cid, c = s.split("#", 1)
        return cid, int(c)
    return s, None


def _iou(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    if inter == 0:
        return 0.0
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua


@dataclass
class Session:
    id: str
    accept: list[str] = field(default_factory=list)
    reject: list[str] = field(default_factory=list)
    query: str = ""
    created: float = field(default_factory=time.time)
    pool: list[int] = field(default_factory=list)
    pool_key: Any = None


class Engine:
    def __init__(self, provider: DataProvider, *, aoi: str = "county", year: int | None = None,
                 index: ChipIndex | None = None) -> None:
        self.provider = provider
        self.year = year or provider.imagery_years()[0]
        self.aoi = aoi
        self.index = index or ChipIndex(config.precompute_dir(self.year, aoi))
        self._clip = None
        self._outliner = None
        self.sessions: dict[str, Session] = {}

    # ------------------------------------------------------------------ shared
    def _clip_model(self):
        if self._clip is None:
            from groundtruth.embed import get_clip

            self._clip = get_clip()
        return self._clip

    def _sources(self):
        return [s for s in self.provider.sources() if str(self.year) in s.name]

    def _limits(self) -> list[str]:
        out = [f"NAIP {self.year} at 0.6 m/px: objects smaller than ~3 m are not resolvable",
               "Scores are embedding similarities, not calibrated probabilities",
               "Hits are 33.6 m sub-cells of 134 m chips, not object outlines (use `outline`)"]
        if self.aoi != "county":
            out.append(f"Only the '{self.aoi}' area is indexed, not the whole county")
        return out

    def _status(self) -> str:
        return "ok" if self.aoi == "county" else "partial"

    def _env(self, tool: str, **kw: Any) -> Envelope:
        kw.setdefault("status", self._status())
        kw.setdefault("limits", self._limits())
        kw.setdefault("sources", self._sources())
        return Envelope(tool=tool, version=VERSION, **kw)

    def _example_cells(self, examples: Sequence[str]) -> list[tuple[int, int]]:
        out = []
        for ex in examples:
            cid, cell = parse_example(ex)
            if cid not in self.index.pos:
                continue
            i = self.index.pos[cid]
            out.append((i, cell if cell is not None else self.index.salient_cell(i)))
        return out

    def localise(self, i: int, qvec: np.ndarray) -> tuple[int, float]:
        """Which cell of the chip best matches a text vector (OpenCLIP on crops of the stored thumbnail).
        Two stages, 20 CLIP passes per chip: (1) 16 windows of 84 px centred on each 2×2 block of cells → best block;
        (2) its 4 cells, each with a 42 px context crop → best cell. Query-time only (pick_candidates' 6 tiles)."""
        from PIL import Image

        img = Image.open(io.BytesIO(self.index.thumb_jpeg(i))).convert("RGB")
        g, cp = self.index.grid, config.CHIP_PX // self.index.grid

        def crop(cx: float, cy: float, size: int) -> np.ndarray:
            x0 = int(min(max(cx - size / 2, 0), config.CHIP_PX - size))
            y0 = int(min(max(cy - size / 2, 0), config.CHIP_PX - size))
            return np.asarray(img.crop((x0, y0, x0 + size, y0 + size)).resize((224, 224), Image.BILINEAR))

        clip = self._clip_model()
        h = g // 2  # 2×2 blocks of cells
        blocks = [(br, bc) for br in range(h) for bc in range(h)]
        s1 = clip.embed_images(np.stack([crop((bc * 2 + 1) * cp, (br * 2 + 1) * cp, 3 * cp) for br, bc in blocks]),
                               batch=16) @ qvec
        br, bc = blocks[int(np.argmax(s1))]
        cells = [(br * 2 + dr) * g + (bc * 2 + dc) for dr in (0, 1) for dc in (0, 1)]
        s2 = clip.embed_images(np.stack([crop((c % g) * cp + cp / 2, (c // g) * cp + cp / 2, int(1.5 * cp)) for c in cells]),
                               batch=4) @ qvec
        k = int(np.argmax(s2))
        return cells[k], float(s2[k])

    def _clip_rank(self, qvec: np.ndarray, k_chips: int) -> list[tuple[int, float, int]]:
        """(chip, score, best_view) by max over CLIP views."""
        V = self.index.n_views
        D, I = self.index.search_rows("clip", qvec, k_chips * V * 3)
        best: dict[int, tuple[float, int]] = {}
        for d, r in zip(D, I):
            if r < 0:
                continue
            i, v = divmod(int(r), V)
            if i not in best or d > best[i][0]:
                best[i] = (float(d), v)
        ranked = sorted(best.items(), key=lambda t: (-round(t[1][0], 6), self.index.ids[t[0]]))
        return [(i, s, v) for i, (s, v) in ranked[:k_chips]]

    def _nms(self, hits: list[tuple[int, float, int]], k: int, iou: float = 0.3,
             block: Sequence[tuple[int, int]] = ()) -> list[tuple[int, float, int]]:
        """Drop hits whose cell overlaps an earlier hit's cell (same object seen in overlapping chips)."""
        kept: list[tuple[int, float, int]] = []
        boxes = [self.index.cell_bounds_m(i, c) for i, c in block]
        for i, s, c in hits:
            b = self.index.cell_bounds_m(i, c)
            if any(_iou(b, o) > iou for o in boxes):
                continue
            kept.append((i, s, c)); boxes.append(b)
            if len(kept) >= k:
                break
        return kept

    # ------------------------------------------------------------------ search_text
    def search_text(self, query: str, k: int = 50) -> Envelope:
        tool = "search_text"
        if not query.strip():
            return declined(tool, VERSION, "empty query")
        if _people(query):
            return declined(tool, VERSION, "Groundtruth does not search for information about people")
        t = StepTimer()
        with t.step("embed_query", "OpenCLIP text, 4-prompt ensemble"):
            q = self._clip_model().embed_query(query)
        with t.step("search", f"max over {self.index.n_views} CLIP views × {len(self.index)} chips"):
            ranked = self._clip_rank(q, k * 3)
        with t.step("localise+dedupe", "salient DINOv2 cell in best view; cell NMS"):
            hits = [(i, s, self.index.salient_cell(i, view_cells(v, self.index.grid))) for i, s, v in ranked]
            views = {i: v for i, _, v in ranked}
            hits = self._nms(hits, k)
        feats = [self.index.feature(i, cell=c, score=round(s, 4), rank=r + 1, view=views[i])
                 for r, (i, s, c) in enumerate(hits)]
        return self._env(tool, result=Result(geojson=feature_collection(feats), metrics={
            "count": len(feats), "indexed_chips": len(self.index),
            "score_max": feats[0]["properties"]["score"] if feats else None}),
            method=f"OpenCLIP ViT-B-16 (laion2b_s34b_b88k) text→image cosine, max over whole chip + 2×2 quadrant "
                   f"crops, NAIP {self.year}; hit cell = most salient DINOv2 cell in the best view",
            assumptions=[f"NAIP {self.year} imagery reflects the ground today"], steps=t.steps)

    # ------------------------------------------------------------------ pick_candidates
    def pick_candidates(self, query: str, n: int = 6, pool: int = 200, per_sense: int = 40,
                        max_sim: float = 0.80) -> Envelope:
        """One representative per *meaning*: the query is expanded into sense prompts (conf/senses.json); each
        candidate chip is assigned to the sense it matches best; per sense the best chip whose DINOv2 cell is
        not too similar (cos < max_sim) to already-chosen tiles becomes the option (MMR-style)."""
        tool = "pick_candidates"
        if not query.strip():
            return declined(tool, VERSION, "empty query")
        if _people(query):
            return declined(tool, VERSION, "Groundtruth does not search for information about people")
        t = StepTimer()
        key, senses = senses_for(query)
        clip = self._clip_model()
        with t.step("embed_query", f"raw query + {len(senses)} sense prompts ({key or 'no sense list'})"):
            qraw = clip.embed_query(query)
            prompted = [s for s in senses if s.get("prompt")]
            Q = np.stack([clip.embed_query(s["prompt"]) for s in prompted]) if prompted else np.zeros((0, 512))
        with t.step("candidate_pool", f"top {pool} raw + top {per_sense} per sense"):
            cand: set[int] = {i for i, _, _ in self._clip_rank(qraw, pool)}
            for qs in Q:
                cand |= {i for i, _, _ in self._clip_rank(qs, per_sense)}
            idx = np.array(sorted(cand))
            CV = self.index.clip_views(idx)  # (n, V, 512)
            raw = (CV @ qraw).max(1)
            S = np.einsum("nvd,sd->nsv", CV, Q) if len(Q) else np.zeros((len(idx), 0, CV.shape[1]))
            Smax, Sview = S.max(2) if len(Q) else S[:, :, 0], S.argmax(2) if len(Q) else None
            assigned = Smax.argmax(1) if len(Q) else None
        chosen: list[dict[str, Any]] = []
        chosen_vecs: list[np.ndarray] = []

        def rep_cell(j: int, view: int) -> int:
            return self.index.salient_cell(int(idx[j]), view_cells(int(view), self.index.grid))

        def try_pick(order: Sequence[int], view_of, sense: dict[str, Any], score_of) -> bool:
            for j in order:
                i = int(idx[j])
                if any(c["i"] == i for c in chosen):
                    continue
                cell = rep_cell(j, view_of(j))
                v = self.index.cells(i)[cell]
                if chosen_vecs and max(float(v @ w) for w in chosen_vecs) >= max_sim:
                    continue
                chosen.append({"i": i, "cell": cell, "sense": sense, "score": float(score_of(j)), "j": j})
                chosen_vecs.append(v)
                return True
            return False

        with t.step("pick", f"one per sense, DINOv2 cell diversity cos<{max_sim}"):
            for s_i, sense in enumerate(prompted):
                mine = np.where(assigned == s_i)[0]
                order = mine[np.argsort(-Smax[mine, s_i])].tolist()
                order += [j for j in np.argsort(-Smax[:, s_i]).tolist() if j not in set(mine.tolist())]
                try_pick(order, lambda j, s_i=s_i: Sview[j, s_i], sense, lambda j, s_i=s_i: Smax[j, s_i])
                if len(chosen) >= n:
                    break
            unknowns = [s for s in senses if not s.get("prompt")] or [{"id": "other", "label": "Something else"}]
            k_i = 0
            raw_view = (CV @ qraw).argmax(1)
            while len(chosen) < n:
                if not try_pick(np.argsort(-raw).tolist(), lambda j: raw_view[j], unknowns[min(k_i, len(unknowns) - 1)],
                                lambda j: raw[j]):
                    break
                k_i += 1
        with t.step("localise", f"OpenCLIP on 16 context crops × {len(chosen)} tiles (sense-specific)"):
            for c in chosen:
                s_i = next((k for k, s in enumerate(prompted) if s is c["sense"]), None)
                c["cell"], c["cell_score"] = self.localise(c["i"], Q[s_i] if s_i is not None else qraw)
        feats = []
        for rank, c in enumerate(chosen, 1):
            j = c["j"]
            s_i = next((k for k, s in enumerate(prompted) if s is c["sense"]), None)
            if s_i is not None:
                mine = np.where(assigned == s_i)[0]
                members = idx[mine[np.argsort(-Smax[mine, s_i])]][:12]
            else:
                members = idx[np.argsort(-raw)][:12]
            feats.append(self.index.feature(c["i"], cell=c["cell"], score=round(c["score"], 4), rank=rank,
                                            raw_score=round(float(raw[j]), 4), sense_id=c["sense"]["id"],
                                            sense_label=c["sense"]["label"], example=f"{self.index.ids[c['i']]}#{c['cell']}",
                                            group_members=[self.index.ids[int(m)] for m in members]))
        return self._env(tool, result=Result(geojson=feature_collection(feats), metrics={
            "count": len(feats), "pool": int(len(idx)), "sense_list": key,
            "senses": [f["properties"]["sense_id"] for f in feats]}),
            method="OpenCLIP sense prompts (conf/senses.json) → each chip assigned to its best sense → one tile per "
                   f"sense, DINOv2 4×4-cell MMR diversity (cos<{max_sim}); object cell localised by OpenCLIP on "
                   "16 per-cell context crops",
            assumptions=["The configured senses cover the plausible meanings of the query"], steps=t.steps)

    # ------------------------------------------------------------------ find_similar
    def _cell_query(self, pos: list[tuple[int, int]], neg: list[tuple[int, int]], neg_weight: float) -> np.ndarray:
        q = np.mean([self.index.cells(i)[c] for i, c in pos], axis=0)
        if neg:
            q = q - neg_weight * np.mean([self.index.cells(i)[c] for i, c in neg], axis=0)
        return q / max(np.linalg.norm(q), 1e-12)

    def _cell_rank(self, q: np.ndarray, k_chips: int, skip: set[int]) -> list[tuple[int, float, int]]:
        C = self.index.n_cells
        D, I = self.index.search_rows("dino", q, (k_chips + len(skip)) * C * 2)
        best: dict[int, tuple[float, int]] = {}
        for d, r in zip(D, I):
            if r < 0:
                continue
            i, c = divmod(int(r), C)
            if i in skip:
                continue
            if i not in best or d > best[i][0]:
                best[i] = (float(d), c)
        ranked = sorted(best.items(), key=lambda t: (-round(t[1][0], 6), self.index.ids[t[0]]))
        return [(i, s, c) for i, (s, c) in ranked]

    def _bbox_rows(self, bbox: Sequence[float] | None) -> np.ndarray | None:
        if not bbox:
            return None
        w, s, e, n = bbox
        m = self.index.meta
        return np.where((m["east"] >= w) & (m["west"] <= e) & (m["north"] >= s) & (m["south"] <= n))[0]

    def _cell_rank_subset(self, q: np.ndarray, rows: np.ndarray, skip: set[int]) -> list[tuple[int, float, int]]:
        """Exact best-cell scores over a subset of chips (bbox search): numpy over the memory-mapped cells."""
        out = []
        for k in range(0, len(rows), 4096):
            r = rows[k:k + 4096]
            S = np.asarray(self.index.dino[r], dtype=np.float32) @ q  # (n, cells)
            best = S.argmax(1)
            out += [(int(i), float(S[j, best[j]]), int(best[j])) for j, i in enumerate(r) if int(i) not in skip]
        out.sort(key=lambda t: (-round(t[1], 6), self.index.ids[t[0]]))
        return out

    def find_similar(self, chip_ids: Sequence[str], exclude_ids: Sequence[str] = (), k: int = 50,
                     neg_weight: float = 0.5, bbox: Sequence[float] | None = None, rerank: bool = False,
                     concept: str | None = None) -> Envelope:
        tool = "find_similar"
        pos = self._example_cells(chip_ids)
        if not pos:
            return declined(tool, VERSION, "none of the example ids are in the index")
        neg = self._example_cells(exclude_ids)
        t = StepTimer()
        with t.step("query_vector", f"{len(pos)} positive cells, {len(neg)} negative cells, λ={neg_weight}"):
            q = self._cell_query(pos, neg, neg_weight)
        skip = {i for i, _ in pos} | {i for i, _ in neg}
        rows = self._bbox_rows(bbox)
        pool = 400
        if rerank:
            from groundtruth.rerank import concept_conf

            pool = int(concept_conf(concept)["rerank"].get("pool", 400))
        with t.step("search", f"best-matching 16.8 m cell over {len(self.index) if rows is None else len(rows)} chips"
                    + (f" in bbox" if rows is not None else "")):
            ranked = (self._cell_rank_subset(q, rows, skip) if rows is not None
                      else self._cell_rank(q, max(k * 3, pool if rerank else 0), skip))
        parts: dict[int, dict] = {}
        info: dict[str, Any] = {}
        if rerank and ranked:
            from groundtruth.rerank import rerank as do_rerank

            with t.step("rerank", f"full-res DINOv2 patches + colour ({concept or 'no concept'}) on top {pool}") as st:
                rr, info = do_rerank(self.index, pos, neg, [i for i, _, _ in ranked[:pool]], concept=concept,
                                     neg_weight=neg_weight)
                st.detail += f" · {info['device']}"
            ranked = [(i, s, c) for i, s, c, _ in rr]
            parts = {i: p for i, _, _, p in rr}
        with t.step("dedupe", "cell NMS (same object in overlapping chips)"):
            hits = self._nms(ranked, k, block=pos + neg)
        feats = [self.index.feature(i, cell=c, score=round(s, 4), rank=r + 1, **({"rerank": parts[i]} if i in parts else {}))
                 for r, (i, s, c) in enumerate(hits)]
        method = ("DINOv2 ViT-B/14 8×8-cell (16.8 m, PCA-192) cosine, best cell per chip; query = mean(positive cells) − "
                  f"{neg_weight}·mean(negative cells)")
        if rerank:
            method += (f"; top {pool} re-ranked by full-res DINOv2 patches (8.4 m) "
                       f"×{info.get('patch_weight')} + concept colour ×{info.get('colour_weight')}")
        return self._env(tool, result=Result(geojson=feature_collection(feats), metrics={
            "count": len(feats), "positives": len(pos), "negatives": len(neg), "reranked": bool(rerank and ranked),
            "bbox": list(bbox) if bbox else None}),
            method=method, assumptions=["The example cells show the intended object"], steps=t.steps)

    # ------------------------------------------------------------------ find_all (core product)
    def _outline_worker(self):
        if getattr(self, "_worker", None) is None:
            import queue
            import threading

            from groundtruth.outline import Outliner

            if self._outliner is None:
                self._outliner = Outliner()
            self._queue: "queue.Queue[tuple[int, int]]" = queue.Queue()
            self._outline_lock = threading.Lock()

            def run() -> None:
                while True:
                    i, c = self._queue.get()
                    try:
                        self._outliner.outline(self.index, i, c)  # thread-safe, cached
                    except Exception:
                        pass

            self._worker = threading.Thread(target=run, daemon=True, name="outline-worker")
            self._worker.start()
        return self._queue

    def _cached_outline(self, i: int, c: int) -> dict[str, Any] | None:
        from groundtruth.outline import Outliner

        p = Outliner._cache_path(self.index.ids[i], c)
        return json.loads(p.read_text()) if p.exists() else None

    def place_bbox(self, place: str | None) -> list[float] | None:
        if not place:
            return None
        places = json.loads((config.SENSES_PATH.parent / "places.json").read_text())["places"]
        key = next((k for k in places if k.lower() == place.strip().lower()), None)
        return places[key]["bbox"] if key else None

    def find_all(self, examples: Sequence[str], exclude: Sequence[str] = (), k: int = 200,
                 bbox: Sequence[float] | None = None, place: str | None = None, concept: str | None = None,
                 rerank: bool = True, outline_top: int = 200) -> Envelope:
        """pick → ranked matches (county or bbox/place) → object dedupe → outlines (cached ones now, the top
        ``outline_top`` queued in the background, lazily cached by chip#cell) → count / acres / median area."""
        tool = "find_all"
        from groundtruth.rerank import concept_conf
        from shapely.geometry import box as sbox

        if place and not bbox:
            bbox = self.place_bbox(place)
            if bbox is None:
                return declined(tool, VERSION, f"unknown place {place!r} (see GET /api/v1/places)")
        base = self.find_similar(examples, exclude, k=k, bbox=bbox, rerank=rerank, concept=concept)
        if base.status == "declined":
            return base.model_copy(update={"tool": tool})
        t = StepTimer()
        t.steps.extend(base.steps)
        feats = base.result.geojson["features"]
        conf_cut = float(concept_conf(concept).get("count_conf", 0.5))
        with t.step("outlines", f"attach cached; queue top {min(outline_top, len(feats))} for SAM 2"):
            q = self._outline_worker() if outline_top else None
            scores = [f["properties"]["score"] for f in feats] or [0]
            s_hi, s_lo = max(scores), min(scores)
            out, polys = [], []
            n_queued = 0
            for r, f in enumerate(feats):
                p = f["properties"]
                i, c = self.index.pos[p["chip_id"]], p["cell"]
                ol = self._cached_outline(i, c)
                rel = (p["score"] - s_lo) / max(s_hi - s_lo, 1e-6)
                quality = (0.5 + 0.5 * ol["properties"]["sam_score"]) if ol and ol.get("geometry") else 0.85
                conf = round(float(np.clip(rel * quality, 0, 1)), 3)
                geom = ol["geometry"] if ol and ol.get("geometry") else mapping(sbox(*p["cell_bbox"]))
                props = {**p, "example": f"{p['chip_id']}#{c}", "confidence": conf,
                         "geometry_kind": "outline" if ol and ol.get("geometry") else "cell",
                         "area_m2": ol["properties"]["area_m2"] if ol and ol.get("geometry") else None,
                         "area_acres": ol["properties"]["area_acres"] if ol and ol.get("geometry") else None}
                if q is not None and not ol and r < outline_top:
                    q.put((i, c)); n_queued += 1
                # object dedupe across chip borders: drop if it overlaps an earlier result's outline/cell by >50%
                g = shape(geom)
                gm = to_measure(g)
                if any(gm.intersection(o).area > 0.5 * min(gm.area, o.area) for o in polys):
                    continue
                polys.append(gm)
                out.append({"type": "Feature", "id": props["example"], "geometry": geom, "properties": props})
        detected = [f for f in out if f["properties"]["confidence"] >= conf_cut]
        areas = [f["properties"]["area_m2"] for f in detected if f["properties"]["area_m2"]]
        tot = float(sum(areas))
        metrics = {"count_detected": len(detected), "count_returned": len(out), "confidence_cut": conf_cut,
                   "outlined": sum(1 for f in out if f["properties"]["geometry_kind"] == "outline"),
                   "outlines_queued": n_queued, "area_m2_total": round(tot, 1),
                   "area_acres_total": round(tot / SQM_PER_ACRE, 3),
                   "median_area_m2": round(float(np.median(areas)), 1) if areas else None,
                   "bbox": list(bbox) if bbox else None, "place": place, "concept": concept}
        limits = self._limits() + [
            "count = detected objects in the ranked results (top k, confidence ≥ cut), not a census",
            f"Only the top {k} matches are considered; areas are summed over outlined detections only",
            "Confidence is a heuristic (relative similarity × outline quality), not a calibrated probability"]
        return self._env(tool, result=Result(geojson=feature_collection(out), metrics=metrics),
                         confidence=None, method=base.method + "; object dedupe by outline/cell overlap > 50%; SAM 2.1 "
                         "outlines prompted by the matching cell (lazy, cached)",
                         assumptions=base.assumptions, limits=limits, steps=t.steps)

    # ------------------------------------------------------------------ refine
    def refine(self, session_id: str | None, accept_ids: Sequence[str] = (), reject_ids: Sequence[str] = (),
               k: int = 50, pool: int = 1500, bbox: Sequence[float] | None = None, place: str | None = None,
               concept: str | None = None) -> Envelope:
        """Per-session logistic regression on DINOv2 cell vectors (accepted vs rejected + background cells),
        applied to every cell of a candidate pool (re-ranked find_similar from the accepted examples, within the
        place/bbox if given). Each hit says why: its nearest accepted example. Target < 1 s (pool cached per session)."""
        from sklearn.linear_model import LogisticRegression

        tool = "refine"
        sid = session_id or uuid.uuid4().hex[:12]
        sess = self.sessions.setdefault(sid, Session(sid))
        sess.accept += [a for a in accept_ids if a not in sess.accept]
        sess.reject = [r for r in sess.reject if r not in accept_ids]
        sess.accept = [a for a in sess.accept if a not in reject_ids]
        sess.reject += [r for r in reject_ids if r not in sess.reject]
        pos = self._example_cells(sess.accept)
        neg = self._example_cells(sess.reject)
        if not pos:
            return declined(tool, VERSION, "refine needs at least one accepted example")
        if place and not bbox:
            bbox = self.place_bbox(place)
        t = StepTimer()
        skip = {i for i, _ in pos} | {i for i, _ in neg}
        key = (tuple(bbox) if bbox else None, concept)
        with t.step("pool", "candidate chips (cached per session)" if getattr(sess, "pool_key", None) == key
                    else f"cell search from the first accepted example → {pool} chips"):
            if getattr(sess, "pool_key", None) != key or not getattr(sess, "pool", None):
                q = self._cell_query(pos[:1], [], 0.5)
                rows = self._bbox_rows(bbox)
                ranked = (self._cell_rank_subset(q, rows, set()) if rows is not None else self._cell_rank(q, pool, set()))
                sess.pool = [i for i, _, _ in ranked[:pool]]
                sess.pool_key = key
            cand = [i for i in sess.pool if i not in skip]
        with t.step("fit", f"logistic regression: {len(pos)} accepted, {len(neg)} rejected + background"):
            rng = np.random.default_rng(0)
            bg_i = rng.choice(len(self.index), size=min(150, len(self.index)), replace=False)
            bg = np.stack([self.index.cells(int(i))[int(rng.integers(self.index.n_cells))] for i in bg_i])
            Xp = np.stack([self.index.cells(i)[c] for i, c in pos])
            Xn = np.concatenate([np.stack([self.index.cells(i)[c] for i, c in neg])] if neg else [] + [bg])
            X = np.concatenate([Xp, Xn])
            y = np.r_[np.ones(len(Xp)), np.zeros(len(Xn))]
            clf = LogisticRegression(C=1.0, class_weight="balanced", max_iter=500).fit(X, y)
        with t.step("score", f"{len(cand)} chips × {self.index.n_cells} cells"):
            cells = np.asarray(self.index.dino[np.array(cand)], dtype=np.float32) if cand else np.zeros((0, 16, 768))
            P = clf.predict_proba(cells.reshape(-1, cells.shape[-1]))[:, 1].reshape(len(cand), -1) if cand else cells
            best_c = P.argmax(1) if cand else []
            ranked = sorted(((cand[j], float(P[j, best_c[j]]), int(best_c[j])) for j in range(len(cand))),
                            key=lambda h: (-round(h[1], 6), self.index.ids[h[0]]))
            hits = self._nms(ranked, k, block=pos + neg)
        with t.step("why", "nearest accepted example per hit"):
            A = np.stack([self.index.cells(i)[c] for i, c in pos])
            feats = []
            for r, (i, p, c) in enumerate(hits):
                sims = A @ self.index.cells(i)[c]
                j = int(np.argmax(sims))
                feats.append(self.index.feature(i, cell=c, score=round(p, 4), rank=r + 1, confidence=round(p, 3),
                                                why={"nearest_accepted": f"{self.index.ids[pos[j][0]]}#{pos[j][1]}",
                                                     "similarity": round(float(sims[j]), 3)}))
        total_ms = sum(s.ms for s in t.steps)
        return self._env(tool, result=Result(geojson=feature_collection(feats), metrics={
            "count": len(feats), "session_id": sid, "accepted": len(pos), "rejected": len(neg),
            "pool_chips": len(cand), "refine_ms": round(total_ms, 1)}),
            confidence=None,
            method="Logistic regression (sklearn, C=1, balanced) on DINOv2 4×4-cell vectors; positives = accepted "
                   "cells, negatives = rejected cells + 150 random background cells; scores = P(match) of best cell",
            assumptions=["Accepted/rejected examples are representative"], steps=t.steps)

    # ------------------------------------------------------------------ outline
    def outline(self, examples: Sequence[str], max: int = 12) -> Envelope:  # noqa: A002
        """SAM 2.1 polygons prompted by each hit's cell box (+1 cell margin). Lazy: only the ids given (the results
        on screen), at most ``max``; cached by chip#cell."""
        tool = "outline"
        cells = self._example_cells(examples)[:max]
        if not cells:
            return declined(tool, VERSION, "none of the example ids are in the index")
        if self._outliner is None:
            from groundtruth.outline import Outliner

            self._outliner = Outliner()
        t = StepTimer()
        feats = []
        with t.step("sam2", f"{len(cells)} outlines (SAM 2.1 hiera-tiny, {self._outliner.device_name})"):
            for i, c in cells:
                feats.append(self._outliner.outline(self.index, i, c))
        done = [f for f in feats if f.get("geometry")]
        fresh = [f["properties"]["ms"] for f in feats if not f["properties"].get("cached")]
        tot = sum(f["properties"]["area_m2"] for f in done)
        return self._env(tool, status="ok" if len(done) == len(feats) else "partial",
                         result=Result(geojson=feature_collection(feats), metrics={
                             "count": len(done), "empty": len(feats) - len(done),
                             "area_m2_total": round(tot, 2), "area_acres_total": round(tot / SQM_PER_ACRE, 4),
                             "ms_per_outline": round(float(np.mean(fresh)), 1) if fresh else None,
                             "cached": len(feats) - len(fresh)}),
                         method="SAM 2.1 hiera-tiny (Apache-2.0) box prompt = matched 16.8 m cell + 1 cell margin, on the "
                                "0.6 m chip; largest mask component overlapping the cell; simplified 0.3 m; areas in EPSG:32617",
                         assumptions=["The object of interest is inside the prompted box"],
                         limits=self._limits() + ["Outlines from 0.6 m imagery: edges ±1 px (0.6 m)"], steps=t.steps)

    # ------------------------------------------------------------------ measure
    def _layer_geom(self, name: str, where: dict[str, Any] | None = None, near: Sequence[dict[str, Any]] | None = None):
        """Union of a layer in EPSG:32617 (cached). With ``near`` (features), only layer parts within ~5 km of their
        extent are merged, which keeps big layers (FEMA) fast."""
        from shapely import make_valid
        from shapely.ops import unary_union

        cache = self.__dict__.setdefault("_layer_cache", {})
        clip = None
        if near:
            xs = [shape(f["geometry"]).bounds for f in near]
            clip = box(min(b[0] for b in xs) - 0.05, min(b[1] for b in xs) - 0.05,
                       max(b[2] for b in xs) + 0.05, max(b[3] for b in xs) + 0.05)
        key = (name, json.dumps(where or {}, sort_keys=True), tuple(round(v, 2) for v in clip.bounds) if clip else None)
        if key not in cache:
            fc = self.provider.get_layer(name, tuple(clip.bounds) if clip else None)
            gs = [make_valid(shape(f["geometry"])) for f in fc["features"] if f.get("geometry") and
                  all(f["properties"].get(k) == v for k, v in (where or {}).items())]
            cache[key] = to_measure(unary_union(gs).buffer(0) if any(g.area for g in gs) else unary_union(gs)) if gs else None
        return cache[key]

    def measure(self, geojson: dict[str, Any], *, to_layer: str | None = None,
                to_layers: Sequence[str] = ()) -> Envelope:
        """Per feature: area_m2, area_acres, perimeter_m, dist_m_to_<layer>. Totals: count, area_acres_total,
        median_area_m2, min/median dist per layer. Measured in EPSG:32617; geometry I/O in EPSG:4326."""
        tool = "measure"
        feats = geojson.get("features", [])
        if not feats:
            return declined(tool, VERSION, "no features to measure")
        layers = [l for l in ([to_layer] if to_layer else []) + list(to_layers) if l]
        t = StepTimer()
        geoms = {}
        for l in layers:
            with t.step("load_layer", l):
                geoms[l] = self._layer_geom(l, near=feats)
        out, areas = [], []
        dists: dict[str, list[float]] = {l: [] for l in layers}
        with t.step("measure", f"{len(feats)} features in EPSG:32617"):
            for f in feats:
                g = shape(f["geometry"])
                gm = to_measure(g)
                p = dict(f.get("properties") or {})
                p["area_m2"] = round(gm.area, 2)
                p["area_acres"] = round(gm.area / SQM_PER_ACRE, 5)
                p["perimeter_m"] = round(gm.length if gm.geom_type in ("Polygon", "MultiPolygon") else length_m(g), 2)
                for l, lg in geoms.items():
                    if lg is not None:
                        d = round(gm.distance(lg), 1)
                        p[f"dist_m_to_{l}"] = d
                        dists[l].append(d)
                areas.append(gm.area)
                out.append({"type": "Feature", "id": f.get("id"), "geometry": f["geometry"], "properties": p})
        tot = float(sum(areas))
        metrics = {"count": len(out), "area_m2_total": round(tot, 2), "area_acres_total": round(tot / SQM_PER_ACRE, 4),
                   "median_area_m2": round(float(np.median(areas)), 2)}
        for l, ds in dists.items():
            if ds:
                metrics[f"min_dist_m_to_{l}"] = min(ds)
                metrics[f"median_dist_m_to_{l}"] = round(float(np.median(ds)), 1)
        return self._env(tool, status="ok", result=Result(geojson=feature_collection(out), metrics=metrics),
                         confidence=1.0, method="Planar measurement after reprojection EPSG:4326 → EPSG:32617 (UTM 17N)",
                         assumptions=["Input geometry is EPSG:4326"],
                         limits=["UTM 17N distortion < 0.1% in Mecklenburg",
                                 "Distances are to the simplified web build of a layer when one exists (~3 m)"],
                         sources=[s for l in layers for s in (self.provider.source_for(
                             {"osm": "openstreetmap"}.get(l.split("_")[0], l.split("_")[0])))], steps=t.steps)

    # ------------------------------------------------------------------ layers
    def add_layer(self, name: str, bbox: Sequence[float] | None = None) -> Envelope:
        tool = "add_layer"
        try:
            t = StepTimer()
            with t.step("load", name):
                fc = self.provider.get_layer(name, tuple(bbox) if bbox else None)
        except KeyError as e:
            return declined(tool, VERSION, str(e))
        return self._env(tool, status="ok", result=Result(geojson=fc, metrics={"count": len(fc["features"])}),
                         confidence=1.0, method=f"reference layer '{name}' from {self.provider.name} provider",
                         limits=[], sources=self.provider.source_for(
                             {"osm": "openstreetmap"}.get(name.split("_")[0], name.split("_")[0])) or self.provider.sources(),
                         steps=t.steps)

    def filter(self, geojson: dict[str, Any], where: dict[str, Any]) -> Envelope:
        """``where`` keys (all optional, ANDed):
        ``within_m_of``: {layer, m} or a list of them (e.g. {"layer": "osm_i485", "m": 1000});
        ``inside_place``: a name from GET /places (e.g. "Ballantyne");
        ``intersects_layer`` (+ ``layer_where`` {prop: value}), ``not_intersects_layer``;
        ``min_area_acres`` / ``max_area_acres`` (uses the feature's area_acres when present, else its geometry);
        ``min_confidence``, ``min_score``. Legacy: ``dist_layer`` + ``max_dist_m``."""
        tool = "filter"
        t = StepTimer()
        feats = geojson.get("features", [])
        within = where.get("within_m_of") or []
        within = [within] if isinstance(within, dict) else list(within)
        if where.get("dist_layer"):
            within.append({"layer": where["dist_layer"], "m": float(where.get("max_dist_m", 0))})
        with t.step("prepare", json.dumps(where)[:160]):
            try:
                inter = (self._layer_geom(where["intersects_layer"], where.get("layer_where"), near=feats)
                         if where.get("intersects_layer") and feats else None)
                notinter = self._layer_geom(where["not_intersects_layer"], near=feats) if where.get("not_intersects_layer") and feats else None
                wgeoms = [(w["layer"], float(w["m"]), self._layer_geom(w["layer"], near=feats)) for w in within] if feats else []
            except KeyError as e:
                return declined(tool, VERSION, str(e))
            place_g = None
            if where.get("inside_place"):
                bb = self.place_bbox(where["inside_place"])
                if bb is None:
                    return declined(tool, VERSION, f"unknown place {where['inside_place']!r}")
                place_g = to_measure(box(*bb))
        keep = []
        with t.step("filter", f"{len(feats)} features"):
            for f in feats:
                gm = to_measure(shape(f["geometry"]))
                p = f.get("properties") or {}
                a = p.get("area_acres") if p.get("area_acres") is not None else gm.area / SQM_PER_ACRE
                if inter is not None and not gm.intersects(inter):
                    continue
                if notinter is not None and gm.intersects(notinter):
                    continue
                if any(lg is None or gm.distance(lg) > m for _, m, lg in wgeoms):
                    continue
                if place_g is not None and not gm.intersects(place_g):
                    continue
                if "min_area_acres" in where and a < where["min_area_acres"]:
                    continue
                if "max_area_acres" in where and a > where["max_area_acres"]:
                    continue
                if "min_score" in where and float(p.get("score", 0)) < where["min_score"]:
                    continue
                if "min_confidence" in where and float(p.get("confidence", 0)) < where["min_confidence"]:
                    continue
                keep.append(f)
        return self._env(tool, status="ok", result=Result(geojson=feature_collection(keep), metrics={
            "count_in": len(feats), "count_out": len(keep)}), confidence=1.0,
            method="Spatial/attribute predicates evaluated in EPSG:32617 (distances to layer unions)",
            limits=["Distances are to the simplified web build of a layer when one exists (~3 m)"], sources=[],
            steps=t.steps)

    def export(self, geojson: dict[str, Any], fmt: str = "geojson", title: str | None = None,
               summary: dict[str, Any] | None = None) -> Envelope:
        tool = "export"
        feats = geojson.get("features", [])
        t = StepTimer()
        with t.step("serialise", fmt):
            if fmt == "geojson":
                content = json.dumps(feature_collection(feats))
            elif fmt == "csv":
                buf = io.StringIO()
                keys = sorted({k for f in feats for k in (f.get("properties") or {}) if not isinstance(f["properties"][k], (list, dict))})
                w = csv.writer(buf, lineterminator="\n")
                w.writerow(["id", "lon", "lat", *keys])
                for f in feats:
                    c = shape(f["geometry"]).representative_point()
                    w.writerow([f.get("id"), round(c.x, 7), round(c.y, 7), *[f["properties"].get(k) for k in keys]])
                content = buf.getvalue()
            elif fmt == "pdf":
                content = None
            else:
                return declined(tool, VERSION, f"unsupported format {fmt!r} (geojson, csv, pdf)")
            out = config.DATA / "out" / "exports"
            out.mkdir(parents=True, exist_ok=True)
            name = f"export_{time.strftime('%Y%m%dT%H%M%S')}_{len(feats)}.{fmt}"
            if fmt == "pdf":
                nbytes = self._pdf(out / name, feats, title or "Groundtruth results", summary or {})
            else:
                (out / name).write_text(content)
                nbytes = len(content)
        return self._env(tool, status="ok", result=Result(metrics={
            "count": len(feats), "format": fmt, "file": f"data/out/exports/{name}", "download": f"/api/v1/exports/{name}",
            "bytes": nbytes, "content": content if content is not None and len(content) < 2_000_000 else None}),
            confidence=1.0, method=f"serialised {len(feats)} features as {fmt}", limits=[], sources=[], steps=t.steps)

    def _pdf(self, path, feats: list[dict[str, Any]], title: str, summary: dict[str, Any]) -> int:
        """One-page PDF (reportlab, BSD): title, summary metrics, top results with thumbnails, sources + limits."""
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.units import inch
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas

        c = canvas.Canvas(str(path), pagesize=letter)
        W, H = letter
        c.setFont("Helvetica-Bold", 16); c.drawString(0.6 * inch, H - 0.8 * inch, title[:80])
        c.setFont("Helvetica", 9); c.setFillGray(0.35)
        c.drawString(0.6 * inch, H - 1.0 * inch, f"Groundtruth · Mecklenburg County, NC · NAIP {self.year} · "
                     f"generated {time.strftime('%Y-%m-%d %H:%M')}")
        c.setFillGray(0); c.setFont("Helvetica", 10)
        y = H - 1.35 * inch
        for k, v in list(summary.items())[:8]:
            c.drawString(0.6 * inch, y, f"{k}: {v}"); y -= 13
        y -= 6
        tile = 1.05 * inch
        for n, f in enumerate(feats[:24]):
            p = f.get("properties") or {}
            cid = p.get("chip_id")
            if cid in self.index.pos:
                x0 = 0.6 * inch + (n % 6) * (tile + 0.12 * inch)
                y0 = y - tile - (n // 6) * (tile + 0.32 * inch)
                c.drawImage(ImageReader(io.BytesIO(self.index.thumb_jpeg(self.index.pos[cid]))), x0, y0, tile, tile)
                c.setFont("Helvetica", 6.5)
                a = p.get("area_m2")
                c.drawString(x0, y0 - 8, f"#{n + 1} conf {p.get('confidence', p.get('score', ''))}"
                             + (f" · {a:.0f} m²" if a else ""))
        c.setFont("Helvetica", 7); c.setFillGray(0.35)
        foot = ["Imagery: USDA NAIP (public domain) via Microsoft Planetary Computer. Layers: OpenStreetMap (ODbL, © "
                "OpenStreetMap contributors), FEMA NFHL (public domain), US Census.",
                "Counts are detected objects in ranked results, not a census. Confidence is heuristic, not calibrated."]
        for k, line in enumerate(foot):
            c.drawString(0.6 * inch, 0.6 * inch + (len(foot) - k) * 9, line)
        c.showPage(); c.save()
        return path.stat().st_size
