# Architecture

```
            ┌──────────── web/ (thin demo) ────────────┐     ┌── web/label (labelling page) ──┐
            │ Vite + React + TS + MapLibre GL           │     │ static HTML + MapLibre         │
            └───────────────┬───────────────────────────┘     └──────────────┬─────────────────┘
                            │ JSON envelopes                                 │
            ┌───────────────▼──────────────┐                 ┌───────────────▼────────────────┐
            │ api/app.py (FastAPI, :8000)  │                 │ api/label_server.py (:8765)    │
            │ one route per engine tool    │                 │ long-lived, never auto-reloads │
            └───────────────┬──────────────┘                 └───────────────┬────────────────┘
                            │                                                │
   ┌────────────────────────▼─────────────── engine/groundtruth ─────────────▼─────────────────┐
   │ tools: search_text · pick_candidates · find_similar · outline · refine · add_layer ·       │
   │        filter · measure · export          → every tool returns envelope.Envelope           │
   │ tiler (chips) · embed (DINOv2, OpenCLIP) · index (FAISS cosine) · geo (4326↔32617)          │
   │ labels.LabelStore (journal + atomic snapshot + backups)                                    │
   │                 ▲ all data access through                                                  │
   │ providers.base.DataProvider ── PublicDataProvider (Census, NAIP/PC, OSM, FEMA, Overture)    │
   │                             └─ (later) OrynDataProvider                                    │
   └───────────────────────────────────────────────────────────────────────────────────────────┘
```

## Principles
- **Engine = product.** API and UI are adapters. The engine has no web framework imports.
- **Providers isolate I/O.** Engine logic receives a `DataProvider`; tests use a fake provider.
- **Envelope everywhere** (`docs/CONTRACT.md`) so the UI and the future agent consume one shape.
- **Precompute once, query fast.** Chips + embeddings + FAISS indices are built offline
  (`scripts/precompute_county.py`); queries are vector lookups (milliseconds).
- **Deterministic & versioned.** Seeds fixed, ties broken by `chip_id`, each tool and index carries a version.

## Data flow (search)
1. Tiler cuts the county into 224×224 px chips at 0.6 m (≈134 m) with overlap; each chip records
   `chip_id, bbox, year, scene_id`.
2. `embed` computes DINOv2 (image↔image) and OpenCLIP (text↔image) vectors, L2-normalised.
3. FAISS inner-product index per embedding type (= cosine).
4. `search_text` embeds the query with the CLIP text tower → top-k chips.
5. `pick_candidates` clusters the top 200 into 6 groups (k-means on DINOv2 vectors), one representative each,
   so the user can say which meaning they intended.
6. `find_similar` uses DINOv2: mean(positives) − λ·mean(negatives) → top-k, excluding already-judged chips.
