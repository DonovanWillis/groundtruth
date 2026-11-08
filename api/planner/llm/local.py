"""Local LLM adapter (OpenAI-compatible llama-server on the laptop, reached through the SSH tunnel).

Chat brain = policy → plan → execute → reply:
  1. policy (declines BEFORE any model call: people data never reaches the model)
  2. plan: the LLM fills the SAME plan schema as the rules planner, with JSON-schema-constrained decoding (closed
     enums for places, concepts, layers, categories) → validated → on timeout / error / invalid: the rules plan
  3. execute: the deterministic executor (groundtruth.planner) runs real tools on the plan
  4. reply: one or two sentences; the NUMBER GUARD drops it for the template reply unless every number in it appears
     in the step envelopes
Config (env): LOCAL_LLM_URL (default http://127.0.0.1:8081/v1), LOCAL_LLM_PLAN_TIMEOUT_S (4), LOCAL_LLM_REPLY_TIMEOUT_S (3).
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import httpx

from groundtruth import config
from groundtruth.planner import HOSTS, LAYERS, Plan, load_senses

URL = os.environ.get("LOCAL_LLM_URL", "http://127.0.0.1:8081/v1")
PLAN_TIMEOUT = float(os.environ.get("LOCAL_LLM_PLAN_TIMEOUT_S", "4"))
REPLY_TIMEOUT = float(os.environ.get("LOCAL_LLM_REPLY_TIMEOUT_S", "3"))
BRAIN = "local LLM (Qwen3-4B, llama.cpp)"


def _enums() -> dict[str, list]:
    places = list(json.loads((config.SENSES_PATH.parent / "places.json").read_text())["places"])
    pc = json.loads((config.SENSES_PATH.parent / "places_categories.json").read_text())
    return {"places": places, "concepts": sorted(load_senses()), "layers": sorted(set(LAYERS.values())),
            "hosts": sorted(set(HOSTS.values())), "categories": sorted(pc["categories"]), "buildings": sorted(pc["buildings"])}


def plan_schema() -> dict[str, Any]:
    e = _enums()
    nul = lambda s: {"anyOf": [s, {"type": "null"}]}  # noqa: E731
    return {"type": "object", "additionalProperties": False,
            "required": ["target_kind", "target", "place", "layer", "within_m", "inside_layer", "host_layer", "minutes",
                         "mode", "origin", "min_height_m", "new_since", "require", "sort", "docks_new_since", "follow_up"],
            "properties": {
                "target_kind": nul({"enum": ["concept", "place_category", "buildings", "open", "derived", "canopy"]}),
                "target": nul({"type": "string", "maxLength": 60}),
                "place": nul({"enum": e["places"]}),
                "layer": nul({"enum": e["layers"]}),
                "within_m": nul({"type": "number", "minimum": 1, "maximum": 20000}),
                "inside_layer": {"type": "boolean"},
                "host_layer": nul({"enum": e["hosts"]}),
                "minutes": nul({"type": "number", "minimum": 1, "maximum": 60}),
                "mode": nul({"enum": ["drive", "walk", "bike"]}),
                "origin": nul({"type": "string", "maxLength": 80}),
                "min_height_m": nul({"type": "number", "minimum": 1, "maximum": 400}),
                "new_since": nul({"enum": [2012, 2014, 2016, 2018, 2020]}),
                "require": {"type": "array", "items": {"enum": ["lakefront", "has_dock"]}, "maxItems": 2},
                "sort": nul({"enum": ["pool_area"]}),
                "docks_new_since": nul({"enum": [2020]}),
                "follow_up": {"type": "boolean"}}}


SYSTEM = (
    "You turn a map request about Mecklenburg County, NC into a JSON plan. Output ONLY the JSON object.\n"
    "target_kind: concept (one of the configured concepts, target = its key), derived (target house_with_pool: "
    "'houses with pools'), place_category (target = a category key), buildings (target = a building kind), canopy "
    "(tree height), open (anything else visible from above; target = the thing, plural as typed).\n"
    "follow_up=true when the message only adds a place or a condition to the previous request (given as PREVIOUS); "
    "then copy the previous target and add the new fields.\n"
    "Fields not mentioned are null (require: []). 'near <layer>' = within_m 500. 'in flood zones' = layer "
    "fema_flood_zones, inside_layer true. 'within N minutes of X' = minutes, mode (drive default), origin X. "
    "'lake and dock access' = require [lakefront, has_dock]. 'biggest' = sort pool_area. 'docks added since 2020' = "
    "docks_new_since 2020 and require [lakefront, has_dock].\n"
    "Concepts: {concepts}. Places: {places}. Layers: {layers}. Categories: {categories}. Building kinds: {buildings}."
)


def _system() -> str:
    e = _enums()
    return SYSTEM.format(**{k: ", ".join(map(str, v)) for k, v in e.items() if k != "hosts"})


def _post(path: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
    with httpx.Client(timeout=timeout) as c:
        r = c.post(f"{URL}{path}", json=body)
        r.raise_for_status()
        return r.json()


def health(timeout: float = 2.0) -> bool:
    try:
        with httpx.Client(timeout=timeout) as c:
            return c.get(URL.rsplit("/v1", 1)[0] + "/health").status_code == 200
    except Exception:
        return False


THINK_RE = re.compile(r"<think>|</think>", re.I)


def llm_plan(text: str, previous: str | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """→ (plan dict or None, info {ms, error, think_leak}). Constrained to the plan schema."""
    t0 = time.perf_counter()
    user = (f"PREVIOUS: {previous}\n" if previous else "") + f"REQUEST: {text}"
    info: dict[str, Any] = {"brain": BRAIN}
    try:
        r = _post("/chat/completions", {
            "messages": [{"role": "system", "content": _system()}, {"role": "user", "content": user}],
            "temperature": 0, "max_tokens": 512, "cache_prompt": True,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_schema", "json_schema": {"name": "plan", "strict": True,
                                                                         "schema": plan_schema()}}}, PLAN_TIMEOUT)
        content = r["choices"][0]["message"].get("content") or ""
        info["think_leak"] = bool(THINK_RE.search(content)) or bool(r["choices"][0]["message"].get("reasoning_content"))
        plan = json.loads(content)
        info["valid"] = validate(plan)
        info["usage"] = r.get("usage")
        if not info["valid"]:
            plan = None
    except Exception as e:  # timeout, tunnel down, server error, bad JSON → rules
        plan, info["error"] = None, f"{type(e).__name__}: {str(e)[:120]}"
    info["ms"] = round((time.perf_counter() - t0) * 1000)
    return plan, info


def validate(plan: dict[str, Any]) -> bool:
    """Schema check (keys, enums, types) + semantic checks the grammar can't express."""
    s = plan_schema()
    if set(plan) != set(s["properties"]):
        return False
    e = _enums()
    tk, tg = plan.get("target_kind"), plan.get("target")
    if tk == "concept" and tg not in e["concepts"]:
        return False
    if tk == "place_category" and tg not in e["categories"]:
        return False
    if tk == "buildings" and tg not in e["buildings"]:
        return False
    if tk == "derived" and tg != "house_with_pool":
        return False
    if tk in ("open", "concept", "place_category", "buildings", "derived") and not tg:
        return False
    if plan.get("minutes") and not plan.get("origin"):
        return False
    return True


def to_plan(d: dict[str, Any], text: str) -> Plan:
    """The executor's Plan from a validated LLM plan (same fields as the rules planner)."""
    p = Plan(text=text)
    for k in ("target_kind", "target", "place", "layer", "within_m", "inside_layer", "host_layer", "minutes", "mode",
              "origin", "min_height_m", "new_since", "sort", "docks_new_since"):
        setattr(p, k, d.get(k))
    p.require = list(d.get("require") or [])
    p.inside_layer = bool(d.get("inside_layer"))
    if p.target_kind == "concept":
        p.concept, p.concept_query = p.target, p.target.replace("_", " ")
    if p.target_kind == "derived":
        p.concept, p.concept_query = "swimming_pool", "pools"
    if p.target_kind == "place_category" and p.layer and not p.within_m and not p.inside_layer:
        p.within_m = 500.0
    return p


NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(s: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in NUM_RE.findall(s)}


def llm_reply(template: str, steps: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    """Rewrite the template answer as 1–2 calm sentences. NUMBER GUARD: every number in the reply must appear in the
    template or the step envelopes' metrics, else the template is used."""
    t0 = time.perf_counter()
    info: dict[str, Any] = {}
    allowed = _numbers(template)
    for s in steps:
        allowed |= _numbers(json.dumps((s.get("envelope", {}).get("result") or {}).get("metrics", {})))
    try:
        r = _post("/chat/completions", {
            "messages": [{"role": "system", "content": "Rewrite the map result below as one or two short, plain sentences "
                                                       "for the user. Keep every number exactly. No step references, no "
                                                       "lists, no markdown, no new facts."},
                         {"role": "user", "content": re.sub(r"\s*\(step_\d+\)", "", template)}],
            "temperature": 0.3, "max_tokens": 160, "cache_prompt": True,
            "chat_template_kwargs": {"enable_thinking": False}}, REPLY_TIMEOUT)
        out = (r["choices"][0]["message"].get("content") or "").strip()
        info["think_leak"] = bool(THINK_RE.search(out))
        bad = _numbers(out) - allowed
        if not out or bad or info["think_leak"]:
            info["guard"] = f"template used (numbers not in envelopes: {sorted(bad)[:5]})" if bad else "template used"
            out = template
    except Exception as e:
        out, info["error"] = template, f"{type(e).__name__}: {str(e)[:120]}"
    info["ms"] = round((time.perf_counter() - t0) * 1000)
    return out, info
