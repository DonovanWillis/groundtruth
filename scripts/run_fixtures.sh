#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")/.."
export GROUNDTRUTH_DEVICE=cpu GROUNDTRUTH_THREADS=6 HF_HUB_OFFLINE=1
nice -n 15 bash scripts/gt.sh python scripts/make_fixtures.py --aoi "${AOI:-south_charlotte}" 2>&1 | grep -vE "HTTP Request|unauthenticated|faiss|AVX2|Loading weights"
