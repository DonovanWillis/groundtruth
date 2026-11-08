"""Height from USGS 3DEP lidar (Phase 6): per-place DTM / DSM / nDSM rasters at 1 m in EPSG:32617, built by
scripts/build_lidar.py with PDAL and cached under data/lidar/<place>/. Until a place is built, heights come from
Overture (stated in limits).
"""

from __future__ import annotations

import json
from typing import Any, Sequence

import numpy as np

from groundtruth import config


def _places() -> dict[str, Any]:
    return json.loads((config.SENSES_PATH.parent / "places.json").read_text())["places"]


def built_places() -> list[str]:
    d = config.DATA / "lidar"
    return sorted(p.name.replace("_", " ") for p in d.iterdir() if (p / "ndsm.tif").exists()) if d.exists() else []


def place_for(bbox: Sequence[float] | None) -> str | None:
    """The built place whose box contains the bbox centre (None if no lidar there)."""
    if not bbox:
        return None
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    pl = _places()
    for name in built_places():
        b = pl.get(name, {}).get("bbox")
        if b and b[0] <= cx <= b[2] and b[1] <= cy <= b[3]:
            return name
    return None


def available_for(bbox: Sequence[float] | None) -> bool:
    return place_for(bbox) is not None


def raster(place: str, kind: str = "ndsm"):
    import rasterio

    return rasterio.open(config.DATA / "lidar" / place.replace(" ", "_") / f"{kind}.tif")


def building_heights(feats: Sequence[dict[str, Any]], bbox, q: float = 90.0) -> dict[str, dict[str, Any]]:
    """Per building: the q-th percentile of nDSM inside its footprint (robust to edges / overhanging trees)."""
    from rasterio.mask import mask as rmask
    from shapely.geometry import mapping, shape

    from groundtruth.geo import to_measure

    place = place_for(bbox)
    if place is None:
        return {}
    out = {}
    with raster(place) as src:
        for f in feats:
            try:
                arr, _ = rmask(src, [mapping(to_measure(shape(f["geometry"])))], crop=True, filled=False)
            except ValueError:  # outside the raster
                continue
            v = np.ma.compressed(arr[0])
            v = v[np.isfinite(v)]
            if len(v) >= 3:
                out[f["properties"].get("id")] = {"height_m": round(float(np.percentile(v, q)), 1), "source": "lidar"}
    return out


def height_stats(geom_m, place: str) -> dict[str, Any] | None:
    """height_m (90th pct nDSM), mean height, volume_m3 (sum of nDSM × 1 m²) and ground elevation for one geometry."""
    from rasterio.mask import mask as rmask
    from shapely.geometry import mapping

    with raster(place) as src:
        try:
            arr, _ = rmask(src, [mapping(geom_m)], crop=True, filled=False)
        except ValueError:
            return None
    v = np.ma.compressed(arr[0])
    v = v[np.isfinite(v)]
    if not len(v):
        return None
    px = abs(src.res[0] * src.res[1])
    return {"height_m": round(float(np.percentile(v, 90)), 2), "mean_height_m": round(float(v.mean()), 2),
            "volume_m3": round(float(np.clip(v, 0, None).sum() * px), 1)}
