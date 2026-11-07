#!/usr/bin/env bash
# PREPARED, NOT ENABLED. Tailnet-only access to the demo (no Funnel, single port). Run only when Monish decides.
#
# What it does (Windows side, Tailscale on the 'oryn' node):
#   tailscale serve --bg --tcp 8000 tcp://localhost:8000   → http://oryn:8000/ reachable only inside the tailnet
# Undo:
#   tailscale serve --tcp=8000 off
# Check:
#   tailscale serve status
#
# Notes:
# - The API binds 127.0.0.1:8000 inside WSL; Windows forwards localhost to WSL, and `tailscale serve` proxies the
#   tailnet port to that localhost port. Nothing is exposed to the public internet (never use `tailscale funnel`).
# - This changes Tailscale config on the production PC: run it yourself, or tell Claude explicitly to run it.
set -euo pipefail
if [ "${1:-}" != "--i-am-monish-and-approve" ]; then
  echo "Not enabled. Read the header of $0; run with --i-am-monish-and-approve to execute." >&2
  exit 2
fi
powershell.exe -NoProfile -Command "tailscale serve --bg --tcp 8000 tcp://localhost:8000; tailscale serve status"
