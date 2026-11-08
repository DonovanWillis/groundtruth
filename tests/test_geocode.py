"""Address lookup stays provider-owned and only returns locations in the service county."""

import asyncio

from groundtruth.providers.public import PublicDataProvider


def test_public_geocode_filters_county_and_caches(tmp_path, monkeypatch):
    boundary = tmp_path / "boundary"
    boundary.mkdir()
    (boundary / "mecklenburg.geojson").write_text(
        '{"type":"Feature","geometry":{"type":"Polygon","coordinates":'
        '[[[-81,35],[-80,35],[-80,36],[-81,36],[-81,35]]]},"properties":{}}')
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return [
                {"display_name": "Chosen address", "lon": "-80.8", "lat": "35.2",
                 "boundingbox": ["35.199", "35.201", "-80.801", "-80.799"]},
                {"display_name": "Outside county", "lon": "-79", "lat": "35.2",
                 "boundingbox": ["35.199", "35.201", "-79.001", "-78.999"]},
            ]

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params):
            calls.append((url, params))
            return Response()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    provider = PublicDataProvider(tmp_path)
    result = asyncio.run(provider.geocode("  Chosen address  "))
    again = asyncio.run(provider.geocode("chosen ADDRESS"))
    assert result == again
    assert len(result) == 1
    assert result[0]["center"] == [-80.8, 35.2]
    assert result[0]["bbox"] == [-80.801, 35.199, -80.799, 35.201]
    assert len(calls) == 1
    assert (tmp_path / "cache" / "ask_geocode.json").exists()
