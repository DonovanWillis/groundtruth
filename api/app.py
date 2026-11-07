"""Groundtruth engine API (contract: docs/CONTRACT.md). Separate process from the labelling server.

  uvicorn api.app:app --host 0.0.0.0 --port 8000
Every tool: POST /api/v1/tools/{tool} → Envelope (HTTP 200 even when declined).
"""

from __future__ import annotations

import json
import os
import threading
from functools import lru_cache
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from groundtruth import __version__, config
from groundtruth.envelope import Envelope, declined
from groundtruth.index import ChipIndex
from groundtruth.providers.public import PublicDataProvider
from groundtruth.tools import NOT_IMPLEMENTED, VERSION, Engine

CONTRACT = "0.2"
app = FastAPI(title="Groundtruth API", version=__version__)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
_provider = PublicDataProvider(download_scenes=False)
_lock = threading.Lock()

TOOLS = {"search_text": True, "pick_candidates": True, "find_similar": True, "refine": True, "measure": True,
         "add_layer": True, "filter": True, "export": True, "outline": True}


def available_indexes() -> list[dict[str, Any]]:
    root = config.DATA / "precompute" / config.INDEX_VERSION
    out = []
    for info in sorted(root.glob("*/*/index.json")):
        d = json.loads(info.read_text())
        out.append({"aoi": info.parent.parent.name, "year": int(info.parent.name), "chips": d["chips"],
                    "index_version": d["index_version"]})
    return out


def default_aoi(year: int) -> str:
    idx = [i for i in available_indexes() if i["year"] == year]
    if any(i["aoi"] == "county" for i in idx):
        return "county"
    if not idx:
        raise HTTPException(503, f"no index built for {year}")
    return max(idx, key=lambda i: i["chips"])["aoi"]


@lru_cache(maxsize=8)
def engine(aoi: str, year: int) -> Engine:
    return Engine(_provider, aoi=aoi, year=year, index=ChipIndex(config.precompute_dir(year, aoi)))


def eng(aoi: str | None, year: int | None) -> Engine:
    y = year or _provider.primary_year
    a = aoi or default_aoi(y)
    with _lock:
        return engine(a, y)


# ---------------- request bodies ----------------
class Common(BaseModel):
    year: int | None = None
    aoi: str | None = None


class SearchTextIn(Common):
    query: str
    k: int = Field(50, ge=1, le=500)


class PickIn(Common):
    query: str
    n: int = Field(6, ge=2, le=12)


class FindSimilarIn(Common):
    examples: list[str]
    exclude: list[str] = []
    k: int = Field(50, ge=1, le=500)


class RefineIn(Common):
    session_id: str | None = None
    accept: list[str] = []
    reject: list[str] = []
    k: int = Field(50, ge=1, le=500)


class OutlineIn(Common):
    examples: list[str]
    max: int = Field(12, ge=1, le=50)


class GeoIn(Common):
    geojson: dict[str, Any]


class MeasureIn(GeoIn):
    to_layer: str | None = None


class FilterIn(GeoIn):
    where: dict[str, Any] = {}


class ExportIn(GeoIn):
    format: str = "geojson"


class AddLayerIn(Common):
    name: str
    bbox: list[float] | None = None


def _env(e: Envelope) -> JSONResponse:
    return JSONResponse(e.model_dump(mode="json"))


# ---------------- meta ----------------
@app.get("/api/v1/health")
def health() -> dict[str, Any]:
    return {"ok": True, "contract": CONTRACT, "engine_version": VERSION, "indexes": available_indexes(),
            "primary_year": _provider.primary_year}


@app.get("/api/v1/tools")
def tools() -> list[dict[str, Any]]:
    return [{"tool": t, "implemented": ok, "version": VERSION} for t, ok in TOOLS.items()]


@app.get("/api/v1/layers")
def layers() -> list[str]:
    return _provider.layer_names()


@app.get("/api/v1/chips/{chip_id}.jpg")
def chip(chip_id: str, year: int | None = None, aoi: str | None = None) -> Response:
    y = year or int(chip_id.split("_", 1)[0])
    e = eng(aoi, y)
    if chip_id not in e.index.pos:
        raise HTTPException(404, "unknown chip")
    return Response(e.index.thumb_jpeg(e.index.pos[chip_id]), media_type="image/jpeg",
                    headers={"Cache-Control": "max-age=86400"})


@app.get("/api/v1/events")
def events() -> Response:
    return Response(status_code=501, content="reserved for the agent SSE stream (contract v0.1)")


# ---------------- tools ----------------
@app.post("/api/v1/tools/search_text")
def t_search_text(b: SearchTextIn) -> JSONResponse:
    return _env(eng(b.aoi, b.year).search_text(b.query, k=b.k))


@app.post("/api/v1/tools/pick_candidates")
def t_pick(b: PickIn) -> JSONResponse:
    return _env(eng(b.aoi, b.year).pick_candidates(b.query, n=b.n))


@app.post("/api/v1/tools/find_similar")
def t_find_similar(b: FindSimilarIn) -> JSONResponse:
    return _env(eng(b.aoi, b.year).find_similar(b.examples, b.exclude, k=b.k))


@app.post("/api/v1/tools/refine")
def t_refine(b: RefineIn) -> JSONResponse:
    return _env(eng(b.aoi, b.year).refine(b.session_id, b.accept, b.reject, k=b.k))


@app.post("/api/v1/tools/outline")
def t_outline(b: OutlineIn) -> JSONResponse:
    return _env(eng(b.aoi, b.year).outline(b.examples, max=b.max))


@app.post("/api/v1/tools/measure")
def t_measure(b: MeasureIn) -> JSONResponse:
    return _env(eng(b.aoi, b.year).measure(b.geojson, to_layer=b.to_layer))


@app.post("/api/v1/tools/filter")
def t_filter(b: FilterIn) -> JSONResponse:
    return _env(eng(b.aoi, b.year).filter(b.geojson, b.where))


@app.post("/api/v1/tools/export")
def t_export(b: ExportIn) -> JSONResponse:
    return _env(eng(b.aoi, b.year).export(b.geojson, b.format))


@app.post("/api/v1/tools/add_layer")
def t_add_layer(b: AddLayerIn) -> JSONResponse:
    return _env(eng(b.aoi, b.year).add_layer(b.name, b.bbox))


@app.post("/api/v1/tools/{tool}")
def t_unknown(tool: str) -> JSONResponse:
    return _env(declined(tool, VERSION, NOT_IMPLEMENTED if tool in TOOLS else f"unknown tool {tool!r}"))


# ---------------- NAIP display tiles (cached; same source as the labelling page) ----------------
_TILE_SEARCH: dict[int, str] = {}


@app.get("/api/v1/tiles/naip/{year}/{z}/{x}/{y}.png")
def naip_tile(year: int, z: int, x: int, y: int) -> Response:
    import httpx

    cache = config.DATA / "cache" / "tiles" / "naip" / str(year) / str(z) / str(x) / f"{y}.png"
    if cache.exists():
        return FileResponse(cache, media_type="image/png", headers={"Cache-Control": "max-age=86400"})
    if z < 10 or z > 18 or year not in _provider.imagery_years():
        return Response(status_code=204)
    base = "https://planetarycomputer.microsoft.com/api/data/v1"
    for attempt in range(2):
        if year not in _TILE_SEARCH or attempt:
            body = {"collections": ["naip"], "filter-lang": "cql2-json", "filter": {"op": "and", "args": [
                {"op": "=", "args": [{"property": "naip:year"}, str(year)]},
                {"op": "=", "args": [{"property": "naip:state"}, "nc"]}]}}
            _TILE_SEARCH[year] = httpx.post(f"{base}/mosaic/register", json=body, timeout=30).json()["searchid"]
        r = httpx.get(f"{base}/mosaic/{_TILE_SEARCH[year]}/tiles/WebMercatorQuad/{z}/{x}/{y}@1x.png",
                      params={"collection": "naip", "assets": "image", "asset_bidx": "image|1,2,3", "nodata": "0"},
                      timeout=60)
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
            cache.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache.with_suffix(".tmp"); tmp.write_bytes(r.content); os.replace(tmp, cache)
            return Response(r.content, media_type="image/png", headers={"Cache-Control": "max-age=86400"})
        if r.status_code == 404 and "Unknown search" not in r.text:
            return Response(status_code=204)
    return Response(status_code=502)


@app.get("/api/v1/boundary")
def boundary() -> dict[str, Any]:
    return _provider.get_boundary()


# ---------------- demo UI (web/dist, built by Vite) ----------------
_DIST = config.ROOT / "web" / "dist"


@app.get("/")
def ui_index() -> Response:
    if (_DIST / "index.html").exists():
        return FileResponse(_DIST / "index.html", headers={"Cache-Control": "no-store"})
    return JSONResponse({"ok": True, "ui": "not built (cd web && npm run build)", "docs": "/docs"})


@app.get("/assets/{path:path}")
def ui_assets(path: str) -> Response:
    p = (_DIST / "assets" / path).resolve()
    if not str(p).startswith(str((_DIST / "assets").resolve())) or not p.exists():
        raise HTTPException(404)
    return FileResponse(p)
