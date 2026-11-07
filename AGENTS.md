# AGENTS.md: rules for coding agents (Codex, Claude, etc.)

Read `CLAUDE.md` for the project rules (envelope, DataProvider, licences, no people data, units in field names).

## Ownership
| owner | paths | notes |
|---|---|---|
| **Donovan** | `mcp/`, `agent/`, `tests/mcp/`, `tests/agent/`, `docs/REQUESTS.md`, `docs/DONOVAN_*.md` | MCP server + AI agent that act on the map through the API |
| Monish / engine | everything else (`engine/`, `api/`, `web/`, `scripts/`, `tests/` except the two above, `docs/` except the above) | engine, API, UI, data |

## Rules for Donovan's agent work
- **Never push to `main`.** Work on your branch (`donovan/mcp-agent`) and open a PR.
- **Never edit files outside your paths.** Need an engine/API change? Write it in `docs/REQUESTS.md`
  (what, why, example request/response) and it will be done on the engine side.
- Talk to the engine **only through the HTTP API** in `docs/CONTRACT.md`. Don't import `engine/` directly.
  Use `docs/fixtures/*.json` (one real request/response per tool, including `declined.json`) for offline tests.
- Treat every response as an envelope: check `status` (`ok | partial | declined`), show `limits`, and surface
  `steps` in logs. `declined_reason == "not_implemented"` means the route exists but the tool is not built yet.
- Never handle or commit API keys, tokens or `.env*` files. Never send data about people.
- Keep updates current with `git fetch origin && git merge origin/main`.

## Running the API locally
```bash
bash scripts/run_api.sh                    # 127.0.0.1:8000, see /api/v1/health
pytest -q                                   # engine tests (yours go in tests/mcp, tests/agent)
```
