#!/usr/bin/env bash
# (PC, inside WSL) Sync the code and start laptop job <name> (scripts/heavy/jobs/<name>.sh). The SSH session that keeps
# the laptop distro alive runs detached here (nohup, survives Claude Code's background-shell reaping).
#   bash scripts/heavy/laptop_job.sh lidar_airport
set -euo pipefail
cd "$(dirname "$0")/../.."
name="$1"
bash scripts/heavy/sync.sh code >/dev/null
mkdir -p data/logs
nohup setsid /mnt/c/Windows/System32/OpenSSH/ssh.exe -i C:/Users/orynt/.ssh/id_ed25519_oryn -o BatchMode=yes \
  -o ConnectTimeout=20 -o ServerAliveInterval=30 -o ServerAliveCountMax=10 ashur@quantcompute \
  "wsl -d Ubuntu-24.04 -- bash -l /home/ashur/groundtruth-heavy/scripts/heavy/run_job.sh $name" \
  > "data/logs/laptop_$name.session.log" 2>&1 < /dev/null &
echo "laptop job $name: session pid $!"
