#!/usr/bin/env bash
# rsync between this PC (run inside the PC's WSL) and the laptop's ~/groundtruth-heavy over Tailscale.
#   bash scripts/heavy/sync.sh code                      # engine/ scripts/ conf → laptop
#   bash scripts/heavy/sync.sh push <path under repo>    # e.g. data/boundary  → laptop (only what a job needs)
#   bash scripts/heavy/sync.sh pull <path under repo>    # e.g. data/lidar/CLT_Airport → PC
# Transport: Windows OpenSSH (existing key, never printed) to the laptop's Windows side, which starts rsync inside
# its Ubuntu via `wsl`. Never syncs data/labels/ (human test set) or secrets.
set -euo pipefail
cd "$(dirname "$0")/../.."
SSH="/mnt/c/Windows/System32/OpenSSH/ssh.exe -i C:/Users/orynt/.ssh/id_ed25519_oryn -o BatchMode=yes -o ConnectTimeout=20"
REMOTE="ashur@quantcompute"
RPATH="wsl -d Ubuntu-24.04 -- rsync"
DEST="/home/ashur/groundtruth-heavy"
EXCL=(--exclude 'data/labels/' --exclude '.env*' --exclude '*.key' --exclude '__pycache__/' --exclude '.git/')
case "${1:-}" in
  code) rsync -az --delete "${EXCL[@]}" -e "$SSH" --rsync-path="$RPATH" engine scripts "$REMOTE:$DEST/" ;;
  push) rsync -az "${EXCL[@]}" -e "$SSH" --rsync-path="$RPATH" --relative "./$2" "$REMOTE:$DEST/" ;;
  pull) rsync -az "${EXCL[@]}" -e "$SSH" --rsync-path="$RPATH" "$REMOTE:$DEST/$2/" "./$2/" ;;
  *) echo "usage: sync.sh code | push <path> | pull <path>"; exit 2 ;;
esac
echo "sync $1 ${2:-} ok"
