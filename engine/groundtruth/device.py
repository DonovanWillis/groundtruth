"""Compute device auto-selection: cuda, then mps, then cpu.

``GROUNDTRUTH_DEVICE`` overrides (e.g. ``cpu`` on the production PC, whose GPU must not be used).
"""

from __future__ import annotations

import os


def pick_device(override: str | None = None) -> str:
    forced = override or os.environ.get("GROUNDTRUTH_DEVICE")
    if forced:
        return forced
    try:
        import torch
    except ImportError:
        return "cpu"
    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"
