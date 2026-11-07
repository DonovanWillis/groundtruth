"""Hero-flow check against the running API, with timings and pass/fail against the latency budget.

  python scripts/demo_check.py [--base http://127.0.0.1:8000] [--place Ballantyne] [--record]
Flow: pick "swimming pool" → pick backyard pool → find_all in <place> → refine ×3 → filter within 1 km of I-485 →
export CSV → new since 2020. Budgets: pick < 2 s, first results (find_all) < 3 s, refine < 1 s.
--record saves every response to data/replay/hero/<n>_<tool>.json for the replay fallback.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BUDGET_MS = {"pick_candidates": 2000, "find_all": 3000, "refine": 1000}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--place", default="Ballantyne")
    ap.add_argument("--record", action="store_true")
    a = ap.parse_args()
    c = httpx.Client(base_url=a.base, timeout=180)
    h = c.get("/api/v1/health").json()
    idx = [i for i in h["indexes"] if i["year"] == h["primary_year"]]
    aoi = "county" if any(i["aoi"] == "county" for i in idx) else max(idx, key=lambda i: i["chips"])["aoi"]
    place = a.place if aoi == "county" else None
    rows, ok_all, n = [], True, 0
    rec = ROOT / "data" / "replay" / "hero"
    if a.record:
        rec.mkdir(parents=True, exist_ok=True)

    def call(tool: str, body: dict) -> dict:
        nonlocal ok_all, n
        n += 1
        t0 = time.perf_counter()
        r = c.post(f"/api/v1/tools/{tool}", json={"aoi": aoi, **body})
        ms = (time.perf_counter() - t0) * 1000
        env = r.json()
        good = r.status_code == 200 and env.get("status") in ("ok", "partial")
        if tool == "compare_years" and env.get("status") == "declined" and "index" in (env.get("declined_reason") or ""):
            print(f"{n:2d} {tool:16s} SKIP  ({env['declined_reason']})")
            rows.append({"step": n, "tool": tool, "ms": 0, "status": "skipped", "budget_ms": None, "within_budget": True,
                         "metrics": {"reason": env["declined_reason"]}})
            return env
        budget = BUDGET_MS.get(tool)
        within = budget is None or ms <= budget
        ok_all &= good
        rows.append({"step": n, "tool": tool, "ms": round(ms), "status": env.get("status"), "budget_ms": budget,
                     "within_budget": within, "metrics": {k: v for k, v in (env.get("result") or {}).get("metrics", {}).items()
                                                          if not isinstance(v, (list, dict)) and k != "content"}})
        print(f"{n:2d} {tool:16s} {'PASS' if good else 'FAIL'} {ms:7.0f} ms"
              + (f"  budget {budget} ms {'✓' if within else '✗ OVER'}" if budget else "")
              + f"  {json.dumps(rows[-1]['metrics'])[:150]}")
        if a.record:
            (rec / f"{n:02d}_{tool}.json").write_text(json.dumps({"request": body, "response": env}))
        return env

    print(f"hero flow on aoi={aoi} place={place} ({datetime.now().strftime('%H:%M:%S')})")
    pc = call("pick_candidates", {"query": "swimming pool"})
    feats = pc["result"]["geojson"]["features"]
    pick = next((f for f in feats if f["properties"].get("sense_id") == "backyard_pool"), feats[0])
    ex, concept = pick["properties"]["example"], pc["result"]["metrics"].get("sense_list")
    body = {"examples": [ex], "concept": concept, "k": 200, "outline_top": 200}
    if place:
        body["place"] = place
    fa = call("find_all", body)
    hits = fa["result"]["geojson"]["features"]
    sid = None
    for k in range(3):
        acc = [ex] if sid is None else []
        acc.append(hits[k]["properties"]["example"])
        rej = [hits[-1 - k]["properties"]["example"]]
        rf = call("refine", {"session_id": sid, "accept": acc, "reject": rej, "k": 200, "concept": concept,
                             **({"place": place} if place else {})})
        sid = rf["result"]["metrics"].get("session_id")
    res = rf["result"]["geojson"]
    flt = call("filter", {"geojson": res, "where": {"within_m_of": {"layer": "osm_i485", "m": 1000}}})
    call("export", {"geojson": flt["result"]["geojson"], "format": "csv"})
    exs = [f["properties"].get("example") or f"{f['properties']['chip_id']}#{f['properties']['cell']}"
           for f in flt["result"]["geojson"]["features"]][:100]
    if exs:
        call("compare_years", {"examples": exs, "from_year": 2020, "concept": concept})
    slow = [r for r in rows if not r["within_budget"]]
    print(f"RESULT: {'PASS' if ok_all else 'FAIL'}; over budget: {[(r['tool'], r['ms']) for r in slow] or 'none'}")
    out = ROOT / "data" / "out" / f"demo_check_{datetime.now().strftime('%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"aoi": aoi, "place": place, "rows": rows, "pass": ok_all}, indent=1))
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
