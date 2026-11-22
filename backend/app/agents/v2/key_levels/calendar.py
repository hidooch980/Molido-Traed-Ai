"""NY trading-day calendar. Cutover is 17:00 America/New_York, DST-aware.

The 17:00 New York rollover is the conventional FX daily close (the market
does not fully shut on weekdays). Weekend: last close is Friday 17:00; the
next day starts Sunday 17:00. Sources are cited in docs/v2-engines-fa.md.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.agents.analyzers.bars import Candle

NY = ZoneInfo("America/New_York")
CUTOVER_HOUR = 17


def to_ny(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return moment.astimezone(NY)


def _at_cutover(local: datetime) -> datetime:
    return local.replace(hour=CUTOVER_HOUR, minute=0, second=0, microsecond=0)


def is_weekday_close(local: datetime) -> bool:
    """Monday–Friday 17:00 NY are daily closes. Saturday/Sunday 17:00 are not."""
    return local.weekday() < 5 and local.hour == CUTOVER_HOUR and local.minute == 0 \
        and local.second == 0 and local.microsecond == 0


def last_completed_close(as_of: datetime) -> datetime:
    """Most recent Friday-or-weekday 17:00 NY that is <= as_of."""
    local = to_ny(as_of)
    candidate = _at_cutover(local)
    if local < candidate:
        candidate -= timedelta(days=1)
        candidate = _at_cutover(candidate)
    while candidate.weekday() >= 5:  # Sat/Sun have no daily close
        candidate -= timedelta(days=1)
        candidate = _at_cutover(candidate)
    return candidate


def day_open(close: datetime) -> datetime:
    """Start of the trading day that ends at `close` (itself a weekday 17:00 NY)."""
    close_ny = to_ny(close)
    start = _at_cutover(close_ny - timedelta(days=1))
    return start


def bar_close_time(bar: Candle, bar_delta) -> datetime:
    return bar.open_time + bar_delta


def visible_bars(
    bars: list[Candle] | tuple[Candle, ...], as_of: datetime, bar_delta,
) -> tuple[Candle, ...]:
    """Drop every bar that had not closed by as_of (no look-ahead)."""
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    return tuple(b for b in bars if bar_close_time(b, bar_delta) <= as_of)


def bars_in_window(
    bars: tuple[Candle, ...],
    start: datetime,
    end: datetime,
    bar_delta,
) -> tuple[Candle, ...]:
    """Bars whose close falls in (start, end]. Comparisons are timezone-safe."""
    out = []
    for bar in bars:
        close = bar_close_time(bar, bar_delta)
        if start < close <= end:
            out.append(bar)
    return tuple(out)
