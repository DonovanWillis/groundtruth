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


class Engine:
    def __init__(self, provider: DataProvider, *, aoi: str = "county", year: int | None = None,
                 index: ChipIndex | None = None) -> None:
        self.provider = provider
        self.year = year or provider.imagery_years()[0]
        self.aoi = aoi
        self.index = index or ChipIndex(config.precompute_dir(self.year, aoi))
        self._clip = None
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

    def localise(self, i: int, qvec: np.ndarray, context_px: int = 84) -> tuple[int, float]:
        """Which of the chip's 16 cells best matches a text vector: OpenCLIP on a ``context_px`` crop centred on
        each cell (from the stored thumbnail), resized to 224. Query-time only (16 CLIP passes per chip)."""
        from PIL import Image

        img = Image.open(io.BytesIO(self.index.thumb_jpeg(i))).convert("RGB")
        g, cp, half = self.index.grid, config.CELL_PX, context_px // 2
        crops = []
        for cell in range(g * g):
            r, c = divmod(cell, g)
            cx, cy = c * cp + cp // 2, r * cp + cp // 2
            x0 = min(max(cx - half, 0), config.CHIP_PX - context_px)
            y0 = min(max(cy - half, 0), config.CHIP_PX - context_px)
            crops.append(np.asarray(img.crop((x0, y0, x0 + context_px, y0 + context_px)).resize((224, 224), Image.BILINEAR)))
        E = self._clip_model().embed_images(np.stack(crops), batch=16)
        s = E @ qvec
        best = int(np.argmax(s))
        return best, float(s[best])

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

    def find_similar(self, chip_ids: Sequence[str], exclude_ids: Sequence[str] = (), k: int = 50,
                     neg_weight: float = 0.5) -> Envelope:
        tool = "find_similar"
        pos = self._example_cells(chip_ids)
        if not pos:
            return declined(tool, VERSION, "none of the example ids are in the index")
        neg = self._example_cells(exclude_ids)
        t = StepTimer()
        with t.step("query_vector", f"{len(pos)} positive cells, {len(neg)} negative cells, λ={neg_weight}"):
            q = self._cell_query(pos, neg, neg_weight)
        skip = {i for i, _ in pos} | {i for i, _ in neg}
        with t.step("search", f"best-matching cell over {len(self.index) * self.index.n_cells} cells"):
            ranked = self._cell_rank(q, k * 3, skip)
        with t.step("dedupe", "cell NMS (overlapping chips)"):
            hits = self._nms(ranked, k, block=pos + neg)
        feats = [self.index.feature(i, cell=c, score=round(s, 4), rank=r + 1) for r, (i, s, c) in enumerate(hits)]
        return self._env(tool, result=Result(geojson=feature_collection(feats), metrics={
            "count": len(feats), "positives": len(pos), "negatives": len(neg)}),
            method=f"DINOv2 ViT-B/14 4×4 sub-cell cosine (best cell per chip); query = mean(positive cells) − "
                   f"{neg_weight}·mean(negative cells)",
            assumptions=["The example cells show the intended object"], steps=t.steps)

    # ------------------------------------------------------------------ refine
    def refine(self, session_id: str | None, accept_ids: Sequence[str] = (), reject_ids: Sequence[str] = (),
               k: int = 50, pool: int = 1500) -> Envelope:
        """Per-session logistic regression on DINOv2 cell vectors (accepted vs rejected + background cells),
        applied to the cells of a candidate pool retrieved by the centroid query. Target < 1 s."""
        from sklearn.linear_model import LogisticRegression

        tool = "refine"
        sid = session_id or uuid.uuid4().hex[:12]
        sess = self.sessions.setdefault(sid, Session(sid))
        sess.accept += [a for a in accept_ids if a not in sess.accept]
        sess.reject += [r for r in reject_ids if r not in sess.reject]
        pos = self._example_cells(sess.accept)
        neg = self._example_cells(sess.reject)
        if not pos:
            return declined(tool, VERSION, "refine needs at least one accepted example")
        t = StepTimer()
        with t.step("pool", f"centroid query → top {pool} chips"):
            skip = {i for i, _ in pos} | {i for i, _ in neg}
            cand = [i for i, _, _ in self._cell_rank(self._cell_query(pos, neg, 0.5), pool, skip)][:pool]
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
        feats = [self.index.feature(i, cell=c, score=round(p, 4), rank=r + 1) for r, (i, p, c) in enumerate(hits)]
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
        """Planned: SAM 2 polygons prompted by each hit's cell box, lazily, cached by chip#cell."""
        return declined("outline", VERSION, NOT_IMPLEMENTED)

    # ------------------------------------------------------------------ measure
    def measure(self, geojson: dict[str, Any], *, to_layer: str | None = None) -> Envelope:
        tool = "measure"
        feats = geojson.get("features", [])
        if not feats:
            return declined(tool, VERSION, "no features to measure")
        t = StepTimer()
        layer_geom = None
        if to_layer:
            with t.step("load_layer", to_layer):
                from shapely.ops import unary_union

                lyr = self.provider.get_layer(to_layer)
                layer_geom = to_measure(unary_union([shape(f["geometry"]) for f in lyr["features"] if f.get("geometry")]))
        out, tot_m2 = [], 0.0
        with t.step("measure", f"{len(feats)} features in EPSG:32617"):
            for f in feats:
                g = shape(f["geometry"])
                gm = to_measure(g)
                p = dict(f.get("properties") or {})
                p["area_m2"] = round(gm.area, 2)
                p["area_acres"] = round(gm.area / SQM_PER_ACRE, 4)
                p["perimeter_m"] = round(gm.length if gm.geom_type in ("Polygon", "MultiPolygon") else length_m(g), 2)
                if layer_geom is not None:
                    p[f"dist_m_to_{to_layer}"] = round(gm.distance(layer_geom), 1)
                tot_m2 += gm.area
                out.append({"type": "Feature", "id": f.get("id"), "geometry": f["geometry"], "properties": p})
        metrics = {"count": len(out), "area_m2_total": round(tot_m2, 2), "area_acres_total": round(tot_m2 / SQM_PER_ACRE, 4)}
        return self._env(tool, status="ok", result=Result(geojson=feature_collection(out), metrics=metrics),
                         confidence=1.0, method="Planar measurement after reprojection EPSG:4326 → EPSG:32617 (UTM 17N)",
                         assumptions=["Input geometry is EPSG:4326"], limits=["UTM 17N distortion < 0.1% in Mecklenburg"],
                         sources=[], steps=t.steps)

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
                         limits=[], sources=self.provider.source_for(name.split("_")[0]) or self.provider.sources(),
                         steps=t.steps)

    def filter(self, geojson: dict[str, Any], where: dict[str, Any]) -> Envelope:
        """``where`` keys (all optional, ANDed): ``intersects_layer`` (+ ``layer_where`` {prop: value}),
        ``not_intersects_layer``, ``max_dist_m`` + ``dist_layer``, ``min_area_acres``, ``max_area_acres``,
        ``min_score``."""
        tool = "filter"
        from shapely.ops import unary_union

        t = StepTimer()
        feats = geojson.get("features", [])

        def layer_union(name: str, lw: dict[str, Any] | None = None):
            fc = self.provider.get_layer(name)
            gs = [shape(f["geometry"]) for f in fc["features"] if f.get("geometry") and
                  all(f["properties"].get(k) == v for k, v in (lw or {}).items())]
            return to_measure(unary_union(gs)) if gs else None

        with t.step("prepare", json.dumps(where)[:120]):
            inter = layer_union(where["intersects_layer"], where.get("layer_where")) if where.get("intersects_layer") else None
            notinter = layer_union(where["not_intersects_layer"]) if where.get("not_intersects_layer") else None
            distl = layer_union(where["dist_layer"]) if where.get("dist_layer") else None
        keep = []
        with t.step("filter", f"{len(feats)} features"):
            for f in feats:
                gm = to_measure(shape(f["geometry"]))
                p = f.get("properties") or {}
                a = gm.area / SQM_PER_ACRE
                if inter is not None and not gm.intersects(inter):
                    continue
                if notinter is not None and gm.intersects(notinter):
                    continue
                if distl is not None and gm.distance(distl) > float(where.get("max_dist_m", 0)):
                    continue
                if "min_area_acres" in where and a < where["min_area_acres"]:
                    continue
                if "max_area_acres" in where and a > where["max_area_acres"]:
                    continue
                if "min_score" in where and float(p.get("score", 0)) < where["min_score"]:
                    continue
                keep.append(f)
        return self._env(tool, status="ok", result=Result(geojson=feature_collection(keep), metrics={
            "count_in": len(feats), "count_out": len(keep)}), confidence=1.0,
            method="Spatial/attribute predicates evaluated in EPSG:32617", limits=[], sources=[], steps=t.steps)

    def export(self, geojson: dict[str, Any], fmt: str = "geojson") -> Envelope:
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
            else:
                return declined(tool, VERSION, f"unsupported format {fmt!r} (geojson, csv)")
            out = config.DATA / "out" / "exports"
            out.mkdir(parents=True, exist_ok=True)
            name = f"export_{time.strftime('%Y%m%dT%H%M%S')}_{len(feats)}.{fmt}"
            (out / name).write_text(content)
        return self._env(tool, status="ok", result=Result(metrics={
            "count": len(feats), "format": fmt, "file": f"data/out/exports/{name}", "bytes": len(content),
            "content": content if len(content) < 2_000_000 else None}), confidence=1.0,
            method=f"serialised {len(feats)} features as {fmt}", limits=[], sources=[], steps=t.steps)
