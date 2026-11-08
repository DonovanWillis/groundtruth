# Worldwide location search contract

Status: agreed interface for the next Ask Maps increment. This is a coordination document, not a claim that worldwide search already works.

## Two kinds of coverage

1. **Navigation coverage:** a user can enter a town, named place, or address and move the map to a returned location anywhere a configured geocoder covers. The map uses a global vector basemap with attribution. Selecting a result never reads device location.
2. **Analysis coverage:** aerial imagery search, building/restaurant extraction, measurements, and other Groundtruth tools run only where their data provider has indexed data. Today that is the Mecklenburg County development slice on this Mac. The UI must display this distinction and decline unsupported analyses outside coverage rather than showing an empty result as if no places exist.

The current `GET /api/v1/geocode` is a county-only, user-submitted Nominatim lookup for development. It is not a worldwide search service. The public Nominatim policy limits traffic to one request per second, disallows client autocomplete, and is unsuitable as the backend of a general map-search product. Worldwide lookup must use a switchable production geocoder: a properly hosted Nominatim instance or a licensed geocoding provider. Its API key, if any, stays server-side. The application must not send confidential address text to a public service without an appropriate privacy decision.

## Proposed stable API

`GET /api/v1/location/search?q=<finalized text>&limit=5`:

```json
{
  "query": "Charlotte, NC",
  "candidates": [
    {
      "id": "provider-specific-stable-id",
      "label": "Charlotte, North Carolina, United States",
      "kind": "town",
      "center": [-80.8431, 35.2271],
      "bbox": [-80.99, 35.10, -80.67, 35.39],
      "source": {"name": "configured geocoder", "url": "https://example.org", "licence": "provider terms"}
    }
  ],
  "coverage": {"navigation": "provider coverage", "analysis": "Mecklenburg County only"}
}
```

The coordinates in this example illustrate the shape; providers supply actual values. Validate coordinate ranges and bbox ordering. Return multiple candidates for ambiguous names; the user selects one. Keep navigation separate from a search intent such as “restaurants near here.” Do not imply that geocoding a town also downloaded its restaurants, aerial imagery, menus, or prices.

`GET /api/v1/coverage?bbox=w,s,e,n` reports which analysis products are ready in that area and their years, sources, and limits. A location outside coverage can still be displayed on the map. `find_place` remains tied to its Overture extract until a global place index is built or a licensed place provider is configured.

## Data path to worldwide Ask Maps

- **Map:** MapLibre with a worldwide vector basemap, such as OpenFreeMap for the prototype or a self-hosted Protomaps build for production. Retain USDA NAIP as a separate overlay only where available. Preserve map-data attribution.
- **Geocoder:** provider interface for town/address search. A hosted provider can make the first worldwide navigation release practical; a self-hosted service is an option for later scale and control. Do not build autocomplete on the public Nominatim endpoint.
- **Places:** Overture Places has global coverage but incomplete and duplicate records. Index bounded extracts by region in PostgreSQL/PostGIS or another spatial store, with stable IDs and per-record source/licence. Do not query the entire planet parquet on every user request.
- **Addresses:** Overture's address theme is currently alpha with partial coverage, so it cannot guarantee every street address. The geocoder must expose its actual coverage and return no-match honestly.
- **Analysis:** add region data and imagery indexes deliberately, one licensed region at a time. A global basemap is not global Groundtruth computer vision coverage.

## Acceptance for the coordinated increment

- Search for an unambiguous town outside North Carolina, select it, and see the map fly there on a global basemap.
- Search for a Mecklenburg address and use it as explicit search context.
- Searching “restaurants near here” outside analysis coverage produces a coverage explanation, not a false zero-results answer.
- No device geolocation request, no Google tiles/data, no public Nominatim autocomplete, no invented menu or price.
- Desktop and mobile layouts have no horizontal overflow; map and search results remain keyboard accessible.

## Source and policy references

- [OSM Foundation Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/)
- [Overture Places coverage and quality](https://docs.overturemaps.org/guides/places/)
- [Overture Divisions for cities and towns](https://docs.overturemaps.org/guides/divisions/)
- [Overture Addresses coverage](https://docs.overturemaps.org/guides/addresses/)
- [OpenFreeMap MapLibre quick start](https://openfreemap.org/quick_start/)
- [Protomaps basemap downloads and self-hosting guidance](https://docs.protomaps.com/basemaps/downloads)
