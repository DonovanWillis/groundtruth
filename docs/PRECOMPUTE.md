# Full-county precompute: estimate and how to run it

Measured on the UNC Charlotte slice (2026-11-07): 342 chips, NAIP 2022.

| quantity | measured / derived |
|---|---|
| chips per year, whole county (224 px, stride 192, 0.6 m) | **107,770** (54 NAIP scenes; same for 2022 and 2020) |
| embed throughput, this PC, CPU only (Ryzen 7 5700X, 8 threads, `nice`) | **4.4 chips/s** (DINOv2 ViT-B/14 + OpenCLIP ViT-B/16 together) |
| NAIP download | ~470 MB per scene; **~10 MB/s** with 16 parallel ranges from `naipeuwest` (Azure West Europe) → ~45 s per scene, ~42 min per year. Prefetched while the previous scene embeds. |
| remote windowed reads (old approach) | 265 s for a 13 MP window, so we don't use it |
| storage per chip | ~20 KB shard (JPEG thumb ~17 KB + fp16 vectors 2.5 KB) |
| storage per year | ~2.2 GB shards + ~1.8 GB thumbs pack + ~0.55 GB FAISS + ~0.28 GB vectors ≈ **4.8 GB** (+ ≤1 GB temporary COGs, deleted after use) |

## Time per year
| where | embed | download | total per year | both years |
|---|---|---|---|---|
| this PC, CPU | 107,770 / 4.4 ≈ **6.8 h** | overlapped | **≈ 7 h** | ≈ 14 h |
| this PC, CPU, using ORYN's DINOv2 vectors (OpenCLIP only) | ≈ 3.1 h | overlapped | ≈ 3.2 h | ≈ 6.5 h |
| laptop GPU (RTX-class, CUDA) | ~3–6 min (≈300–600 chips/s) | ~42 min on home bandwidth | **≈ 45 min** | ≈ 1.5 h |
| Colab T4 GPU | ~12 min (≈150 chips/s) | likely faster cloud-to-cloud (not measured) | **≈ 20–30 min** | ≈ 1 h |

**Decision:** the CPU estimate (~7 h per year) is well over the 3-hour limit, and this PC is the production machine:
its GPU must not be used, and a 7-hour CPU job would compete with ORYN. So **the precompute was not started here.**
The fastest option is a GPU box: the laptop over SSH, or Colab. On GPU the job is download-bound, so ORYN's DINOv2 vectors
would save only minutes and aren't worth a production DB export or a grid change.

## Run on another machine (CUDA)
```bash
git clone https://github.com/sensordyme-debug/groundtruth && cd groundtruth
python -m venv .venv && source .venv/bin/activate
pip install -e ".[ml]"          # CUDA torch: pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
python scripts/fetch_boundary_naip.py
python scripts/precompute_county.py --aoi county --year 2022 --batch 128    # resumable; re-run to continue
python scripts/precompute_county.py --aoi county --year 2020 --batch 128
# copy back: data/precompute/chips224s192-g0.6-v1/county/<year>/{chips.parquet,dino.*,clip.*,thumbs.*,index.json}
```
The device is picked automatically (cuda → mps → cpu); `GROUNDTRUTH_DEVICE` overrides it. Each scene is one work unit,
written atomically to `shards/<scene>.parquet`. A crashed or interrupted run resumes from the next unfinished scene,
and failed reads are retried 3× with a fresh download.
