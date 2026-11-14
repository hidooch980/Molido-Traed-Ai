"""Candles, the point-in-time context, and small pure indicators.

`make_context` is the only constructor and it drops every bar that had not
closed by `as_of` - an H1 bar opening 10:00 is invisible at 10:30. Swing
points need `k` closed bars on each side, so a swing is confirmed late, never
early: that delay is the price of not looking ahead.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.agents.messages import Market


@dataclass(frozen=True)
class Candle:
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0  # tick volume where that is all the broker has
    spread: float | None = None  # in price units


@dataclass(frozen=True)
class AnalysisContext:
    symbol: str
    market: Market
    timeframe: str
    bar_delta: timedelta
    as_of: datetime
    bars: tuple[Candle, ...]
    spread: float | None = None
    minutes_to_high_impact: float | None = None
    extras: dict = field(default_factory=dict)

    @property
    def closes(self) -> list[float]:
        return [b.close for b in self.bars]

    @property
    def source(self) -> str:
        return f"bars:{self.symbol}:{self.timeframe}"


def make_context(symbol: str, market: Market, timeframe: str, bar_delta: timedelta,
                 bars: list[Candle], as_of: datetime, **kw: object) -> AnalysisContext:
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    as_of = as_of.astimezone(UTC)
    visible = tuple(sorted((b for b in bars if b.open_time + bar_delta <= as_of),
                           key=lambda b: b.open_time))
    return AnalysisContext(symbol.upper(), market, timeframe, bar_delta, as_of, visible,
                           **kw)  # type: ignore[arg-type]


def true_ranges(bars: tuple[Candle, ...] | list[Candle]) -> list[float]:
    out: list[float] = []
    for i, b in enumerate(bars):
        prev = bars[i - 1].close if i else b.close
        out.append(max(b.high - b.low, abs(b.high - prev), abs(b.low - prev)))
    return out


def atr(bars: tuple[Candle, ...] | list[Candle], n: int = 14) -> float | None:
    tr = true_ranges(bars)
    if len(tr) < n + 1:
        return None
    return sum(tr[-n:]) / n


def ema(values: list[float], n: int) -> float | None:
    if len(values) < n:
        return None
    k = 2 / (n + 1)
    e = sum(values[:n]) / n
    for v in values[n:]:
        e = v * k + e * (1 - k)
    return e


def zscore(values: list[float], n: int = 20) -> float | None:
    if len(values) < n:
        return None
    window = values[-n:]
    sd = statistics.pstdev(window)
    return None if sd == 0 else (window[-1] - statistics.fmean(window)) / sd


def swings(bars: tuple[Candle, ...], k: int = 2) -> tuple[list[int], list[int]]:
    """Indices of confirmed swing highs and lows (k closed bars each side)."""
    highs, lows = [], []
    for i in range(k, len(bars) - k):
        window = bars[i - k : i + k + 1]
        if bars[i].high == max(b.high for b in window) and \
                sum(1 for b in window if b.high == bars[i].high) == 1:
            highs.append(i)
        if bars[i].low == min(b.low for b in window) and \
                sum(1 for b in window if b.low == bars[i].low) == 1:
            lows.append(i)
    return highs, lows


def session_names(moment: datetime) -> list[str]:
    """Liquidity sessions by UTC hour (approximate, DST-agnostic)."""
    h = moment.astimezone(UTC).hour
    names = []
    if h >= 21 or h < 6:
        names.append("sydney")
    if 0 <= h < 9:
        names.append("tokyo")
    if 7 <= h < 16:
        names.append("london")
    if 12 <= h < 21:
        names.append("new_york")
    return names


def safe_ratio(a: float, b: float | None) -> float | None:
    if b is None or b == 0 or math.isnan(b):
        return None
    return a / b
