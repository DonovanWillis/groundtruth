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
INDEX_VERSION = "chips224s192-g0.6-v2cells"

# Sub-chip vectors (v2): DINOv2 patch tokens pooled to a CELL_GRID x CELL_GRID grid (16 cells of 56 px = 33.6 m);
# OpenCLIP on the whole chip + 2x2 quadrant crops upsampled to 224 (CLIP_SUBCROPS=True).
CELL_GRID = 4
CELL_PX = CHIP_PX // CELL_GRID
CLIP_SUBCROPS = True

SENSES_PATH = Path(__file__).resolve().parent / "conf" / "senses.json"

# AOIs (EPSG:4326)
AOIS: dict[str, tuple[float, float, float, float]] = {
    "unc_charlotte": (-80.745, 35.297, -80.722, 35.315),
    # residential area with many backyard pools, used to judge find_similar fairly
    "south_charlotte": (-80.835, 35.050, -80.815, 35.066),
}


def precompute_dir(year: int, aoi: str) -> Path:
    return DATA / "precompute" / INDEX_VERSION / aoi / str(year)
