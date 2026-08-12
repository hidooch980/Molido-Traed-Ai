# Architecture

## Shape

A **modular monolith** plus workers, not microservices. The spec is explicit
about this (§54): split a service out only when a measured bottleneck justifies
it. One deployable keeps transactions honest — an order, its risk decision and
its audit record can share a transaction, which is impossible across a network
boundary without distributed-transaction machinery nobody wants in a trading
path.

```
backend/app/
  core/        config, logging, errors, enums, safe mode
  db/          engine, session, portable types, alembic migrations
  models/      SQLAlchemy tables
  schemas/     Pydantic DTOs (API boundary)
  providers/   market-data adapters + registry
  services/    domain logic
  api/v1/      HTTP routers
  seed/        demo dataset generator
  cli.py       operator commands
```

## The two rules everything else rests on

### 1. Point-in-time integrity

`services/point_in_time.get_bars()` is the **only** sanctioned way to read
historical market data. Everything later — features, market memory, episodes,
backtests, model training — must go through it. Two filters, both required:

- **Closure.** A bar is visible only after it has closed at or before `as_of`.
  An H1 bar opening at 10:00 contains 10:59 prices; at 10:30 it is the future.
- **Knowledge time.** A row is visible only if `ingested_at <= as_of`. A
  correction backfilled tomorrow cannot appear in a decision reconstructed for
  today.

Corrections are **appended as revisions**, never written over the original.
That is what allows a past decision to be replayed exactly as it was made.

The invariant is asserted in code after every read (`_assert_no_lookahead`), so
a future query rewrite fails loudly instead of quietly poisoning a backtest.

### 2. No fabricated data

`InsufficientDataError` is a first-class error, mapped to HTTP 409. When there
is not enough trustworthy data, the system says so. It never substitutes an
estimate for a measurement, and the quality engine never repairs a bad candle —
a silently repaired wrong price is more dangerous than an obviously missing one.

## Data flow (this milestone)

```
Provider adapter          providers/*.py
    ↓ raw rows
Normalization             services/ingestion._normalize
    ↓ drops only unusable rows
Quality detectors         services/data_quality
    ↓ findings + score
Revisioned storage        models/market_data.Bar
    ↓
Point-in-time read        services/point_in_time.get_bars
    ↓
API / future engines
```

Everything downstream of the point-in-time read is a later phase.

## Sessions and the market calendar

`services/sessions.SessionCalendar` answers one question — *was this market
open at this instant* — and everything schedule-shaped depends on it: gap
detection, expected-bar grids, freshness, and later the regime engine's session
feature.

Three concerns stay separate on purpose: weekly **trading hours** (in the
instrument's own local time), dated **holidays** (`market_holidays`, supporting
full closures, early closes and late opens), and the Sydney/Tokyo/London/New
York **liquidity sessions**.

Every boundary resolves through `zoneinfo`. FX hours are expressed in
`America/New_York` so the Sunday open and Friday close follow US DST — doing
this arithmetic against a fixed UTC offset produces a silent one-hour error for
a few weeks each spring, which shifts a whole session's worth of bars.

`active_sessions()` returns a **list**, not one label: the London/New York
overlap is the highest-liquidity window of the day, and collapsing it to a
single name discards the most informative fact about it.

## Feature store

`services/feature_store.py` reads market data **only** through
`point_in_time.get_bars()`. It never queries `ohlcv` directly, and that is the
single most important review point in the module: a direct query here would
silently void the no-lookahead guarantee, and no test elsewhere would catch it.

Each feature declares a `lookback` and a `version`. The lookback is enforced —
a feature that cannot warm up returns `None` rather than a number computed from
too little history. The version is stored with every value, so a model trained
on `rsi_14 v1` can never be fed v2 numbers without the change being visible.

`materialize()` separates two things that look alike and are not: `start`/`end`
bound which **bars** are described, while `as_of` is the **knowledge cutoff** —
which vintage of those bars to use. No-lookahead within a run comes from
slicing (`series[:i+1]`), not from `as_of`; what `as_of` controls is whether a
later revision of an earlier bar is visible. Each stored row records
`source_revision` and `computed_at` so the two are always distinguishable
after the fact.

## The collector

`workers/collector.py` is the only long-running process besides the API. It
sweeps a watchlist on a schedule: ingest → quality → materialize features.

It writes data and decides nothing. No trading logic, no risk decision, no
order — and it must not grow them by accident, because it runs unattended and
predates every safety layer the spec requires around execution.

Three operational properties make it safe to leave running:

- **Closed markets are skipped, not polled.** The session calendar already
  knows; polling anyway burns provider quota and produces empty responses that
  are indistinguishable from a broken feed.
- **Every cycle is safe to repeat.** Ingestion is idempotent per window key and
  features are skipped when present, so a crash, a restart, or two overlapping
  sweeps cannot duplicate data.
- **One bad symbol does not stop the sweep.** Failures are recorded per entry
  and the loop continues.

## Multi-tenancy

`tenant_id` is on every business table and enforced in the service layer, not
only in request handlers — background workers must not be able to cross tenants
either. Market data is deliberately **not** tenant-scoped: a EURUSD bar from a
given provider is the same public fact for everyone, and what is private is the
decision made from it.

## Safe mode

`core/safe_mode.SafeMode` is a latch consulted before any risk-increasing
action. Nothing in this milestone increases risk, but the choke point exists
now so later phases have one obvious place to call, rather than each inventing
its own guard. Persisted multi-process state lands with the Stability Core.

## Storage

PostgreSQL with TimescaleDB hypertables on `ohlcv` and `ticks`; compression
after 180/7 days, retention on raw ticks only — bars are the durable record.
Column types are portable (`db/types.py`), so the suite runs on in-memory
SQLite and the point-in-time regression tests execute in CI with no container.
Hypertable behaviour is verified by running the migration against the real
image, not by the unit suite.

## Deferred, and why

Auth, rate limiting and RBAC enforcement have tables and enums but no
middleware yet. There is no endpoint that mutates anything and no broker
connection to protect, so shipping a half-designed auth layer now would mean
rewriting it against real requirements later. It is the first thing to build
alongside the execution phase — before, not after.
