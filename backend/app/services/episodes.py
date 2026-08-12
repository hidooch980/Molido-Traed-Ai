"""Episode construction and retrieval (spec phase 10, §9).

An episode pairs *what was knowable at a moment* with *what happened next*.
The two halves come from opposite sides of the same timestamp, which makes this
the easiest place in the whole system to leak the future — and the leak is
invisible in a backtest, because the backtest is the thing being fooled.

Two rules keep it honest.

**Building.** The state half is read through `get_bars()` with `as_of` set to
the episode's own bar close, so it can only contain what had happened. The
outcome half deliberately reads *forward* — that is its purpose — but it is
written together with `outcome_ready_at`, the instant the forward window
closes.

**Reading.** `query()` filters `outcome_ready_at <= as_of`. An episode whose
outcome window is still open does not exist as far as a decision at `as_of` is
concerned. Skipping that filter is how an episode library ends up "predicting"
moves it was shown the answer to.

Outcomes are **direction-agnostic**: `max_up_pct` and `max_down_pct`, not MFE
and MAE. Favourable and adverse are undefined until something decides to be
long or short, and nothing here does. Phase 19+ maps one onto the other.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.enums import Timeframe
from app.core.errors import InsufficientDataError, ValidationFailedError
from app.core.logging import get_logger
from app.models.episodes import Episode
from app.services import feature_store
from app.services.point_in_time import BarView, get_bars
from app.services.sessions import active_sessions

log = get_logger(__name__)

BUILDER_VERSION = 1
DEFAULT_HORIZON_BARS = 24


@dataclass
class EpisodeDraft:
    event_time: datetime
    entry_price: float
    session_labels: list[str]
    features: dict[str, float | None]
    max_up_pct: float
    max_down_pct: float
    forward_return_pct: float
    bars_to_max_up: int
    bars_to_max_down: int
    outcome_bars: int
    outcome_ready_at: datetime


@dataclass
class BuildResult:
    built: int = 0
    skipped_existing: int = 0
    skipped_immature: int = 0
    first_event_time: datetime | None = None
    last_event_time: datetime | None = None
    warnings: list[str] = field(default_factory=list)

    def as_payload(self) -> dict[str, Any]:
        return {
            "built": self.built,
            "skipped_existing": self.skipped_existing,
            "skipped_immature": self.skipped_immature,
            "first_event_time": (
                self.first_event_time.isoformat() if self.first_event_time else None
            ),
            "last_event_time": (
                self.last_event_time.isoformat() if self.last_event_time else None
            ),
        }


def measure_outcome(
    entry: BarView, forward: list[BarView], timeframe: Timeframe
) -> tuple[float, float, float, int, int]:
    """Excursions over the forward window, relative to the entry close.

    Measured against highs and lows rather than closes: a move that touched
    +2% intrabar and closed flat *happened*, and a system that only reads
    closes will never learn that it was there.
    """
    base = entry.close
    max_up = 0.0
    max_down = 0.0
    bars_to_up = 0
    bars_to_down = 0

    for index, bar in enumerate(forward, start=1):
        up = (bar.high - base) / base
        down = (bar.low - base) / base
        if up > max_up:
            max_up, bars_to_up = up, index
        if down < max_down:
            max_down, bars_to_down = down, index

    forward_return = (forward[-1].close - base) / base
    return max_up, max_down, forward_return, bars_to_up, bars_to_down


def build(
    session: Session,
    instrument_id: uuid.UUID,
    timeframe: Timeframe,
    *,
    start: datetime,
    end: datetime,
    horizon_bars: int = DEFAULT_HORIZON_BARS,
    as_of: datetime | None = None,
    feature_names: list[str] | None = None,
    step: int = 1,
    recompute: bool = False,
) -> BuildResult:
    """Create episodes for bars in [start, end) whose outcome window has closed.

    `step` samples every Nth bar. Consecutive bars produce near-identical
    episodes, and a library of near-duplicates makes similarity search
    confidently wrong — it finds a hundred "matches" that are really one
    moment counted a hundred times.
    """
    if horizon_bars < 1:
        raise ValidationFailedError("horizon_bars must be at least 1")
    if step < 1:
        raise ValidationFailedError("step must be at least 1")

    start = _require_utc(start, "start")
    end = _require_utc(end, "end")
    if end <= start:
        raise ValidationFailedError("end must be after start")
    cutoff = _require_utc(as_of, "as_of") if as_of else datetime.now(UTC)

    # Warm-up before `start` so the first episode's features are as
    # well-informed as the last one's.
    warmup = feature_store.LOOKBACK_MARGIN + _max_lookback(feature_names)
    series = get_bars(
        session,
        instrument_id,
        timeframe,
        cutoff,
        start=start - timeframe.delta * (warmup + 1),
    )
    if not series:
        raise InsufficientDataError(
            "No bars available for the requested range.",
            instrument_id=str(instrument_id),
            timeframe=timeframe.value,
        )

    specs = feature_store._resolve(feature_names)

    if recompute:
        # Replace, don't duplicate. Without this the unique constraint rejects
        # the whole batch, so "recompute" would mean "crash".
        _delete_window(session, instrument_id, timeframe, horizon_bars, start, end)
        existing: set[datetime] = set()
    else:
        existing = _existing_times(
            session, instrument_id, timeframe, horizon_bars, start, end
        )

    result = BuildResult()

    for index, bar in enumerate(series):
        if bar.event_time < start or bar.event_time >= end:
            continue
        if (index % step) != 0:
            continue

        forward = series[index + 1 : index + 1 + horizon_bars]
        if len(forward) < horizon_bars:
            # The window has not closed in the data we hold. Not an error —
            # the most recent bars are simply not episodes yet.
            result.skipped_immature += 1
            continue

        outcome_ready_at = bar.event_time + timeframe.delta * (horizon_bars + 1)
        if outcome_ready_at > cutoff:
            result.skipped_immature += 1
            continue

        if bar.event_time in existing:
            result.skipped_existing += 1
            continue

        window = series[: index + 1]
        features = feature_store._compute_row(specs, window).values
        max_up, max_down, fwd, to_up, to_down = measure_outcome(bar, forward, timeframe)

        session.add(
            Episode(
                instrument_id=instrument_id,
                timeframe=timeframe,
                builder_version=BUILDER_VERSION,
                event_time=bar.event_time,
                horizon_bars=horizon_bars,
                outcome_ready_at=outcome_ready_at,
                computed_at=datetime.now(UTC),
                entry_price=bar.close,
                session_labels=[s.value for s in active_sessions(bar.event_time)],
                features={k: v for k, v in features.items() if v is not None},
                max_up_pct=max_up,
                max_down_pct=max_down,
                forward_return_pct=fwd,
                bars_to_max_up=to_up,
                bars_to_max_down=to_down,
                outcome_bars=len(forward),
            )
        )
        result.built += 1
        result.first_event_time = result.first_event_time or bar.event_time
        result.last_event_time = bar.event_time

    session.flush()
    log.info(
        "episodes.built",
        instrument_id=str(instrument_id),
        timeframe=timeframe.value,
        **result.as_payload(),
    )
    return result


def _max_lookback(feature_names: list[str] | None) -> int:
    specs = feature_store._resolve(feature_names)
    return max((spec.lookback for spec in specs), default=0)


def _delete_window(
    session: Session,
    instrument_id: uuid.UUID,
    timeframe: Timeframe,
    horizon_bars: int,
    start: datetime,
    end: datetime,
) -> int:
    from sqlalchemy import delete

    result = session.execute(
        delete(Episode).where(
            Episode.instrument_id == instrument_id,
            Episode.timeframe == timeframe,
            Episode.horizon_bars == horizon_bars,
            Episode.builder_version == BUILDER_VERSION,
            Episode.event_time >= start,
            Episode.event_time < end,
        )
    )
    session.flush()
    # `rowcount` lives on CursorResult; the ORM's execute() is typed as the
    # base Result, so the count is read defensively rather than asserted.
    return int(getattr(result, "rowcount", 0) or 0)


def _existing_times(
    session: Session,
    instrument_id: uuid.UUID,
    timeframe: Timeframe,
    horizon_bars: int,
    start: datetime,
    end: datetime,
) -> set[datetime]:
    rows = session.scalars(
        select(Episode.event_time).where(
            Episode.instrument_id == instrument_id,
            Episode.timeframe == timeframe,
            Episode.horizon_bars == horizon_bars,
            Episode.builder_version == BUILDER_VERSION,
            Episode.event_time >= start,
            Episode.event_time < end,
        )
    )
    return set(rows)


def query(
    session: Session,
    instrument_id: uuid.UUID,
    timeframe: Timeframe,
    as_of: datetime,
    *,
    horizon_bars: int | None = None,
    limit: int = 200,
    session_label: str | None = None,
) -> list[Episode]:
    """Episodes usable as evidence at `as_of`.

    The `outcome_ready_at <= as_of` filter is not an optimisation. An episode
    whose forward window is still open would hand the caller an answer that had
    not happened yet.
    """
    as_of = _require_utc(as_of, "as_of")

    conditions = [
        Episode.instrument_id == instrument_id,
        Episode.timeframe == timeframe,
        Episode.outcome_ready_at <= as_of,
        Episode.computed_at <= as_of,
    ]
    if horizon_bars is not None:
        conditions.append(Episode.horizon_bars == horizon_bars)

    rows = list(
        session.scalars(
            select(Episode)
            .where(and_(*conditions))
            .order_by(Episode.event_time.desc())
            .limit(limit)
        )
    )
    if session_label:
        rows = [r for r in rows if session_label in (r.session_labels or [])]
    return rows


def outcome_distribution(episodes: list[Episode]) -> dict[str, Any]:
    """Summarise what a set of episodes did next.

    Returns `insufficient` rather than percentages when the sample is too
    small. "60% of 5 episodes went up" is three episodes wearing a statistic.
    """
    if len(episodes) < 20:
        return {
            "sufficient": False,
            "count": len(episodes),
            "reason": "fewer than 20 matured episodes",
        }

    forwards = [float(e.forward_return_pct) for e in episodes if e.forward_return_pct is not None]
    ups = [float(e.max_up_pct) for e in episodes if e.max_up_pct is not None]
    downs = [float(e.max_down_pct) for e in episodes if e.max_down_pct is not None]

    import statistics

    positive = sum(1 for f in forwards if f > 0)
    return {
        "sufficient": True,
        "count": len(episodes),
        "positive_share": round(positive / len(forwards), 4) if forwards else None,
        "median_forward_return": round(statistics.median(forwards), 8) if forwards else None,
        "mean_max_up": round(statistics.fmean(ups), 8) if ups else None,
        "mean_max_down": round(statistics.fmean(downs), 8) if downs else None,
    }


def coverage(
    session: Session, instrument_id: uuid.UUID, timeframe: Timeframe
) -> dict[str, Any]:
    total, first, last, matured = session.execute(
        select(
            func.count(Episode.id),
            func.min(Episode.event_time),
            func.max(Episode.event_time),
            func.count(Episode.id).filter(Episode.outcome_ready_at <= datetime.now(UTC)),
        ).where(
            Episode.instrument_id == instrument_id,
            Episode.timeframe == timeframe,
        )
    ).one()
    return {
        "episodes": int(total or 0),
        "matured": int(matured or 0),
        "first_event_time": first,
        "last_event_time": last,
    }


def _require_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None:
        raise ValidationFailedError(
            f"{field_name} must be timezone-aware (UTC)", field=field_name
        )
    return value.astimezone(UTC)
