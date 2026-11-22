# PROJECT_EXECUTION_STATE

Living log for Master Development & Preservation Prompt V2.
Create-once, append thereafter. Additive work only. No force-push, reset --hard, git clean, branch delete, or DB drop.

## Current pointer

- Date: 2026-11-22 (Asia/Tehran)
- Checkpoint tag: `checkpoint/v2-audit-20261122` → `0870a5302f828e2f4e3d4f0cb42cbb51b78b6a88` (`agents/stage-21-weighted-vote`)
- Audit: `docs/v2-audit-20261122.md`
- Active work branch (additive, unmerged): `agents/stage-22-pro-btb`
- Default mode: Research / Paper / shadow. Live trading remains BLOCKED.
- Central Risk Brain is not bypassed. No engine may override it.

## Phase status

| Phase | Title | Status |
|---|---|---|
| 1 | Repo audit | DONE (see `docs/v2-audit-20261122.md`) |
| 2 | Backup / git checkpoint | DONE (tag pushed, non-destructive) |
| 3 | Extract exact definitions (5 key levels; SP2L; Pro BTB; Spike & Imbalance) | NOT STARTED — no guessing; unspecified items stay RESEARCH |
| 4 | Additive architecture | NOT STARTED |
| 5 | Four engines (SP2L, Pro BTB, Spike & Imbalance/FVG, Key Levels) | IN PROGRESS — Pro BTB is the first engine |
| 6 | Eight layers | NOT STARTED as a V2 package (fragments already exist; see audit) |
| 7 | Rocket Trade Hunter integration | NOT STARTED as a V2 package (RT01–RT10 already exist in shadow) |
| 8 | Hybrid AI Brain integration | NOT STARTED as a V2 package (BRAIN-01 + `app/brain` already exist) |
| 9 | Dashboard / analytics | NOT STARTED as a V2 package (partial metrics already exist) |
| 10–12 | Tests, fixes | NOT STARTED for the V2 engines (existing suite remains the regression gate) |
| 13 | Paper trading | NOT STARTED for the V2 engines |
| 14 | Security / performance | NOT STARTED as a V2 pass |
| 15 | Stable release + report | BLOCKED pending approval |

## Already present vs missing (from the Phase 1 audit)

Already present (reuse, do not rewrite): 51 shadow agents including 10 Rocket roles; SMC/FVG (SM04); MTF (TA02); agent risk gate + `app/brain/risk.py`; leak-free walk-forward and scorecard (WR/PF/expectancy/MDD/avg R fragments); paper/shadow cycle; dashboard/lab/rocket pages.

Missing (build additively): the five named Key Levels; SP2L; Pro BTB; a dedicated Spike & Imbalance engine; V2 eight-layer package; Rocket ingest of the four engines; Hybrid Brain wiring of those engines; key-levels map and a complete metrics/replay dashboard.

## Change log

### 2026-11-22 — Phase 1+2 audit and checkpoint

- Files: `docs/v2-audit-20261122.md` (new), `PROJECT_EXECUTION_STATE.md` (new). Git tag `checkpoint/v2-audit-20261122` on `0870a53` (no file change in the tag itself).
- Before: stage-21 tree, no V2 state file, no checkpoint tag.
- Change: read-only audit written; annotated tag created and pushed. No existing file deleted or rewritten.
- Reason: Master V2 Phase 1+2, before any engine work is committed.
- Impact: documentation and a recoverable tag only. Runtime unchanged.
- Test: not applicable for the tag; audit is observational.
- Result: tag visible on origin as `checkpoint/v2-audit-20261122`.
- Rollback: `git checkout checkpoint/v2-audit-20261122`. Do not delete the tag.

### 2026-11-22 — Task A (EA deliverable, outside this git repo)

- Files on the box (not this repository): `/workspace/deliver/molido-expert/Molido_Expert.ex5`, `/workspace/deliver/molido-expert-2.2.zip`.
- Before: zip lacked the compiled expert.
- Change: copied `Molido_Expert.ex5` (457,926 bytes) read-only from the RoboForex MT5 data folder on the Windows VPS via WinRM; rebuilt the zip with Python `zipfile` (ex5 included, `ref/` excluded). Nothing was changed on the VPS.
- Reason: user asked for the executable that was missing from the previously sent files.
- Impact: local deliverable only.
- Test: local size matches remote size (457,926).
- Result: done.
- Rollback: delete the two box files; VPS untouched.


### 2026-11-22 — Phase 5 first engine: Pro BTB (additive)

- Files (all new): `backend/app/agents/pro_btb/**`, `backend/tests/test_pro_btb_*.py`, `backend/tests/pro_btb_bars.py`, `docs/pro-btb-fa.md`. Also this state file and `docs/v2-audit-20261122.md`.
- Before: no Pro BTB module; 51-agent runner and Risk Brain unchanged.
- Change: independent deterministic detectors for the six specified stages; rule catalog with one status each; optional read-only adapter (off by default, never overrides Risk Brain). Entry/SL/TP stay WAIT while those rules are RESEARCH. No existing file was modified or deleted.
- Reason: user specification t124u, as the first Phase 5 engine after the V2 audit.
- Impact: new shadow module only. Default behaviour of agents, risk, and execution is unchanged.
- Test: `pytest` in `backend/` — 4754 passed, including 42 new Pro BTB tests; 0 failed.
- Result: branch `agents/stage-22-pro-btb` (push only, not merged).
- Rollback: stay on / check out `checkpoint/v2-audit-20261122` or `agents/stage-21-weighted-vote`. Delete or ignore the stage-22 branch; no force-push or branch delete is required for rollback.

## Next

Phase 5 first engine: additive Pro BTB sub-module on `agents/stage-22-pro-btb`. Branch push only; no merge, no deploy, no live trading.
