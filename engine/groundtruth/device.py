"""Compute device auto-selection: cuda, then mps, then cpu.

``GROUNDTRUTH_DEVICE`` overrides (e.g. ``cpu`` on the production PC, whose GPU must not be used).
"""

from __future__ import annotations

import os


def torch_device(name: str):
    """Turn a device name into something ``tensor.to()`` accepts. ``dml`` = DirectML (AMD/Intel GPUs on
    Windows via torch-directml, MIT)."""
    if name == "dml":
        import torch_directml

        return torch_directml.device()
    return name


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
    try:
        import torch_directml

        if torch_directml.is_available():
            return "dml"
    except ImportError:
        pass
    return "cpu"
