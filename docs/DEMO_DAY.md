# Demo day (one page)

The demo runs on this PC (`oryn`): API + UI on `127.0.0.1:8000` inside WSL, the label server on 8765 (not needed).
Code + data are frozen at the `demo-final` tag (`data/DEMO_MANIFEST.json`).

## Before you leave home
1. `wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/orynt/GeoSpatial/Geospatial-SearchEngine && bash scripts/rollback_demo.sh"`
   → checks out demo-final, pins its data versions, restarts with the full warm-up (~6 min), runs demo_check.
   It must end with `RESULT: PASS`.
2. Leave the PC on, awake, and on the tailnet.

## Enable access from the presenting laptop (tailnet only, one port, no Funnel)
1. On this PC: `bash scripts/tailnet_serve.sh on --i-am-monish-and-approve`  (inside WSL, repo root)
2. `bash scripts/tailnet_serve.sh status` shows `tcp:8000 → localhost:8000`.
3. On the presenting laptop (logged into the same tailnet): open **http://oryn:8000/** in the browser.
   - Test: the landing page loads, the imagery shows, click "find swimming pools", then type the chain below.
   - If `oryn` doesn't resolve, use the PC's tailnet IP: **http://100.116.119.48:8000/**.

## The chain to type (each < 2 s warm)
"find swimming pools" → pick *Backyard pool* → choose *Ballantyne* → Find all (dense) → ✓/✗ three results →
"pools within 1 km of I-485" → "houses within 10 minutes of Ardrey Kell High School" → "buildings taller than 30 m in
Uptown" → "boat docks on Lake Norman" → "new pools since 2020 in Ballantyne" → "export them as CSV" →
"who owns these pools" (declined, on purpose).

## Disable afterwards
`bash scripts/tailnet_serve.sh off --i-am-monish-and-approve`, then `bash scripts/tailnet_serve.sh status` (empty).

## Fallbacks
- **Network trouble:** present on this PC itself: open http://localhost:8000/ in its browser (no tailnet needed).
- **Planetary Computer down / no internet:** the imagery is local (NAIP 2022 county + 2020 for the 8 places). Restart
  with `GROUNDTRUTH_OFFLINE=1 bash scripts/restart_and_warm.sh` to block every outbound imagery fetch.
- **Something broke:** `bash scripts/rollback_demo.sh` (above). Last resort: restart with `GROUNDTRUTH_REPLAY=1`
  (recorded responses, marked `[REPLAY]` in the UI work log).
- **Never** run `tailscale funnel`.
