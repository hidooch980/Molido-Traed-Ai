"""Completed and developing daily H/L, plus sweep / breakout / reversal flags."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.agents.analyzers.bars import Candle
from app.agents.v2.key_levels.calendar import (
    bar_close_time,
    bars_in_window,
    day_open,
    last_completed_close,
)


@dataclass(frozen=True)
class DayRange:
    start: datetime
    end: datetime
    high: float | None
    low: float | None
    close: float | None
    complete: bool
    bar_count: int

    def as_dict(self) -> dict:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "complete": self.complete,
            "bar_count": self.bar_count,
        }


@dataclass(frozen=True)
class LevelReaction:
    kind: str  # sweep, breakout, reversal
    side: str  # high or low
    level: float
    bar_index: int
    reasons: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "kind": self.kind, "side": self.side, "level": self.level,
            "bar_index": self.bar_index, "reasons": list(self.reasons),
        }


def range_from_bars(
    window: Sequence[Candle], start: datetime, end: datetime, *, complete: bool,
) -> DayRange:
    if not window:
        return DayRange(start, end, None, None, None, complete, 0)
    return DayRange(
        start, end,
        high=max(b.high for b in window),
        low=min(b.low for b in window),
        close=window[-1].close,
        complete=complete,
        bar_count=len(window),
    )


def completed_day(bars: tuple[Candle, ...], as_of: datetime, bar_delta) -> DayRange:
    close = last_completed_close(as_of)
    start = day_open(close)
    window = bars_in_window(bars, start, close, bar_delta)
    return range_from_bars(window, start, close, complete=True)


def developing_day(bars: tuple[Candle, ...], as_of: datetime, bar_delta) -> DayRange:
    start = last_completed_close(as_of)
    window = bars_in_window(bars, start, as_of, bar_delta)
    return range_from_bars(window, start, as_of, complete=False)


def previous_ny_close(
    bars: tuple[Candle, ...], as_of: datetime, bar_delta,
) -> tuple[float | None, datetime]:
    close_at = last_completed_close(as_of)
    start = day_open(close_at)
    window = bars_in_window(bars, start, close_at, bar_delta)
    if not window:
        return None, close_at
    # Prefer the bar whose close is exactly at the cutover; otherwise the last
    # closed bar of that trading day (still no look-ahead: window is filtered).
    exact = [b for b in window if bar_close_time(b, bar_delta) == close_at]
    chosen = exact[-1] if exact else window[-1]
    return chosen.close, close_at


def reactions_to_completed(
    bars: tuple[Candle, ...],
    completed: DayRange,
    as_of: datetime,
    bar_delta,
) -> tuple[LevelReaction, ...]:
    """Sweep / breakout / reversal of the *completed* day's H/L, on later bars."""
    if not completed.complete or completed.high is None or completed.low is None:
        return ()
    later = [b for b in bars if bar_close_time(b, bar_delta) > completed.end
             and bar_close_time(b, bar_delta) <= as_of]
    out: list[LevelReaction] = []
    swept_high = swept_low = False
    for i, bar in enumerate(later):
        # Index is against the original `bars` tuple for traceability.
        try:
            index = bars.index(bar)
        except ValueError:
            index = i
        if bar.high > completed.high and bar.close <= completed.high:
            swept_high = True
            out.append(LevelReaction(
                "sweep", "high", completed.high, index,
                (f"wick {bar.high} above daily high {completed.high}, close back inside",),
            ))
        if bar.close > completed.high:
            out.append(LevelReaction(
                "breakout", "high", completed.high, index,
                (f"close {bar.close} above daily high {completed.high}",),
            ))
        if swept_high and bar.close < completed.high:
            out.append(LevelReaction(
                "reversal", "high", completed.high, index,
                ("close back below the swept daily high",),
            ))
        if bar.low < completed.low and bar.close >= completed.low:
            swept_low = True
            out.append(LevelReaction(
                "sweep", "low", completed.low, index,
                (f"wick {bar.low} below daily low {completed.low}, close back inside",),
            ))
        if bar.close < completed.low:
            out.append(LevelReaction(
                "breakout", "low", completed.low, index,
                (f"close {bar.close} below daily low {completed.low}",),
            ))
        if swept_low and bar.close > completed.low:
            out.append(LevelReaction(
                "reversal", "low", completed.low, index,
                ("close back above the swept daily low",),
            ))
    return tuple(out)


# timedelta imported only if needed - actually unused, I'll remove if ruff complains
