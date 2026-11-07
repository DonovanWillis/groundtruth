# Status for Monish (unattended run, started 16:38 ET)

## 1. What you can try right now
- Labelling page: http://localhost:8765/label (unchanged, running)
- Demo UI + API (local only): http://localhost:8000/ (slice indexes until the county index lands)

## 2. Numbers
- County precompute 2022: running on the 4060. Started 16:28, ~16–18 chips/s, ETA ~18:20. Then 2020 (~+100 min).

## 3. Decisions needed (max 5)
- (none yet)

## Progress
| item | state | notes |
|---|---|---|
| 1 precompute | in progress | 2022 scene 5/51 at 16:38 |
| 2 backyard re-rank | todo | |
| 3 find-all | todo | |
| 4 refine | todo | |
| 5 filter/measure/export, contract v0.3 | todo | |
| 6 search across time | todo (needs 2020) | |
| 7 UI | todo | |
| 8 evaluation | todo (needs county index) | |
| 9 demo hardening | todo | |
| 10 write-up material | todo | |
| 11 ORYN merge plan | todo | |

## Decisions I made
- 16:38 Session lock at `docs/.session-lock`, HEAD `ca18aa0`.

## Notes
- The GPU query-time approval line was present (not deleted), so query-time GPU use is allowed until Sun 12:00, capped at 4 GB.
  Groundtruth backs off to CPU if free VRAM drops (guard in code).
