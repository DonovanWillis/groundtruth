#!/usr/bin/env bash
# (laptop) Run scripts/heavy/jobs/<name>.sh detached, then wait on it so this wsl.exe session keeps the distro alive
# (WSL stops the distro when its last wsl.exe client exits; .wslconfig stays untouched). Log: data/logs/<name>.log
name="$1"
cd ~/groundtruth-heavy && mkdir -p data/logs
if pgrep -f "jobs/$name.sh" >/dev/null; then echo "already running: $name"; else
  nohup setsid bash "scripts/heavy/jobs/$name.sh" > "data/logs/$name.log" 2>&1 < /dev/null &
  echo "started $name pid $!"
fi
while pgrep -f "jobs/$name.sh" >/dev/null; do sleep 30; done
echo "finished $name: $(tail -1 data/logs/$name.log)"
