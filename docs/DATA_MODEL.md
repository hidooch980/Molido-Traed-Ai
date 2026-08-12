# Data model

## Boundaries (spec §67)

| Group | Tables |
| --- | --- |
| Tenancy | `tenants`, `users`, `api_keys` |
| Reference | `providers`, `instruments`, `broker_symbols` |
| Market data | `ohlcv`, `ticks` |
| Ingestion | `ingestion_runs`, `ingestion_checkpoints` |
| Quality | `data_quality_findings`, `dataset_quality` |
| Observability | `audit_events` |

## Point-in-time columns

Every market-data row carries three:

| Column | Meaning |
| --- | --- |
| `event_time` | when the fact was true in the market (bar **open** time, UTC) |
| `ingested_at` | when we learned it |
| `revision` | 1 for the first version, incremented per correction |

A revised bar is a **new row**: same `event_time`, higher `revision`, later
`ingested_at`. Reads pick the highest revision whose `ingested_at <= as_of`.

## `ohlcv`

Primary key `(instrument_id, timeframe, provider_id, event_time, revision)` —
Timescale requires the partitioning column in the key, and the revision makes
corrections additive rather than destructive. Hypertable on `event_time`,
30-day chunks, compressed after 180 days.

`quality_score` on the row is written by the quality engine; the training gate
lives on `dataset_quality.is_training_eligible`.

## `instruments` vs `broker_symbols`

`instruments` is the canonical, global record: `EURUSD` is one instrument.
`broker_symbols` is tenant-scoped and holds the properties that differ per
broker and drive real-money sizing — contract size, digits, point, tick size,
tick value, volume min/max/step, margin rules, spread model.

Those are stored exactly as the broker reports them and **never inferred**.
`normalize_symbol()` strips broker decoration (`EURUSD.m`, `EURUSD-ECN`) to
find the canonical instrument, conservatively: a wrong merge of two distinct
instruments is far more damaging than an unmerged duplicate an operator can map
by hand.

## `dataset_quality`

The gate. `is_training_eligible` requires **both** a score above the configured
threshold **and** zero error/critical findings — a good average cannot outvote
one negative price. An unevaluated dataset is ineligible; absence of evidence is
not a pass.

## `audit_events`

Append-only, indexed by time, type and tenant. Carries `trace_id` so an HTTP
request, its ingestion run and its findings can be stitched together. Payloads
hold metadata only — never secrets, tokens or raw broker responses.

## Retention

| Data | Policy |
| --- | --- |
| `ticks` | compress after 7 days, drop after 400 |
| `ohlcv` | compress after 180 days, **never dropped** |
| `audit_events` | no automatic deletion |

Bars are the durable historical record the whole platform reasons over; ticks
are high-volume detail that can be re-fetched from the provider.
