# Milestone 1 report — phases 0–5

Reported in the format the spec requires (§73). No phase is marked PASS on the
existence of code.

## Status

**PASS** for phases 0–5, with one verification step blocked by the environment
(see *Known limitations*).

## Implementation summary

Greenfield build of the MolidoTrade AI foundation: repository, infrastructure,
database schema, market-data ingestion, data-quality engine, and point-in-time
integrity — plus branding and a dashboard shell. No broker execution code was
written, deliberately: per the spec's core principle, execution comes after the
risk brain that authorizes it.

## Files created

| Area | Paths |
| --- | --- |
| Infrastructure | `infra/docker-compose.yml`, `infra/.env.example`, `.gitignore`, `.github/workflows/ci.yml` |
| Backend core | `backend/app/core/{config,logging,errors,enums,safe_mode}.py` |
| Database | `backend/app/db/{base,session,types}.py`, `alembic.ini`, `app/db/alembic/**` |
| Models | `backend/app/models/{tenancy,instruments,market_data,ingestion,audit}.py` |
| Providers | `backend/app/providers/{base,csv_provider,yfinance_provider,registry}.py` |
| Services | `backend/app/services/{ingestion,data_quality,point_in_time,instruments,audit}.py` |
| API | `backend/app/main.py`, `app/api/v1/{health,instruments,market_data,data_quality}.py`, `app/schemas/market.py` |
| CLI / seed | `backend/app/cli.py`, `backend/app/seed/demo_data.py` |
| Tests | `backend/tests/{conftest,test_point_in_time,test_data_quality,test_ingestion,test_instruments,test_core,test_api}.py` |
| Frontend | `frontend/**` (Next.js 15 shell, 4 pages, i18n + RTL scaffold) |
| Brand | `brand/molidotrade-{logo,mark,mark-mono}.svg`, `brand/README.md` |
| Docs | `docs/{ARCHITECTURE,DATA_MODEL,PHASES}.md`, `README.md` |

Files modified: none — the repository was empty apart from the spec document.
Files deleted: none.

## Migrations

`0001_foundation` — 14 tables; TimescaleDB hypertables on `ohlcv` (30-day
chunks) and `ticks` (1-day), compression policies at 180/7 days, retention on
raw ticks at 400 days. Applies and reverses cleanly. Degrades to plain tables
when the extension is unavailable, so CI without Timescale still works.

## API changes

New surface (all read-only):

- `GET /health/live`, `GET /health/ready`
- `GET /api/v1/instruments`, `GET /api/v1/instruments/{id}`
- `GET /api/v1/bars` — `as_of` is **required**
- `GET /api/v1/data-quality/{instrument_id}`

## Tests

**81 passed, 0 failed.** `ruff check` clean, `mypy app` clean (42 files).

Coverage of note:

- Point-in-time: unclosed bar invisible; close boundary inclusive; late-ingested
  row invisible; revision visible only after it was known; naive `as_of`
  rejected; insufficient history raises rather than returning a short series.
- Ingestion: idempotent re-run; value-equal rows counted as duplicates;
  corrections become revisions; retry and rate-limit backoff; exhausted retries
  recorded, not raised; checkpoint resume and never moving backwards.
- Data quality: each detector asserted against known-bad input; weekend gaps
  scored as INFO; statistics withheld below the sample floor; empty dataset
  scores 0.0; one critical finding blocks training eligibility.
- Tenant isolation: a broker mapping is invisible to another tenant while both
  share the canonical instrument.

## Evidence (live run against TimescaleDB)

```
alembic upgrade head                  → 14 tables; hypertables: ohlcv, ticks (compression on)
python -m app.cli seed-demo           → fetched 716, written 715, duplicates 1, score 0.983
                                        findings: duplicate_bar 1, missing_candle 1,
                                                  price_gap 1, outlier 2
re-run seed-demo                      → written 0 (idempotency_key short-circuit)
GET /api/v1/data-quality/{id}         → findings match the injected defects exactly:
                                        missing_candle 2024-01-09T08:00 (5 rows),
                                        duplicate_bar 2024-01-17T16:00,
                                        outlier 2024-01-21T20:00
                                        is_training_eligible: false (blocked by the ERROR)
GET /health/ready                     → 200, database + redis healthy
```

The detectors were proven against ground truth: the seed generator reports what
it corrupted, and the engine found those exact windows.

## Security findings

- Credentials are redacted in config summaries and scrubbed from logs by key
  name; both are unit-tested.
- Passwords and API keys are stored as hashes only.
- Security headers set on the frontend; CORS restricted to `localhost:3000`.
- **Open:** no authentication or rate limiting yet. Acceptable now because no
  endpoint mutates state and no broker credential exists — but the first PR that
  adds either must ship auth with it. Recorded in `docs/PHASES.md`.

## Performance findings

- The point-in-time query uses a window function rather than `DISTINCT ON` so it
  runs on SQLite in tests; on Postgres it is served by `ix_ohlcv_lookup`. Worth
  re-measuring once a table holds tens of millions of rows.
- Ingestion writes row-by-row through the ORM. Fine at demo scale, and the
  obvious first optimisation (bulk insert) when backfilling years of M1 data.

## Known limitations

1. **Dashboard was not seen rendering live rows.** Docker Desktop stopped
   partway through verification, so the pages were confirmed only in their
   offline state — which is itself correct behaviour: `/health/ready` returned
   503 and the UI reported "Backend unreachable: HTTP 503" instead of showing an
   empty table. The API had already been verified returning the real data
   directly. Re-run `docker compose up -d` and reload to close this.
2. **Session calendar missing.** Weekend gaps are detected heuristically
   (`weekday() >= 5`); holidays are not modelled. Phase 6.
3. **Safe mode is process-local.** Fine today; needs shared state before
   multi-worker deployment.
4. **Provider conflict detection exists but is not wired into ingestion** — it
   needs two providers covering one instrument, which is a later configuration.
5. yfinance adapter is written but untested against the live API (optional
   dependency, no network calls in the test suite by design).

## Rollback plan

`alembic downgrade base` drops every table created here. The repository had no
prior state, so reverting the code is a matter of deleting the working tree.
No data outside the project was touched.

## Next phase

**Phase 6 — canonical instrument engine (session/trading-hours calendar).** It
unblocks honest gap detection and is a prerequisite for the feature store.
Order and rationale in `docs/PHASES.md`.
