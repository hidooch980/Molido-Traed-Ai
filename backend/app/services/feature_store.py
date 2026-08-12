"""Feature store (spec phase 7).

The one rule: **every bar this module sees comes from
`point_in_time.get_bars()`**. It never touches the `ohlcv` table directly. That
is not stylistic — it is the reason a feature computed live and the same
feature recomputed during a backtest give identical numbers. If a future change
adds a direct query here, the leakage guarantee from phase 5 is silently gone,
and no test elsewhere would catch it.

Two operations:

* `compute_at()` — features for one instant, computed on demand. Nothing is
  stored; this is what a live decision path uses.
* `materialize()` — walks a range, computes each bar's features and persists
  them, so training and backtests read rows instead of recomputing millions of
  windows.

Both share one code path for the maths, so a materialized value and a live one
cannot drift apart.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, aliased

from app.core.enums import Timeframe
from app.core.errors import InsufficientDataError, ValidationFailedError
from app.core.logging import get_logger
from app.features import base as registry
from app.models.features import FeatureValue
from app.services.point_in_time import BarView, get_bars

log = get_logger(__name__)

# Extra bars fetched beyond the declared lookback. Indicators such as the EMA
# are warmed over several periods, and a small cushion costs one query instead
# of a subtly seeding-dependent value.
LOOKBACK_MARGIN = 5


@dataclass
class FeatureRow:
    """Features describing a single bar."""

    event_time: datetime
    values: dict[str, float | None] = field(default_factory=dict)
    source_revision: int = 1

    def as_dict(self) -> dict[str, object]:
        return {"event_time": self.event_time.isoformat(), **self.values}


@dataclass
class MaterializeResult:
    instrument_id: uuid.UUID
    timeframe: Timeframe
    bars_processed: int
    values_written: int
    values_skipped: int
    features: list[str]
    first_event_time: datetime | None = None
    last_event_time: datetime | None = None


def _resolve(feature_names: list[str] | None) -> list[registry.FeatureSpec]:
    names = feature_names or registry.names()
    return [registry.get(name) for name in names]


def compute_at(
    session: Session,
    instrument_id: uuid.UUID,
    timeframe: Timeframe,
    as_of: datetime,
    *,
    feature_names: list[str] | None = None,
    provider_id: uuid.UUID | None = None,
) -> FeatureRow:
    """Features for the most recent bar knowable at `as_of`.

    Raises `InsufficientDataError` when history is too short for the requested
    features — never returns a partially-warmed value dressed up as a real one.
    """
    specs = _resolve(feature_names)
    if not specs:
        raise ValidationFailedError("No features requested")

    needed = max(spec.lookback for spec in specs) + 1 + LOOKBACK_MARGIN
    # Require only enough history for the *shortest* feature. A long-lookback
    # indicator that cannot warm up yet reports None (see `_compute_row`);
    # failing the whole call because one feature is hungry would make the store
    # useless early in an instrument's history.
    bars = get_bars(
        session,
        instrument_id,
        timeframe,
        as_of,
        lookback=needed,
        provider_id=provider_id,
        min_bars=min(spec.lookback for spec in specs) + 1,
    )
    return _compute_row(specs, bars)


def _compute_row(specs: list[registry.FeatureSpec], bars: list[BarView]) -> FeatureRow:
    """Evaluate every spec against a window whose last bar is the target."""
    target = bars[-1]
    values: dict[str, float | None] = {}
    for spec in specs:
        try:
            values[spec.name] = spec.compute(bars)
        except InsufficientDataError:
            # One short feature must not void the whole row: record it as
            # unknown rather than dropping the others or inventing a number.
            values[spec.name] = None
    return FeatureRow(
        event_time=target.event_time, values=values, source_revision=target.revision
    )


def materialize(
    session: Session,
    instrument_id: uuid.UUID,
    timeframe: Timeframe,
    *,
    start: datetime,
    end: datetime,
    as_of: datetime | None = None,
    feature_names: list[str] | None = None,
    provider_id: uuid.UUID | None = None,
    recompute: bool = False,
) -> MaterializeResult:
    """Compute and persist features for every bar in [start, end).

    `start`/`end` bound which **bars** are described. `as_of` is a different
    thing: the **knowledge cutoff** — which vintage of those bars to use. They
    must not be conflated. A backfill run today legitimately uses today's
    knowledge, including any revisions that arrived since, which is why `as_of`
    defaults to now rather than to `end`.

    No-lookahead within the series comes from the slicing, not from `as_of`:
    the window for bar *i* is `series[:i+1]`, so a feature can never see a
    later bar. What `as_of` controls is whether a *revision* of an earlier bar
    is visible — and that choice is recorded per row via `source_revision` and
    `computed_at`, so a training set built today is distinguishable from one
    built before the revision landed.

    Bars are fetched once rather than per bar: one query instead of millions,
    with identical values.
    """
    specs = _resolve(feature_names)
    if not specs:
        raise ValidationFailedError("No features requested")

    start = _require_utc(start, "start")
    end = _require_utc(end, "end")
    if end <= start:
        raise ValidationFailedError("end must be after start")
    cutoff = _require_utc(as_of, "as_of") if as_of else datetime.now(UTC)

    warmup = max(spec.lookback for spec in specs) + LOOKBACK_MARGIN
    # Fetch warm-up history *before* `start` so the first materialized bar is
    # as well-informed as the thousandth.
    series = get_bars(
        session,
        instrument_id,
        timeframe,
        cutoff,
        start=start - timeframe.delta * (warmup + 1),
        provider_id=provider_id,
    )
    if not series:
        raise InsufficientDataError(
            "No bars available for the requested range.",
            instrument_id=str(instrument_id),
            timeframe=timeframe.value,
        )

    existing = (
        set()
        if recompute
        else _existing_keys(session, instrument_id, timeframe, specs, start, end)
    )

    written = skipped = processed = 0
    first_time = last_time = None
    now = datetime.now(UTC)

    for index, bar in enumerate(series):
        if bar.event_time < start or bar.event_time >= end:
            continue
        window = series[: index + 1]
        processed += 1
        first_time = first_time or bar.event_time
        last_time = bar.event_time

        for spec in specs:
            key = (spec.name, spec.version, bar.event_time)
            if key in existing:
                skipped += 1
                continue
            try:
                value = spec.compute(window)
            except InsufficientDataError:
                skipped += 1
                continue

            session.merge(
                FeatureValue(
                    instrument_id=instrument_id,
                    timeframe=timeframe,
                    name=spec.name,
                    feature_version=spec.version,
                    event_time=bar.event_time,
                    computed_at=now,
                    value=value,
                    source_revision=bar.revision,
                    quality_score=bar.quality_score,
                )
            )
            written += 1

    session.flush()
    log.info(
        "features.materialized",
        instrument_id=str(instrument_id),
        timeframe=timeframe.value,
        bars=processed,
        written=written,
        skipped=skipped,
    )
    return MaterializeResult(
        instrument_id=instrument_id,
        timeframe=timeframe,
        bars_processed=processed,
        values_written=written,
        values_skipped=skipped,
        features=[spec.name for spec in specs],
        first_event_time=first_time,
        last_event_time=last_time,
    )


def _existing_keys(
    session: Session,
    instrument_id: uuid.UUID,
    timeframe: Timeframe,
    specs: list[registry.FeatureSpec],
    start: datetime,
    end: datetime,
) -> set[tuple[str, int, datetime]]:
    rows = session.execute(
        select(
            FeatureValue.name, FeatureValue.feature_version, FeatureValue.event_time
        ).where(
            FeatureValue.instrument_id == instrument_id,
            FeatureValue.timeframe == timeframe,
            FeatureValue.name.in_([spec.name for spec in specs]),
            FeatureValue.event_time >= start,
            FeatureValue.event_time < end,
        )
    )
    return {(name, version, event_time) for name, version, event_time in rows}


def read_materialized(
    session: Session,
    instrument_id: uuid.UUID,
    timeframe: Timeframe,
    as_of: datetime,
    *,
    feature_names: list[str] | None = None,
    lookback: int = 200,
) -> list[FeatureRow]:
    """Stored features knowable at `as_of`, oldest first.

    `computed_at <= as_of` is enforced for the same reason `ingested_at` is on
    bars: a feature recomputed tomorrow must not appear in a decision replayed
    for today, even though the bar it describes is old.
    """
    as_of = _require_utc(as_of, "as_of")
    specs = _resolve(feature_names)
    cutoff = as_of - timeframe.delta

    conditions = [
        FeatureValue.instrument_id == instrument_id,
        FeatureValue.timeframe == timeframe,
        FeatureValue.event_time <= cutoff,
        FeatureValue.computed_at <= as_of,
        FeatureValue.name.in_([spec.name for spec in specs]),
    ]

    # Newest computation per (name, version, event_time): a re-materialization
    # after a bar revision supersedes the earlier value, but only once it was
    # actually known.
    ranked = (
        select(
            FeatureValue,
            func.row_number()
            .over(
                partition_by=(
                    FeatureValue.name,
                    FeatureValue.feature_version,
                    FeatureValue.event_time,
                ),
                order_by=FeatureValue.computed_at.desc(),
            )
            .label("rn"),
        )
        .where(and_(*conditions))
        .subquery()
    )
    latest = aliased(FeatureValue, ranked)
    rows = list(
        session.scalars(
            select(latest).where(ranked.c.rn == 1).order_by(ranked.c.event_time.desc())
        )
    )

    grouped: dict[datetime, FeatureRow] = {}
    for row in rows:
        entry = grouped.setdefault(
            row.event_time,
            FeatureRow(event_time=row.event_time, source_revision=row.source_revision),
        )
        entry.values[row.name] = float(row.value) if row.value is not None else None

    ordered = [grouped[key] for key in sorted(grouped)]
    return ordered[-lookback:]


@dataclass(frozen=True)
class Coverage:
    """What has been materialized, for the dashboard and for operators."""

    values: int
    features: int
    first_event_time: datetime | None
    last_event_time: datetime | None


def coverage(
    session: Session, instrument_id: uuid.UUID, timeframe: Timeframe
) -> Coverage:
    total, first, last, distinct = session.execute(
        select(
            func.count(FeatureValue.event_time),
            func.min(FeatureValue.event_time),
            func.max(FeatureValue.event_time),
            func.count(func.distinct(FeatureValue.name)),
        ).where(
            FeatureValue.instrument_id == instrument_id,
            FeatureValue.timeframe == timeframe,
        )
    ).one()
    return Coverage(
        values=int(total or 0),
        features=int(distinct or 0),
        first_event_time=first,
        last_event_time=last,
    )


def _require_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None:
        raise ValidationFailedError(
            f"{field_name} must be timezone-aware (UTC)", field=field_name
        )
    return value.astimezone(UTC)
