"""Paths and fixed engine parameters (versioned: change => bump INDEX_VERSION)."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("GROUNDTRUTH_DATA", ROOT / "data"))

# Chip grid (EPSG:32617). 224 px at 0.6 m = 134.4 m; stride 192 px = 115.2 m (32 px ≈ 19 m overlap).
GSD_M = 0.6
CHIP_PX = 224
STRIDE_PX = 192
CHIP_M = CHIP_PX * GSD_M
STRIDE_M = STRIDE_PX * GSD_M
INDEX_VERSION = "chips224s192-g0.6-v1"

# AOIs (EPSG:4326)
AOIS: dict[str, tuple[float, float, float, float]] = {
    "unc_charlotte": (-80.745, 35.297, -80.722, 35.315),
}


def precompute_dir(year: int, aoi: str) -> Path:
    return DATA / "precompute" / INDEX_VERSION / aoi / str(year)
