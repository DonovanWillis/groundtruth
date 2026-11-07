"""Object outlines with SAM 2.1 (hiera-tiny, Apache-2.0), prompted by a hit's 16.8 m cell box.

Lazy by design: only for results on screen, cached by ``chip_id#cell`` under data/cache/outlines/<index version>/.
Never run county-wide on CPU.
"""

from __future__ import annotations

import io
import json
import time
from functools import cached_property
from typing import Any

import numpy as np
from rasterio import features as rfeatures
from rasterio.transform import from_origin
from shapely.geometry import mapping, shape

from groundtruth import config
from groundtruth.device import pick_device, torch_device
from groundtruth.geo import SQM_PER_ACRE, to_wgs84
from groundtruth.index import ChipIndex

SAM_MODEL = "facebook/sam2.1-hiera-tiny"
SAM_ID = "sam2.1-hiera-tiny"


class Outliner:
    def __init__(self, device: str | None = None) -> None:
        self.device_name = pick_device(device)
        self.device = torch_device(self.device_name)

    @cached_property
    def _model(self):
        from transformers import Sam2Model, Sam2Processor

        proc = Sam2Processor.from_pretrained(SAM_MODEL)
        model = Sam2Model.from_pretrained(SAM_MODEL).to(self.device).eval()
        return proc, model

    def _cache_path(self, chip_id: str, cell: int):
        return config.DATA / "cache" / "outlines" / config.INDEX_VERSION / f"{chip_id}_{cell}.json"

    def outline(self, index: ChipIndex, i: int, cell: int, margin_px: int = 8) -> dict[str, Any]:
        """→ GeoJSON Feature (EPSG:4326) with area_m2/area_acres/sam_score/ms/cached."""
        chip_id = index.ids[i]
        cp = self._cache_path(chip_id, cell)
        if cp.exists():
            f = json.loads(cp.read_text())
            f["properties"]["cached"] = True
            return f
        import torch
        from PIL import Image

        t0 = time.perf_counter()
        img = Image.open(io.BytesIO(index.thumb_jpeg(i))).convert("RGB")
        g = index.grid
        px = config.CHIP_PX // g
        r, c = divmod(int(cell), g)
        m = margin_px
        box = [max(0, c * px - m), max(0, r * px - m), min(config.CHIP_PX, (c + 1) * px + m),
               min(config.CHIP_PX, (r + 1) * px + m)]
        point = [c * px + px / 2, r * px + px / 2]
        proc, model = self._model
        inputs = proc(images=img, input_boxes=[[box]], input_points=[[[point]]], input_labels=[[[1]]],
                      return_tensors="pt").to(self.device)
        with torch.inference_mode():
            out = model(**inputs, multimask_output=True)
        masks = proc.post_process_masks(out.pred_masks.cpu(), inputs["original_sizes"].cpu())[0]
        cand = np.asarray(masks).reshape(-1, config.CHIP_PX, config.CHIP_PX).astype(bool)
        ious = out.iou_scores.reshape(-1).float().cpu().numpy()[: len(cand)]
        box_area = (box[2] - box[0]) * (box[3] - box[1])
        ok = [k for k in range(len(cand)) if 0 < cand[k].sum() <= 1.5 * box_area] or list(range(len(cand)))
        k = max(ok, key=lambda j: ious[j])
        mask, score = cand[k], float(ious[k])
        # polygonise in UTM: chip pixel (0,0) = NW corner
        x0, y0 = float(index.meta["x0_m"][i]), float(index.meta["y0_m"][i])
        tr = from_origin(x0, y0 + config.CHIP_M, config.GSD_M, config.GSD_M)
        polys = [shape(geom) for geom, v in rfeatures.shapes(mask.astype(np.uint8), mask=mask, transform=tr) if v == 1]
        ms = round((time.perf_counter() - t0) * 1000, 1)
        props: dict[str, Any] = {"chip_id": chip_id, "cell": int(cell), "example": f"{chip_id}#{cell}",
                                 "sam_score": round(score, 4), "model": SAM_ID, "ms": ms, "cached": False}
        if not polys:
            feat = {"type": "Feature", "id": f"{chip_id}#{cell}", "geometry": None,
                    "properties": {**props, "area_m2": 0.0, "area_acres": 0.0, "empty": True}}
        else:
            # keep the component overlapping the prompt cell most
            from shapely.geometry import box as sbox

            cx0, cy1 = x0 + c * px * config.GSD_M, y0 + config.CHIP_M - r * px * config.GSD_M
            cellbox = sbox(cx0, cy1 - px * config.GSD_M, cx0 + px * config.GSD_M, cy1)
            best = max(polys, key=lambda p: (p.intersection(cellbox).area, p.area)).simplify(0.3)
            area = best.area
            feat = {"type": "Feature", "id": f"{chip_id}#{cell}", "geometry": mapping(to_wgs84(best)),
                    "properties": {**props, "area_m2": round(area, 2), "area_acres": round(area / SQM_PER_ACRE, 5)}}
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(feat))
        return feat
