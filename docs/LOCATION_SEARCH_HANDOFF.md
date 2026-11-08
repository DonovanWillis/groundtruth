# Claude team handoff: worldwide location search

This document supersedes the earlier independent MCP, database, and Cesium prompts for the **next shared task**. The team is building one vertical slice: search a town or address, move the map there, and explain whether Groundtruth analysis is available. The active branch is `codex/ask-maps-foundation` in Donovan's fork. Read `docs/CONVERSATION_CONTEXT.md`, `docs/ASK_MAPS_PLAN.md`, `docs/LOCATION_SEARCH_CONTRACT.md`, `AGENTS.md`, and `CLAUDE.md` before work. No ORYN access, Google data/tiles, people data, secrets, or writes to `data/labels/`.

## Shared working rules

There are three Claude roles and one Codex integrator. All roles use the same API contract and acceptance checks in `docs/LOCATION_SEARCH_CONTRACT.md`. Use separate worktrees and branches. Do not edit the same files concurrently. Post a short handoff here after each completed role: commit hash, changed paths, tests, unresolved issues, and exact interface changes. The next role reads that handoff and bases its work on the previous commit. Codex integrates and runs the cross-stack test. Do not force-push or merge to main.

| Order | Role | Owns | Depends on |
|---|---|---|---|
| 1 | Location backend | `engine/groundtruth/providers/`, `api/`, focused tests, contract updates | Current contract |
| 2 | Map and search UI | `web/` and UI tests | Role 1 committed API |
| 3 | Integration and coverage QA | integration tests and docs, fixes assigned back to owner | Roles 1 and 2 commits |

The existing MCP work is separate and should pause until its concurrent writers agree on one owner. The pasted Claude output reported simultaneous changes under `mcp/` and `tests/mcp/`; do not run another MCP writer in the same worktree.

## Handoff log

| time | role | commit | tests and notes |
|---|---|---|---|
| pending | backend | pending | Awaiting Role 1. |
