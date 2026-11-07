"""Engine tools. Each returns an Envelope (docs/CONTRACT.md).

    eng = Engine(PublicDataProvider(), aoi="unc_charlotte")
    eng.search_text("swimming pool", k=24)
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np

from groundtruth import config
from groundtruth.envelope import Envelope, Result, StepTimer, declined, feature_collection
from groundtruth.index import ChipIndex
from groundtruth.providers.base import DataProvider

PEOPLE_TERMS = ("owner", "who lives", "resident", "income", "race", "ethnicity", "crime", "school rating",
                "demographic", "home address of")


def _people(query: str) -> bool:
    q = query.lower()
    return any(t in q for t in PEOPLE_TERMS)


class Engine:
    def __init__(self, provider: DataProvider, *, aoi: str = "county", year: int | None = None,
                 index: ChipIndex | None = None) -> None:
        self.provider = provider
        self.year = year or provider.imagery_years()[0]
        self.aoi = aoi
        self.index = index or ChipIndex(config.precompute_dir(self.year, aoi))
        self._clip = None

    # --- shared ---
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
               f"Results are 134 m image chips ({config.INDEX_VERSION}), not object outlines"]
        if self.aoi != "county":
            out.append(f"Only the '{self.aoi}' area is indexed, not the whole county")
        return out

    def _status(self) -> str:
        return "ok" if self.aoi == "county" else "partial"

    # --- tools ---
    def search_text(self, query: str, k: int = 50) -> Envelope:
        tool, ver = "search_text", "0.1.0"
        if not query.strip():
            return declined(tool, ver, "empty query")
        if _people(query):
            return declined(tool, ver, "Groundtruth does not search for information about people")
        t = StepTimer()
        with t.step("embed_query", "OpenCLIP text, 4-prompt ensemble"):
            q = self._clip_model().embed_query(query)
        with t.step("search", f"exact cosine over {len(self.index)} chips"):
            D, I = self.index.search("clip", q, k)
        feats = [self.index.feature(int(i), score=round(float(d), 4), rank=r + 1) for r, (d, i) in enumerate(zip(D, I))]
        return Envelope(
            tool=tool, version=ver, status=self._status(),
            result=Result(geojson=feature_collection(feats),
                          metrics={"count": len(feats), "indexed_chips": len(self.index),
                                   "score_max": round(float(D[0]), 4) if len(D) else None}),
            confidence=None, method=f"OpenCLIP ViT-B-16 (laion2b_s34b_b88k) text→image cosine, NAIP {self.year}",
            assumptions=[f"NAIP {self.year} imagery reflects the ground today"], limits=self._limits(),
            sources=self._sources(), steps=t.steps)

    def pick_candidates(self, query: str, n: int = 6, pool: int = 200, seed: int = 0) -> Envelope:
        """Cluster the top ``pool`` text matches (in DINOv2 space) into ``n`` groups; one representative each —
        the highest-scoring member — so the user can pick which meaning they intended."""
        tool, ver = "pick_candidates", "0.1.0"
        base = self.search_text(query, k=pool)
        if base.status == "declined":
            return base.model_copy(update={"tool": tool, "version": ver})
        from sklearn.cluster import KMeans

        t = StepTimer()
        t.steps.extend(base.steps)
        feats = base.result.geojson["features"]
        idx = np.array([self.index.pos[f["id"]] for f in feats])
        scores = np.array([f["properties"]["score"] for f in feats])
        with t.step("cluster", f"k-means k={n} on DINOv2 of top {len(idx)}"):
            X = self.index.dino[idx]
            km = KMeans(n_clusters=min(n, len(idx)), n_init=10, random_state=seed).fit(X)
        groups = []
        for g in range(km.n_clusters):
            members = np.where(km.labels_ == g)[0]
            best = members[np.argmax(scores[members])]
            groups.append((float(scores[best]), g, best, members))
        groups.sort(key=lambda x: (-x[0], x[1]))
        out = []
        for rank, (s, g, best, members) in enumerate(groups, 1):
            out.append(self.index.feature(int(idx[best]), score=round(s, 4), rank=rank, group=rank,
                                          group_size=int(len(members)),
                                          group_mean_score=round(float(scores[members].mean()), 4),
                                          group_members=[self.index.ids[int(idx[m])] for m in
                                                         members[np.argsort(-scores[members])][:12]]))
        return Envelope(
            tool=tool, version=ver, status=base.status,
            result=Result(geojson=feature_collection(out),
                          metrics={"count": len(out), "pool": len(idx),
                                   "group_sizes": [o["properties"]["group_size"] for o in out]}),
            method=base.method + f"; top {len(idx)} clustered with k-means (k={n}, seed={seed}) on DINOv2 ViT-B/14",
            assumptions=base.assumptions + ["Different visual clusters approximate different meanings of the query"],
            limits=base.limits, sources=base.sources, steps=t.steps)

    def find_similar(self, chip_ids: Sequence[str], exclude_ids: Sequence[str] = (), k: int = 50,
                     neg_weight: float = 0.5) -> Envelope:
        tool, ver = "find_similar", "0.1.0"
        pos = [self.index.pos[c] for c in chip_ids if c in self.index.pos]
        if not pos:
            return declined(tool, ver, "none of the example chip_ids are in the index")
        neg = [self.index.pos[c] for c in exclude_ids if c in self.index.pos]
        t = StepTimer()
        with t.step("query_vector", f"{len(pos)} positives, {len(neg)} negatives, λ={neg_weight}"):
            q = self.index.dino[pos].mean(0)
            if neg:
                q = q - neg_weight * self.index.dino[neg].mean(0)
            q /= max(np.linalg.norm(q), 1e-12)
        skip = set(pos) | set(neg)
        with t.step("search", f"exact cosine over {len(self.index)} chips"):
            D, I = self.index.search("dino", q, k + len(skip))
        feats: list[dict[str, Any]] = []
        for d, i in zip(D, I):
            if int(i) in skip:
                continue
            feats.append(self.index.feature(int(i), score=round(float(d), 4), rank=len(feats) + 1))
            if len(feats) >= k:
                break
        return Envelope(
            tool=tool, version=ver, status=self._status(),
            result=Result(geojson=feature_collection(feats), metrics={"count": len(feats), "positives": len(pos),
                                                                       "negatives": len(neg)}),
            method=f"DINOv2 ViT-B/14 CLS cosine; query = mean(positives) − {neg_weight}·mean(negatives)",
            assumptions=["The example chips show the intended object type"], limits=self._limits(),
            sources=self._sources(), steps=t.steps)
