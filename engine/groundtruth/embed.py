"""Image/text embedders. All outputs are float32, L2-normalised (so inner product == cosine).

- DINOv2 ViT-B/14 (``facebook/dinov2-base``, Apache-2.0): image↔image similarity (find_similar, clustering).
  Input 224×224 RGB, ImageNet mean/std; vector = final-layer-normed CLS token (768-d).
- OpenCLIP ViT-B-16 ``laion2b_s34b_b88k`` (MIT): text↔image (search_text). Input 224×224 RGB, CLIP mean/std;
  512-d. Text queries use a small aerial-imagery prompt ensemble (mean of normalised prompt embeddings).
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Sequence

import numpy as np

from groundtruth.device import pick_device

DINO_MODEL = "facebook/dinov2-base"
DINO_REVISION = "f9e44c814b77203eaa57a6bdbbd535f21ede1415"  # pinned (same snapshot already in the HF cache)
DINO_ID = "dinov2-vitb14-cls-v1"
CLIP_ARCH = "ViT-B-16"
CLIP_PRETRAINED = "laion2b_s34b_b88k"
CLIP_ID = "openclip-vitb16-laion2b_s34b_b88k-v1"

IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
CLIP_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
CLIP_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)

PROMPTS = (
    "an aerial photo of {}.",
    "a satellite image of {}.",
    "a high-resolution overhead view of {}.",
    "{} seen from above.",
)


def _threads() -> None:
    import torch

    n = int(os.environ.get("GROUNDTRUTH_THREADS", "0") or 0)
    if n > 0:
        torch.set_num_threads(n)


def _l2(x: np.ndarray) -> np.ndarray:
    x = x.astype(np.float32, copy=False)
    return x / np.clip(np.linalg.norm(x, axis=1, keepdims=True), 1e-12, None)


def _to_tensor(chips: np.ndarray, mean: np.ndarray, std: np.ndarray, device: str):
    import torch

    if chips.ndim == 3:
        chips = chips[None]
    if chips.shape[1:3] != (224, 224):
        raise ValueError(f"expected (N,224,224,3) uint8 chips, got {chips.shape}")
    x = (chips.astype(np.float32) / 255.0 - mean) / std
    return torch.from_numpy(np.ascontiguousarray(x.transpose(0, 3, 1, 2))).to(device)


class DinoEmbedder:
    model_id = DINO_ID
    dim = 768

    def __init__(self, device: str | None = None) -> None:
        import torch
        from transformers import AutoModel

        _threads()
        self.device = pick_device(device)
        self.model = AutoModel.from_pretrained(DINO_MODEL, revision=DINO_REVISION).to(self.device).eval()
        self._torch = torch

    def embed_images(self, chips: np.ndarray, batch: int = 32) -> np.ndarray:
        out = []
        with self._torch.inference_mode():
            for i in range(0, len(chips), batch):
                x = _to_tensor(chips[i : i + batch], IMAGENET_MEAN, IMAGENET_STD, self.device)
                out.append(self.model(pixel_values=x).pooler_output.float().cpu().numpy())
        return _l2(np.concatenate(out)) if out else np.zeros((0, self.dim), np.float32)


class ClipEmbedder:
    model_id = CLIP_ID
    dim = 512

    def __init__(self, device: str | None = None) -> None:
        import open_clip
        import torch

        _threads()
        self.device = pick_device(device)
        self.model, _, _ = open_clip.create_model_and_transforms(CLIP_ARCH, pretrained=CLIP_PRETRAINED)
        self.model = self.model.to(self.device).eval()
        self.tokenizer = open_clip.get_tokenizer(CLIP_ARCH)
        self._torch = torch

    def embed_images(self, chips: np.ndarray, batch: int = 32) -> np.ndarray:
        out = []
        with self._torch.inference_mode():
            for i in range(0, len(chips), batch):
                x = _to_tensor(chips[i : i + batch], CLIP_MEAN, CLIP_STD, self.device)
                out.append(self.model.encode_image(x).float().cpu().numpy())
        return _l2(np.concatenate(out)) if out else np.zeros((0, self.dim), np.float32)

    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        with self._torch.inference_mode():
            tok = self.tokenizer(list(texts)).to(self.device)
            return _l2(self.model.encode_text(tok).float().cpu().numpy())

    def embed_query(self, query: str) -> np.ndarray:
        """Prompt-ensembled query vector (1, 512)."""
        v = self.embed_texts([p.format(query) for p in PROMPTS]).mean(axis=0, keepdims=True)
        return _l2(v)


@lru_cache(maxsize=2)
def get_clip(device: str | None = None) -> ClipEmbedder:
    return ClipEmbedder(device)


@lru_cache(maxsize=2)
def get_dino(device: str | None = None) -> DinoEmbedder:
    return DinoEmbedder(device)
