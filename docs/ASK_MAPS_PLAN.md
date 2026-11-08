# Ask Maps implementation plan

Status: implementation started on `codex/ask-maps-foundation` from Donovan's fork. The `demo-final` tag remains the hackathon baseline. This plan records product decisions and acceptance checks for the new experience.

## Product contract

The map remains visible while a right-side Ask panel holds the conversation and a numbered result list. Selecting a card selects and focuses its map feature; selecting a map feature selects its card. The session remembers the current area, ordered results, and selected result. A request for “near me” requires an address chosen by the user or a rectangle the user draws. The app never requests device location.

Follow-ups such as “What does the top option serve?” refer to the first displayed result. Ranking changes the existing result order and map numbers only when a provider supplies the ranking field. Menus, prices, opening hours, and travel times are never inferred from a place name or model output. Missing fields produce a clear unavailable answer with the source and coverage limits.

The LLM is an optional planner and explanation layer. It must emit validated tool plans and cite engine/provider envelopes. Deterministic code executes queries, computes distances and counts, and produces map actions. Mistral is the intended future model; local Qwen is the Mac setup model. The first Ask Maps slice can use explicit, deterministic intents while the model adapter is built.

## Visual direction

Use a restrained warm neutral canvas, ink text, one muted geographic accent, crisp borders, compact controls, and direct map interaction. Keep the right panel usable on desktop and as a bottom panel on narrow screens. Avoid horizontal scrolling. Do not use harsh gradients, Lucide, pure white page backgrounds, rainbow or neon palettes, shadows, three-card rows, emojis, glass effects, em dashes, Inter/Geist/Space Grotesk, colored left stripes, bento grids, checkmark bullets, soft corners, purple with black, skeletons, radial orbs, dot grids, or sparkle icons. Prefer plain CSS and existing map controls over a new component library. A Figma reference can be added later without blocking functional work.

## Delivery sequence

| Stage | Work | Acceptance |
|---|---|---|
| 1. Map and conversation foundation | Persistent map, right Ask panel, responsive bottom panel, explicit address geocoding and drawn rectangle, linked result cards, session state, honest no-data follow-ups | No browser geolocation; no horizontal scroll at desktop/mobile widths; card and map selection agree; “near me” without area requests context; `npm run build`, API and engine tests pass |
| 2. Provider-backed place answers | Search Overture places in selected area, stable IDs/order, distances measured in EPSG:32617, source/coverage display, menu/price provider interface | No fabricated attributes; unavailable data is explicit; results remain stable through follow-ups |
| 3. LLM planner | Mistral-compatible adapter behind validated plan schema; tool allowlist, source-aware response builder, session continuation and tests | Model cannot supply factual metrics absent from envelopes; invalid plans decline safely; deterministic fallback works when model is unavailable |
| 4. Persistence and integration | PostgreSQL/PostGIS schema and migrations for sessions, areas, result references and sourced place metadata; optional Supabase deployment and authentication | Local app works without cloud credentials; server holds secrets; row access and data retention are documented; no imagery/FAISS files in Postgres |
| 5. MCP and 3D | MCP server wrapping existing HTTP tools; optional CesiumJS view with licensed terrain/building sources and synchronized selected feature | MCP observes envelope contract; 2D stays usable; 3D says when height/terrain coverage is missing |
| 6. Hardening | Accessibility, latency, device widths, source and licence review, data quality checks, deployment guide | Automated checks and a human walkthrough pass; unavailable geography and fields are reported clearly |

## Stack decisions from repo audit

Already present: Node/npm tooling, React/TypeScript/Vite, MapLibre, FastAPI, pytest, DuckDB Spatial, GDAL through rasterio, OpenCLIP, DINOv2, Grounding DINO and SAM 2.1. MCP and agent directories currently contain stubs. Supabase, PostgreSQL/PostGIS, Next.js, GeoPandas, YOLO, OpenCV and CesiumJS are absent.

Keep Vite/React for Stage 1 because the existing map and API calls are reusable. Next.js is a possible later deployment choice, not a prerequisite for chat or map interaction. Add PostgreSQL/PostGIS and Supabase when multi-user persistence is implemented. GeoPandas, GDAL CLI, YOLO and OpenCV require a concrete pipeline gap before adoption; rasterio already invokes GDAL and the current detector/outline pipeline serves the imagery use case. CesiumJS belongs behind a separate 3D mode after terrain and height sources are licensed and coverage is known.

## Parallel assignments

- Codex: plan, provider geocoding/API, integration and review.
- UI agent: `web/` only, Stage 1 map and Ask panel.
- Claude Code: `mcp/` and `tests/mcp/` only, HTTP tool wrapper and offline tests, on its own branch/worktree. No ORYN access, secrets, labels, or edits to engine/API/web. Keep all envelopes intact and handle `ok`, `partial`, and `declined`.

Do not merge or deploy before the slice is reviewable. Record actual progress and known gaps rather than checking off stages from intent alone.
