# Phase 6 report — canonical instrument engine (session calendar)

Reported per spec §73.

## Status

**PASS.** 120 tests green, `ruff` and `mypy` clean, verified end-to-end against
TimescaleDB.

## Why this phase existed

Milestone 1 detected missing candles with a weekday heuristic: any gap touching
a Saturday was downgraded to INFO. That was wrong in both directions — it
excused a genuine Friday outage and it would have flagged every Christmas as
data loss. This phase replaces the guess with a real calendar.

## Implementation summary

- `services/sessions.py` — `SessionCalendar` (trading hours, holidays,
  expected-bar grids, `next_open`/`next_close`) and `active_sessions()` for the
  Sydney/Tokyo/London/New York labels.
- All boundaries resolve through `zoneinfo`. FX hours are expressed in
  `America/New_York`, so the Sunday open and Friday close track US DST the way
  brokers actually behave.
- `models/calendar.py` + migration `0002` — `market_holidays` (full closure,
  early close, late open) and `instruments.market_code`.
- `data_quality._check_gaps_with_calendar` — expected bars come from the
  calendar; the weekday fallback remains only for calendar-less batch
  evaluation and is now recorded in `QualityReport.calendar_aware`.
- New API: `GET /api/v1/sessions/{instrument_id}`, `GET /api/v1/sessions`.
- New CLI: `seed-holidays`, `session-status`.
- New dashboard page: `/sessions`.

## What the calendar caught immediately

Two real defects in our own demo fixture, neither of which the old heuristic
could see:

1. The generator emitted **weekend bars for a forex pair** — 24/7 data for an
   instrument that closes Friday night. Flagged as `session_mismatch`.
2. After the holiday seed, it emitted bars on **1 January**, a full closure.

Both were fixed in the generator rather than silenced in the detector. The demo
window moved to February 2024, which contains none of the baseline holidays, so
the only defects in the fixture are the ones injected on purpose.

## Evidence

Before phase 6 (weekday heuristic, 720 continuous bars):

```
fetched 716, score 0.983
findings: duplicate_bar 1, missing_candle 1, price_gap 1, outlier 2
```

After (calendar-aware, weekends excluded from the fixture and the grid):

```
fetched 522, score 0.979
findings: duplicate_bar 1, missing_candle 1, price_gap 1, outlier 1
expected_bars 526, actual_bars 522
missing_candle: 5 rows from 2024-02-13T08:00Z, severity WARNING, calendar_aware true
```

`expected_bars` is now 526 rather than ~720: the weekend hours are no longer
counted against the dataset. The injected 5-bar hole is a full WARNING instead
of being excused, and the second spurious `outlier` disappeared with the
unrealistic weekend data.

Session status, live:

```
2024-03-06T14:00Z  open,   sessions [london, new_york], closes 2024-03-08T22:00Z
2024-03-09T14:00Z  closed, sessions [off],              opens  2024-03-10T21:00Z
```

## Tests

**120 passed.** 28 new in `tests/test_sessions.py`, 6 in
`TestCalendarAwareGaps`, 3 API tests.

Load-bearing cases:

- **DST boundary.** 21:00 UTC is open on 5 January (EST) and closed on 15 March
  (EDT) — the same local 17:00 New York close. A fixed offset would fail one.
- Holiday closure, early close and late open each narrow or shut a day.
- Instrument-specific holidays override the market-wide entry.
- Weekend gaps produce **no finding at all**; weekday holes produce WARNING.
- A bar delivered while the market was shut is flagged.
- `next_close` on a closed market reports the *next* session's end, not "now".
- Crypto reports `next_close: null` rather than inventing a far-future time.

## API changes

| Endpoint | Purpose |
| --- | --- |
| `GET /api/v1/sessions/{instrument_id}` | open/closed, active sessions, next open/close, holiday |
| `GET /api/v1/sessions` | holiday calendar listing |

`instruments.market_code` is new in responses.

## Migrations

`0002_session_calendar` — adds `market_holidays` and
`instruments.market_code` (server default `FX`, so existing rows migrate
without a backfill). Applies and reverses cleanly on TimescaleDB.

## Security findings

None new. The holiday endpoints are read-only and expose public market data.
The outstanding auth gap from milestone 1 is unchanged and still scheduled
before the execution phase.

## Performance findings

`expected_bar_times` walks the grid one slot at a time — fine for the windows
ingestion uses (30-day chunks), but a multi-year M1 backfill would generate
~1.5M `is_open` calls per instrument. If that becomes hot, the fix is to
precompute open/closed intervals per week rather than per bar. Not needed yet;
noted so it is not rediscovered under time pressure.

## Known limitations

1. **Baseline holidays are deliberately minimal** — New Year and Christmas
   only. Good Friday, Easter Monday and national holidays vary by venue and
   year; a wrong entry would *mask* a real outage, which is worse than a
   missing one. Operator-loaded holidays carry a `source` field.
2. Session windows are the common liquidity definitions, not exchange hours.
   FX has no exchange; the numbers are conventions and are documented as such.
3. `market_holidays` has no import tooling yet — entries go in via
   `upsert_holiday()` or the CLI seed.
4. Weekly/monthly timeframes raise rather than guess a grid; a calendar rollup
   is needed when those become relevant.

## Rollback plan

`alembic downgrade 0001_foundation` drops `market_holidays` and the
`market_code` column. The quality engine falls back to the weekday heuristic
automatically when no calendar is supplied, so reverting the code is safe
without a data migration.

## Next phase

**Phase 7 — feature store.** It must read exclusively through
`point_in_time.get_bars()`; that is the single thing to review hardest in that
change.
