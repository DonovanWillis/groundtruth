"""The first conversational result is the nearest sourced place, not an arbitrary ID."""

from groundtruth.envelope import Source
from groundtruth.tools import Engine


def test_find_place_nearest_first_and_stable(monkeypatch):
    def feature(name, ident, lon):
        return {"type": "Feature", "id": ident, "geometry": {"type": "Point", "coordinates": [lon, 35.05]},
                "properties": {"id": ident, "name": name, "category": "restaurant", "confidence": .9,
                               "source_dataset": "test"}}

    class Store:
        def places(self, bbox, categories=(), name=None, limit=None, taxonomy=()):
            assert limit is None  # sort all matches before limiting the response
            return {"type": "FeatureCollection", "features": [
                feature("far", "a", -80.86), feature("near-b", "b", -80.849),
                feature("near-a", "c", -80.850)]}, 1.0

    class Provider:
        name = "fake"

        def overture_source(self, kind):
            return Source(name="Overture test", url="https://example.org", date="2026-01-01", licence="test")

        def sources(self):
            return []

    monkeypatch.setattr("groundtruth.vector.store", lambda: Store())
    engine = Engine.__new__(Engine)
    engine.provider, engine.year, engine.aoi = Provider(), 2022, "county"
    result = engine.find_place("restaurants", bbox=[-80.87, 35.04, -80.84, 35.06], limit=2,
                               origin=[-80.85, 35.05])
    features = result.result.geojson["features"]
    assert [f["properties"]["name"] for f in features] == ["near-a", "near-b"]
    assert features[0]["properties"]["dist_m"] == 0
    assert features[1]["properties"]["dist_m"] > 0
    assert result.result.metrics["truncated"] is True
    assert result.result.metrics["sort"] == "distance_m_ascending"
