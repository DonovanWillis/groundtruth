# Groundtruth — conversation handoff

Updated November 8, 2026. This document captures Donovan's product decisions and current task scope from the Codex conversation. It is a curated handoff, not a full chat transcript. Read this alongside `AGENTS.md`, `CLAUDE.md`, and `docs/CONTRACT.md`.

## Product goal

Donovan Willis and Monish are building Groundtruth, a geospatial search engine for Mecklenburg County, NC. Its engine searches public aerial imagery and geographic layers and returns map features and measurements in a versioned envelope. The engine will later be integrated into Monish's ORYN geospatial intelligence platform.

The intended experience is an interactive “Ask Maps” assistant in ORYN's right tab:

- A user enters an address or draws an area by clicking and dragging.
- A question returns option cards in the right tab and linked markers or outlines on the map.
- Clicking a card selects its map feature; clicking a map feature selects its card.
- The conversation retains the displayed result set, its order, the selected option, and the chosen search area so follow-up questions refer to the same results.

Example: “Find food near here” produces restaurant cards and map markers. “What food does the top option have?” refers to the first card and fetches available menu details. “Rank them by price” reorders that same result set and map numbers using sourced price data. Missing menu or price information must be stated plainly, never invented.

Location is supplied explicitly by the user. Do not automatically determine device location. If the user says “near me” without an address or drawn area, ask them to provide one.

The six-example “pick what you meant” flow is no longer the central product direction. `demo-final` and older demo documentation preserve the hackathon baseline. They do not supersede this future product direction.

## Model and architecture decisions

Mistral is the intended LLM for the future Ask ORYN experience. Local Qwen3-4B is part of reproducing the Mac development setup; it does not settle the future product model choice.

The LLM plans tool calls and explains sourced results. Deterministic geospatial tools perform searches, filtering, measurement, and map actions. Counts, distances, prices, dates, menus, and confidence must come from providers or engine results.

Keep integrations pluggable through `DataProvider`. Preserve source, licence, coverage, and limitations in answers. Keep the existing versioned tool envelope and typed, tested engine. GeoJSON uses EPSG:4326; measurements use EPSG:32617 with units in field names.

## Current authorized task: Mac setup only

Do not start the Ask ORYN feature implementation as part of this setup task.

- Fork: https://github.com/DonovanWillis/groundtruth
- Local clone used for this task: `/Users/donov/dev/groundtruth` (`~/dev/groundtruth`). A separate `/Users/donov/groundtruth` directory also exists; do not assume it is this clone.
- Branch: `DonovanWillis/setup`, created from `demo-final`.
- `origin` is Donovan's fork; `upstream` is `sensordyme-debug/groundtruth`.
- Keep changes on the setup branch. Do not push to upstream main.
- No Monish devpack is available yet. Build a small public-data development slice.
- Do not read, call, or copy ORYN during this task.
- Do not use Google data or tiles, data about people, or non-commercial/GPL/AGPL dependencies.
- Never write `data/labels/`. Never print or commit API keys or tokens.
- Keep heavy data and model weights outside the repo.

Setup work includes the Python/Node toolchain, Apple Silicon model compatibility, a Ballantyne development slice, local Qwen via llama.cpp Metal, API/UI checks, a reproducible Mac handbook, and a draft PR for review. Setup does not imply that the full county demo or the future conversational product is complete.

## Observed setup status at handoff

These are observations from the current Mac, not guarantees for a fresh checkout:

- Apple Silicon Mac with 16 GB RAM; root `.venv` uses Python 3.12.13.
- Python imports and the existing test suite passed: 31 tests.
- DINOv2, OpenCLIP, SAM 2.1 tiny, and Grounding DINO tiny loaded on MPS. OpenCLIP image inference succeeded.
- A 2022 Ballantyne index with 1,320 chips was built at `~/dev/groundtruth-data/precompute/chips224s192-g0.6-v3c8p192/ballantyne/2022`.
- Data root: `~/dev/groundtruth-data`. NAIP scene cache: `~/.cache/groundtruth/naip/2022`. Local configuration is in ignored `.env.local`.
- Qwen3-4B Q4_K_M resides in `~/dev/groundtruth-models/`; llama.cpp tag `b12202` was built in `~/dev/llama.cpp` with Metal. A local chat completion succeeded at `127.0.0.1:8081`.
- API health at `127.0.0.1:8000/api/v1/health` reported `ok: true`, 1,320 chips, and no warm-up error on November 8 at 03:53 EST. The Vite UI responded at `127.0.0.1:5173`.
- Torch, FAISS, and scikit-learn initially caused a duplicate OpenMP runtime crash. In this local `.venv`, FAISS and scikit-learn's bundled `libomp.dylib` files were backed up and replaced by relative symlinks to Torch's copy. The API then completed warm-up. Package reinstalls may undo this environment change; document and validate a reproducible fix before claiming setup is complete. Do not use `KMP_DUPLICATE_LIB_OK` to hide the conflict.

Still pending: finish and verify public layers, run the slice-appropriate demo chain, finish the Mac/LLM setup guides, review and commit setup changes, and open the draft PR. Full county coverage, 2020 comparison, routing, lidar, and the future Ask ORYN experience have not been validated on this Mac.

There are setup edits in the working tree and a separate untracked `.claude-flow/` directory. Inspect current Git state before working; do not overwrite another agent's changes or commit its files indiscriminately. Running service status may change after this handoff.

## Prompt for another coding agent

> Work in `~/dev/groundtruth` on `DonovanWillis/setup`. Read `docs/CONVERSATION_CONTEXT.md`, `AGENTS.md`, `CLAUDE.md`, and `docs/CONTRACT.md` before making changes. The active task is Mac setup only; the future product goal is the Ask Maps-style experience described in the context document. Inspect current Git state and coordinate with any active agent before editing the same files. Preserve unrelated edits and report verified results and remaining limitations honestly.
