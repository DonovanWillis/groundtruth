"""Count consistency: filter never returns more objects than it was given, and counts equal feature counts."""
import json
from pathlib import Path

from groundtruth.tools import Engine

FIX = Path(__file__).resolve().parents[1] / "docs" / "fixtures"


class _Prov:
    name = "fake"

    def get_layer(self, name, bbox=None):
        return {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {}, "geometry": {"type": "LineString",
                                                               "coordinates": [[-80.83, 35.05], [-80.82, 35.06]]}}]}

    def source_for(self, k):
        return []

    def sources(self):
        return []


def _engine():
    e = Engine.__new__(Engine)  # filter needs no index
    e.provider, e.year, e.aoi = _Prov(), 2022, "test"
    return e


def _square(lon, lat, d=0.0001):
    return {"type": "Feature", "properties": {"confidence": 0.9},
            "geometry": {"type": "Polygon", "coordinates": [[[lon, lat], [lon + d, lat], [lon + d, lat + d], [lon, lat + d], [lon, lat]]]}}


def test_filter_count_never_exceeds_total():
    fc = {"type": "FeatureCollection", "features": [_square(-80.825, 35.055), _square(-80.70, 35.30), _square(-80.8251, 35.0551)]}
    e = _engine()
    for m in (10, 1000, 100000):
        env = e.filter(fc, {"within_m_of": {"layer": "any", "m": m}})
        assert env.result.metrics["count_out"] <= env.result.metrics["count_in"] == len(fc["features"])
        assert env.result.metrics["count_out"] == len(env.result.geojson["features"])


def test_find_all_fixture_count_matches_features():
    p = FIX / "find_all.json"
    if not p.exists():
        return
    resp = json.loads(p.read_text())["response"]
    m = resp["result"]["metrics"]
    n = len(resp["result"]["geojson"]["features"]) + resp.get("_fixture", {}).get("truncated_features", 0)
    assert n == m["count_detected"]
