# Sources and licences

Every dataset and model Groundtruth uses. One-line summary per item for sign-off:
**Commercial use OK? · Attribution required?**

## Datasets

| dataset | link | retrieved | licence | commercial OK? | attribution? | notes |
|---|---|---|---|---|---|---|
| Mecklenburg County boundary (Census TIGERweb State_County, GEOID 37119) | https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1 | 2026-11-07 | US Government work, public domain | Yes | No (courtesy credit "US Census Bureau") | `data/boundary/mecklenburg.geojson`, 1,413.18 km² |
| USDA NAIP imagery (collection `naip`) via Microsoft Planetary Computer STAC | https://planetarycomputer.microsoft.com/dataset/naip | 2026-11-07 | Public domain (USDA FSA). Planetary Computer [Terms of Use](https://planetarycomputer.microsoft.com/terms) apply to the hosting/API | Yes | No (courtesy credit "USDA NAIP") | Full-county years: 2022, 2020, 2018, 2016, 2014, 2012. Primary **2022** (0.6 m, 2022-06-02…2022-09-27), secondary **2020** (0.6 m, 2020-07-11…2020-07-12) |
| NAIP display tiles: Planetary Computer data API (TiTiler-pgstac mosaic) | https://planetarycomputer.microsoft.com/api/data/v1 | 2026-11-07 | Imagery public domain; service under PC Terms of Use | Yes (imagery) | No | Proxied + cached by the labelling server (`data/cache/tiles`) |
| Place search: OpenStreetMap Nominatim | https://nominatim.openstreetmap.org | 2026-11-07 | Data © OpenStreetMap contributors, ODbL 1.0; service under the [Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/) (≤1 req/s, identifying UA, caching) | Yes | **Yes** ("© OpenStreetMap contributors") | Used only to jump the map; results cached in `data/cache/geocode.json` |

## Software (runtime dependencies)

| package | licence |
|---|---|
| FastAPI, Uvicorn, Pydantic, httpx | MIT / BSD-3 |
| NumPy, Shapely, pyproj, Pillow | BSD-3 / BSD-3 / MIT / MIT-CMU (HPND) |
| rasterio | BSD-3 |
| pystac-client, planetary-computer | Apache-2.0 / MIT |
| MapLibre GL JS 4.7.1 | BSD-3 |

## Models

_To be filled in Step 4 (DINOv2, OpenCLIP; RemoteCLIP / GeoRSCLIP licence check)._
