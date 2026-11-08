"""Rules planner: turns a request like "pools within 1 km of I-485 in Ballantyne" into real tool calls + map actions.

Deterministic rules (no LLM): concept (conf/senses.json aliases), place (conf/places.json), distance + layer
("within 1 km of I-485", "near light rail", "in flood zones"), host layer ("on warehouses"), year ("in 2020") and
"new since 2020". Every number in the final `say` cites the step envelope it came from. Map actions follow the
map-action schema (fly_to / show_candidates / add_results / add_layer / set_filter / show_metrics / offer_download / say).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from groundtruth import config
from groundtruth.tools import _people, load_senses

LAYERS = {
    "i-485": "osm_i485", "i485": "osm_i485", "485": "osm_i485",
    "i-77": "osm_i77", "i77": "osm_i77", "i-85": "osm_i85", "i85": "osm_i85",
    "light rail": "osm_light_rail", "lynx": "osm_light_rail", "light-rail": "osm_light_rail",
    "flood zone": "fema_flood_zones", "flood zones": "fema_flood_zones", "floodplain": "fema_flood_zones",
    "flood": "fema_flood_zones",
}
HOSTS = {"warehouse": "osm_warehouses", "warehouses": "osm_warehouses"}
DEFAULT_SENSE = {"swimming_pool": "backyard_pool", "solar_installation": "rooftop_solar_comm",
                 "parking_lot": "surface_lot_full", "warehouse": "distribution_center", "construction_site": "cleared_land"}


@dataclass
class Plan:
    text: str
    concept: str | None = None
    concept_query: str | None = None
    place: str | None = None
    layer: str | None = None
    within_m: float | None = None
    inside_layer: bool = False
    host_layer: str | None = None
    year: int | None = None
    new_since: int | None = None
    notes: list[str] = field(default_factory=list)


def parse(text: str) -> Plan:
    t = " " + re.sub(r"\s+", " ", text.lower().strip()) + " "
    p = Plan(text=text)
    senses = load_senses()
    # concept: longest alias match, ignoring the host phrase ("solar on warehouses" → solar, host = warehouses)
    t_concept = re.sub(r"\bon (warehouses?)\b", " ", t)
    best = None
    for key, entry in senses.items():
        for a in entry["aliases"] + [key.replace("_", " ")]:
            if re.search(rf"\b{re.escape(a)}\b", t_concept) and (best is None or len(a) > len(best[1])):
                best = (key, a)
    if best:
        p.concept, p.concept_query = best[0], best[1]
    places = json.loads((config.SENSES_PATH.parent / "places.json").read_text())["places"]
    for name in sorted(places, key=len, reverse=True):
        if f" {name.lower()} " in t or f" {name.lower()}," in t or t.rstrip().endswith(name.lower()):
            p.place = name
            break
    m = re.search(r"within\s+([\d.]+)\s*(km|kilometers?|m|meters?|metres?|mi|miles?)\s+(?:of|from)\s+([a-z0-9\- ]+?)(?:\s+in\s|\s*$|,)", t)
    if m:
        v, u, what = float(m.group(1)), m.group(2), m.group(3).strip()
        p.within_m = v * (1000 if u.startswith("k") else 1609.34 if u.startswith("mi") else 1)
        p.layer = next((lay for k, lay in LAYERS.items() if k in what), None)
    elif re.search(r"\bnear\b", t):
        p.within_m = 500.0
        p.layer = next((lay for k, lay in LAYERS.items() if k in t), None)
        p.notes.append("'near' read as within 500 m")
    if re.search(r"\bin (a |the )?flood ?(zones?|plain)", t):
        p.layer, p.inside_layer, p.within_m = "fema_flood_zones", True, None
    hm = re.search(r"\bon (warehouses?)\b", t)
    if hm:
        p.host_layer = HOSTS[hm.group(1)]
    ym = re.search(r"\bnew\b.*?\bsince (20\d\d)\b", t)
    if ym:
        p.new_since = int(ym.group(1))
    yy = re.search(r"\bin (20\d\d)\b", t)
    if yy:
        p.year = int(yy.group(1))
    return p


def run(engine_for, text: str) -> dict[str, Any]:
    """engine_for(year) → Engine. Returns {plan, steps:[{ref, tool, envelope}], actions:[...], status}."""
    plan = parse(text)
    steps: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []

    def step(tool: str, env) -> str:
        ref = f"step_{len(steps) + 1}"
        steps.append({"ref": ref, "tool": tool, "envelope": env.model_dump(mode="json")})
        return ref

    if _people(text):
        actions.append({"action": "say", "text": "I can't help with information about people (owners, residents, "
                                                 "demographics, crime or schools). Ask about things visible from above."})
        return {"plan": plan.__dict__, "steps": steps, "actions": actions, "status": "declined",
                "planner": "rules planner (deterministic)"}
    if not plan.concept:
        actions.append({"action": "say", "text": "I didn't recognise what to look for. Try: swimming pools, parking lots, "
                                                 "solar panels, warehouses or construction sites (optionally 'in <place>')."})
        return {"plan": plan.__dict__, "steps": steps, "actions": actions, "status": "declined",
                "planner": "rules planner (deterministic)"}
    eng = engine_for(plan.year)
    places = json.loads((config.SENSES_PATH.parent / "places.json").read_text())["places"]
    if plan.place:
        actions.append({"action": "fly_to", "bbox": places[plan.place]["bbox"], "label": plan.place})
    # 1. pick what you meant: the planner picks the default sense, every other sense is a negative
    pc = eng.pick_candidates(plan.concept_query or plan.concept.replace("_", " "))
    r_pick = step("pick_candidates", pc)
    actions.append({"action": "show_candidates", "envelope_ref": r_pick})
    tiles = [f for f in pc.result.geojson["features"] if not f["properties"].get("no_clear_example")]
    want = DEFAULT_SENSE.get(plan.concept)
    chosen = next((f for f in tiles if f["properties"]["sense_id"] == want), tiles[0] if tiles else None)
    if chosen is None:
        actions.append({"action": "say", "text": f"No clear example of {plan.concept_query} in the index ({r_pick})."})
        return {"plan": plan.__dict__, "steps": steps, "actions": actions, "status": "partial",
                "planner": "rules planner (deterministic)"}
    ex = chosen["properties"]["example"]
    neg = [f["properties"]["example"] for f in tiles if f is not chosen]
    plan.notes.append(f"example: sense '{chosen['properties']['sense_id']}' ({ex}); other senses used as negatives")
    plan_extra = {"chosen_sense": chosen["properties"]["sense_id"], "chosen_example": ex, "negatives": neg}
    # 2. find all (exhaustive in a place; ranked county-wide otherwise)
    fa = eng.find_all([ex], neg, place=plan.place if eng.aoi == "county" else None, concept=plan.concept,
                      within_layer=plan.host_layer)  # "solar on warehouses": scan exactly the chips covering warehouses
    r_fa = step("find_all", fa)
    actions.append({"action": "add_results", "layer_id": "results", "envelope_ref": r_fa})
    current, r_cur = fa.result.geojson, r_fa
    # 3. context / filter layers
    for lay, kind in ((plan.layer, "filter"), (plan.host_layer, "host")):
        if not lay:
            continue
        al = eng.add_layer(lay, places[plan.place]["bbox"] if plan.place else None)
        r_l = step("add_layer", al)
        if al.status != "declined":
            actions.append({"action": "add_layer", "layer_id": lay, "source": "envelope", "envelope_ref": r_l})
        where = ({"intersects_layer": lay} if (kind == "host" or plan.inside_layer)
                 else {"within_m_of": {"layer": lay, "m": plan.within_m or 1000}})
        fl = eng.filter(current, where)
        r_f = step("filter", fl)
        if fl.status != "declined":
            actions.append({"action": "set_filter", "layer_id": "results", "envelope_ref": r_f})
            current, r_cur = fl.result.geojson, r_f
    # 4. new since <year>
    r_cy = None
    if plan.new_since:
        cy = eng.compare_years([f["properties"]["example"] for f in current["features"]][:300], from_year=plan.new_since,
                               concept=plan.concept)
        r_cy = step("compare_years", cy)
    # 5. measure + export
    dist_layers = [plan.layer] if plan.layer and not plan.inside_layer else []
    ms = eng.measure(current, to_layers=dist_layers) if current["features"] else None
    r_ms = step("measure", ms) if ms else None
    if r_ms:
        actions.append({"action": "show_metrics", "envelope_ref": r_ms})
        ex_env = eng.export(current, "csv")
        r_ex = step("export", ex_env)
        actions.append({"action": "offer_download", "envelope_ref": r_ex, "format": "csv"})
    n = len(current["features"])
    what = (plan.concept_query or plan.concept).replace("_", " ")
    scope = (f" in {plan.place}" if plan.place
             else f" on {plan.host_layer.replace('osm_', '')} (every chip touching one scanned)" if plan.host_layer
             else " (county-wide, ranked top results: not an exhaustive count; add 'in <place>' for one)")
    parts = [f"{n} {what} detected{scope} ({r_cur})"]
    if r_ms and ms.status != "declined":
        parts.append(f"{ms.result.metrics.get('area_acres_total')} acres in total ({r_ms})")
    if r_cy:
        cy_env = next(s["envelope"] for s in steps if s["ref"] == r_cy)
        if cy_env["status"] == "declined":
            parts.append(f"'new since {plan.new_since}' isn't available yet: {cy_env['declined_reason']} ({r_cy})")
        else:
            mm = cy_env["result"]["metrics"]
            parts.append(f"{mm.get('new', 0)} new since {plan.new_since}, {mm.get('existing', 0)} existing, "
                         f"{mm.get('unsure', 0)} unsure ({r_cy})")
    if r_ms and dist_layers and ms.status != "declined":
        md = ms.result.metrics.get(f"median_dist_m_to_{plan.layer}")
        if md is not None:
            parts.append(f"median {round(md)} m to {plan.layer.replace('osm_', '').upper()} ({r_ms})")
    actions.append({"action": "say", "text": "; ".join(parts) + "."})
    return {"plan": {**plan.__dict__, **plan_extra}, "steps": steps, "actions": actions, "status": "ok",
            "planner": "rules planner (deterministic)"}
