# Phase plan

The spec defines 53 phases. This file records where the build actually is, so
the next session resumes without re-deriving the order.

## Done — Milestone 1 (phases 0–5)

| Phase | Status | Evidence |
| --- | --- | --- |
| 0 Repository audit | done | Greenfield: the folder held only the spec document. Recorded in the plan and in `README.md`. |
| 1 Architecture / gaps | done | `docs/ARCHITECTURE.md` |
| 2 Data infrastructure | done | `infra/docker-compose.yml`, migration `0001_foundation` |
| 3 Historical acquisition | done | `providers/`, `services/ingestion.py` — retry, resume, checkpoints, dedup, idempotency |
| 4 Data quality / provenance | done | `services/data_quality.py`, `dataset_quality` gate |
| 5 Point-in-time engine | done | `services/point_in_time.py`, `tests/test_point_in_time.py` |

81 tests pass, including the leakage regression suite.

## Done — Milestone 2 so far

| Phase | Status | Evidence |
| --- | --- | --- |
| 6 Canonical instrument engine (session calendar) | done | `services/sessions.py`, migration `0002_session_calendar`, `tests/test_sessions.py` |
| 7 Feature store | done | `features/`, `services/feature_store.py`, migration `0003_feature_store`, `tests/test_feature_store.py` |
| 8 Symbol DNA | done | `services/symbol_dna.py`, migration `0004_symbol_dna`, `tests/test_symbol_dna.py` |

**183 tests pass.**

Phase 6 removed the guesswork from gap detection: weekends and holidays are
excluded from the expected-bar grid, real weekday holes are full WARNINGs, and
bars delivered while the market was shut are flagged — a defect the old
weekday heuristic could not see at all.

Phase 7 added 12 versioned features that read **exclusively** through
`get_bars()`. A feature computed live and the same feature recomputed months
later produce identical numbers; future bars cannot influence a past value; a
feature that cannot warm up reports `None` rather than a number derived from
too little history.

## Also shipped (not a numbered phase)

- **Collector worker** — `workers/collector.py`. The long-running process that
  keeps gathering bars and materializing features on a schedule, skipping
  closed markets. It writes data and decides nothing; that separation is what
  keeps it safe to run unattended before the risk layer exists.
- **VPS deployment** — `infra/docker-compose.prod.yml`, Dockerfiles, Caddy TLS,
  restore-verified backups. See `docs/DEPLOYMENT.md`.
- **Dashboard redesign** — institutional layout, validated chart palette,
  point-in-time price chart, feature and session screens.

Phase 8 measures what an instrument actually does — volatility percentiles,
session and clock rhythm, trend persistence, liquidity, cross-instrument
correlation. Six of the eleven facets the spec lists (regime, news sensitivity,
strategy performance, failure patterns, execution profile, market memory) need
phases that do not exist yet; they are reported as `unavailable` **with the
reason**, never approximated.

## Next — Milestone 2 (phases 9–13)

Recommended order, with the reason each depends on the previous:

1. **9 Market memory** → **10 Historical episodes** → **11 Similarity engine**.
   Episodes need outcomes, so the episode schema should be written now but only
   populated once execution exists; until then it holds backtest outcomes.
2. **12 World state** → **13 Regime engine**. The session labels from phase 6
   feed directly into world state, so that field is already available.

The collector is accumulating history in the meantime, so each new phase has
more real data to work from than the last.

## Out of order on purpose

**Auth / RBAC (phase 48)** should be pulled forward to sit *immediately before*
phase 25 (execution safety) — not left to the end. There is currently no
mutating endpoint and no broker credential to protect, but the first PR that
adds either must ship auth with it.

## Later

14–18 cognitive brain, council, meta-brain, adversarial, counterfactual ·
19 strategy · 20 probability/calibration · 21 EV · 22 portfolio ·
23–24 risk brain and stress · 25–27 execution, broker adapters, guardian ·
28 challenge · 29 journal · 30–34 learning lab, registry, champion/challenger,
drift, benchmark · 35–37 stability, crash recovery, disaster recovery ·
38–42 dashboard, charts, command mode, what-if, decision replay ·
43–44 multi-account/broker · 45–46 Telegram, n8n · 47 multilingual ·
48 security · 49 observability · 50–52 performance, load, E2E ·
53 production readiness.

## Phase completion standard (spec §73)

No phase is marked PASS on code existence. Every phase reports: status,
implementation summary, files created/modified/deleted, migrations, API
changes, tests passed/failed, security findings, performance findings, known
limitations, rollback plan, evidence, next phase.
