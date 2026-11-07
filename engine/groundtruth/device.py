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
    if name.startswith("cuda"):
        cap = float(os.environ.get("GROUNDTRUTH_VRAM_GB", "0") or 0)
        if cap > 0:  # hard per-process cap (allocations beyond it raise OOM instead of growing)
            import torch

            total = torch.cuda.get_device_properties(0).total_memory / 1024**3
            torch.cuda.set_per_process_memory_fraction(min(1.0, cap / total), 0)
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
