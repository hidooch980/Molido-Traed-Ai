"""Point-in-time reads (spec §6).

This module is the single door to historical market data. Every downstream
phase — features, memory, episodes, backtests, training — must read through
`get_bars()` and never query `ohlcv` directly. Concentrating the rule in one
place is what makes "no lookahead" a testable property instead of a hope.

Two independent filters are applied, and both matter:

1. **Bar closure.** A bar is visible only once it has *closed* at or before
   `as_of`. Its open timestamp being in the past is not enough: an H1 bar
   opening at 10:00 still contains prices from 10:59, so at 10:30 it is future
   information.

2. **Knowledge time.** A row is visible only if `ingested_at <= as_of`. A
   correction backfilled tomorrow must not appear in a decision reconstructed
   for today, even though its `event_time` is old. Where several revisions of
   the same bar were known by `as_of`, the newest such revision wins.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, and_, func, select
from sqlalchemy.orm import Session, aliased

from app.core.config import get_settings
from app.core.enums import Timeframe
from app.core.errors import InsufficientDataError, LookaheadViolationError, ValidationFailedError
from app.models.ingestion import DatasetQuality
from app.models.market_data import Bar


@dataclass(frozen=True)
class BarView:
    """An immutable, as-of-correct bar."""

    instrument_id: uuid.UUID
    provider_id: uuid.UUID
    timeframe: Timeframe
    event_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    tick_volume: float | None
    spread: float | None
    revision: int
    ingested_at: datetime
    quality_score: float


def _require_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None:
        raise ValidationFailedError(f"{field} must be timezone-aware (UTC)", field=field)
    return value.astimezone(UTC)


def _visible_bars_query(
    instrument_id: uuid.UUID,
    timeframe: Timeframe,
    as_of: datetime,
    provider_id: uuid.UUID | None,
    start: datetime | None = None,
    lookback: int | None = None,
) -> Select:
    """Rows visible at `as_of`, newest known revision per event_time.

    A window function collapses revisions rather than Postgres' DISTINCT ON, so
    the same query runs on SQLite in tests. The visibility filters are applied
    *inside* the window, which matters: ranking first and filtering afterwards
    would let an unknown-yet revision hide the revision that was actually
    current at `as_of`.

    **`lookback` is pushed into the window rather than left to the caller's
    LIMIT**, and the difference is three seconds a page. A window function is
    computed over every row the WHERE admits before any outer LIMIT can
    discard one, so asking for the last two bars ranked an instrument's entire
    history - twelve thousand rows at H1 - to return two. The world-state
    endpoint spent 3.4 of its 7.5 seconds here, and the price block it was
    waiting on had asked for `lookback=2`.

    Narrowing by the newest `lookback` *event times* rather than rows is what
    makes it exactly equivalent. Several providers can cover one timestamp, so
    a row limit and a timestamp limit are different numbers - but the newest N
    rows by event_time can never span more than N distinct event times, so the
    rows the outer LIMIT would have kept are all still here.
    """
    cutoff = as_of - timeframe.delta  # last bar whose close is <= as_of

    conditions = [
        Bar.instrument_id == instrument_id,
        Bar.timeframe == timeframe,
        Bar.event_time <= cutoff,
        Bar.ingested_at <= as_of,
    ]
    if provider_id is not None:
        conditions.append(Bar.provider_id == provider_id)
    if start is not None:
        conditions.append(Bar.event_time >= start)

    if lookback is not None:
        # Built from `conditions` as it stands, before this clause joins them:
        # the horizon has to see the same visibility rules, and must not see
        # itself.
        horizon = (
            select(Bar.event_time)
            .where(and_(*conditions))
            .distinct()
            .order_by(Bar.event_time.desc())
            .limit(lookback)
            # Never correlated with the enclosing query. SQLAlchemy leaves
            # this uncorrelated anyway - auto-correlation is skipped when it
            # would empty the subquery's FROM - but that protection is a
            # documented edge of the ORM, not a property of this code, and a
            # correlated rendering would silently turn the whole bound into
            # `event_time IN (event_time)`: always true, nothing narrowed,
            # and every test still green because the outer LIMIT keeps the
            # answer identical while the three seconds quietly come back.
            .correlate(None)
            .scalar_subquery()
        )
        conditions.append(Bar.event_time.in_(horizon))

    ranked = (
        select(
            Bar,
            func.row_number()
            .over(
                partition_by=(Bar.instrument_id, Bar.timeframe, Bar.provider_id, Bar.event_time),
                order_by=(Bar.revision.desc(), Bar.ingested_at.desc()),
            )
            .label("rn"),
        )
        .where(and_(*conditions))
        .subquery()
    )
    latest = aliased(Bar, ranked)
    return select(latest).where(ranked.c.rn == 1).order_by(ranked.c.event_time.desc())


def get_bars(
    session: Session,
    instrument_id: uuid.UUID,
    timeframe: Timeframe,
    as_of: datetime,
    *,
    lookback: int | None = None,
    start: datetime | None = None,
    provider_id: uuid.UUID | None = None,
    require_training_eligible: bool = False,
    min_bars: int | None = None,
) -> list[BarView]:
    """Return bars knowable at `as_of`, oldest first.

    `lookback` caps the number of most-recent bars; `start` sets an inclusive
    lower bound on event_time. `min_bars` turns "not enough history" into an
    explicit `InsufficientDataError` instead of a short list that a caller
    might silently treat as sufficient.

    With `provider_id` omitted and several providers covering the instrument,
    each provider's view of a timestamp is returned separately. Silently
    picking one would be a hidden editorial decision about which feed to
    believe; that choice belongs to the caller (or to the provider-conflict
    detector), not to this function.
    """
    as_of = _require_utc(as_of, "as_of")
    settings = get_settings()

    if settings.max_asof_age_days > 0:
        age_days = (datetime.now(UTC) - as_of).days
        if age_days > settings.max_asof_age_days:
            raise ValidationFailedError(
                "as_of is older than the configured historical read limit",
                as_of=as_of.isoformat(),
                max_age_days=settings.max_asof_age_days,
            )

    if require_training_eligible and not is_training_eligible(
        session, instrument_id, timeframe, provider_id=provider_id
    ):
        raise InsufficientDataError(
            "Dataset is not eligible for training reads (quality gate).",
            instrument_id=str(instrument_id),
            timeframe=timeframe.value,
        )

    if lookback is not None and lookback <= 0:
        raise ValidationFailedError("lookback must be positive", lookback=lookback)

    start = _require_utc(start, "start") if start is not None else None

    def _run(lower: datetime | None) -> list:
        query = _visible_bars_query(
            instrument_id,
            timeframe,
            as_of,
            provider_id,
            start=lower,
            lookback=lookback,
        )
        if lookback is not None:
            # Still applied. The horizon bounds the scan to the right
            # timestamps; this bounds the rows, which differ when two
            # providers cover one.
            query = query.limit(lookback)
        return list(session.scalars(query))

    if lookback is not None and start is None:
        # A recency probe before the unbounded read, because the bars table is
        # a hypertable in production. Without a lower time bound the planner
        # must consider every chunk - 264 of them - and "the last two bars"
        # costs seconds of planning to return two rows. A window generous
        # enough for weekends and holidays satisfies almost every call from
        # one or two recent chunks; the unbounded query runs only when the
        # probe comes back short, which keeps the answer exactly what it was -
        # an instrument quiet for months still reports its old bars rather
        # than none.
        window = max(lookback * timeframe.delta * 4, timedelta(days=14))
        rows = _run(as_of - window)
        if len(rows) < lookback:
            rows = _run(None)
    else:
        rows = _run(start)
    rows.reverse()  # query is newest-first for LIMIT; callers want chronological

    bars = [
        BarView(
            instrument_id=row.instrument_id,
            provider_id=row.provider_id,
            timeframe=Timeframe(row.timeframe),
            event_time=row.event_time,
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume) if row.volume is not None else None,
            tick_volume=float(row.tick_volume) if row.tick_volume is not None else None,
            spread=float(row.spread) if row.spread is not None else None,
            revision=row.revision,
            ingested_at=row.ingested_at,
            quality_score=float(row.quality_score),
        )
        for row in rows
    ]

    # Defence in depth: the invariant is asserted, not merely intended. If a
    # future index hint or query rewrite breaks it, this fails loudly here
    # rather than quietly poisoning a backtest.
    _assert_no_lookahead(bars, as_of, timeframe)

    if min_bars is not None and len(bars) < min_bars:
        raise InsufficientDataError(
            "Not enough history available at the requested timestamp.",
            required=min_bars,
            available=len(bars),
            as_of=as_of.isoformat(),
            instrument_id=str(instrument_id),
            timeframe=timeframe.value,
        )
    return bars


def _assert_no_lookahead(bars: list[BarView], as_of: datetime, timeframe: Timeframe) -> None:
    for bar in bars:
        if bar.event_time + timeframe.delta > as_of:
            raise LookaheadViolationError(
                "Bar had not closed at as_of.",
                event_time=bar.event_time.isoformat(),
                as_of=as_of.isoformat(),
            )
        if bar.ingested_at > as_of:
            raise LookaheadViolationError(
                "Bar was not yet known at as_of.",
                ingested_at=bar.ingested_at.isoformat(),
                as_of=as_of.isoformat(),
            )


def latest_bar(
    session: Session,
    instrument_id: uuid.UUID,
    timeframe: Timeframe,
    as_of: datetime,
    *,
    provider_id: uuid.UUID | None = None,
) -> BarView | None:
    bars = get_bars(
        session, instrument_id, timeframe, as_of, lookback=1, provider_id=provider_id
    )
    return bars[-1] if bars else None


def data_freshness_seconds(
    session: Session,
    instrument_id: uuid.UUID,
    timeframe: Timeframe,
    *,
    now: datetime | None = None,
    provider_id: uuid.UUID | None = None,
) -> float | None:
    """Age of the newest closed bar, in seconds. None when there is no data.

    Feeds the market-data failure policy (spec §40): stale data means no new
    trade, so freshness must be measurable, not assumed.
    """
    now = _require_utc(now or datetime.now(UTC), "now")
    bar = latest_bar(session, instrument_id, timeframe, now, provider_id=provider_id)
    if bar is None:
        return None
    return (now - (bar.event_time + timeframe.delta)).total_seconds()


def is_training_eligible(
    session: Session,
    instrument_id: uuid.UUID,
    timeframe: Timeframe,
    *,
    provider_id: uuid.UUID | None = None,
) -> bool:
    """Whether the dataset passed the quality gate (spec §5).

    Absence of an evaluation is not eligibility: an unevaluated dataset is
    treated as ineligible.
    """
    conditions = [
        DatasetQuality.instrument_id == instrument_id,
        DatasetQuality.timeframe == timeframe,
    ]
    if provider_id is not None:
        conditions.append(DatasetQuality.provider_id == provider_id)

    records = list(session.scalars(select(DatasetQuality).where(and_(*conditions))))
    if not records:
        return False
    return any(record.is_training_eligible for record in records)
