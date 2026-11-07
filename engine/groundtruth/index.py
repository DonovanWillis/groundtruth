"""Loads a precomputed chip index (chips.parquet + {dino,clip}.npy/.faiss + thumbs pack)."""

from __future__ import annotations

import json
from functools import cached_property
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq


class ChipIndex:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        if not (self.root / "index.json").exists():
            raise FileNotFoundError(f"no index at {self.root}; run scripts/precompute_county.py")
        self.info: dict[str, Any] = json.loads((self.root / "index.json").read_text())
        t = pq.read_table(self.root / "chips.parquet")
        self.meta = {c: t.column(c).to_numpy(zero_copy_only=False) for c in t.column_names}
        self.ids: list[str] = list(self.meta["chip_id"])
        self.pos = {cid: i for i, cid in enumerate(self.ids)}

    def __len__(self) -> int:
        return len(self.ids)

    @cached_property
    def dino(self) -> np.ndarray:
        return np.load(self.root / "dino.npy").astype(np.float32)

    @cached_property
    def clip(self) -> np.ndarray:
        return np.load(self.root / "clip.npy").astype(np.float32)

    def _faiss(self, name: str):
        import faiss

        return faiss.read_index(str(self.root / f"{name}.faiss"))

    @cached_property
    def dino_index(self):
        return self._faiss("dino")

    @cached_property
    def clip_index(self):
        return self._faiss("clip")

    def search(self, kind: str, q: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
        """Exact cosine top-k. Ties broken by chip_id (deterministic)."""
        idx = self.dino_index if kind == "dino" else self.clip_index
        k = min(k, len(self))
        D, I = idx.search(np.ascontiguousarray(q, dtype=np.float32).reshape(1, -1), k)
        order = sorted(range(len(I[0])), key=lambda j: (-round(float(D[0][j]), 6), self.ids[I[0][j]]))
        return D[0][order], I[0][order]

    @cached_property
    def _thumb_offsets(self) -> np.ndarray:
        return np.load(self.root / "thumbs_offsets.npy")

    def thumb_jpeg(self, i: int) -> bytes:
        o = self._thumb_offsets
        with open(self.root / "thumbs.bin", "rb") as f:
            f.seek(int(o[i]))
            return f.read(int(o[i + 1] - o[i]))

    def feature(self, i: int, **props: Any) -> dict[str, Any]:
        m = self.meta
        w, s, e, n = (float(m[k][i]) for k in ("west", "south", "east", "north"))
        return {
            "type": "Feature", "id": self.ids[i],
            "geometry": {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]},
            "properties": {"chip_id": self.ids[i], "year": int(m["year"][i]), "scene_id": str(m["scene_id"][i]),
                           "thumb_url": f"/api/chips/{self.ids[i]}.jpg", **props},
        }
