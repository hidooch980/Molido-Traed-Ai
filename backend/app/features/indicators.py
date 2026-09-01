"""Baseline feature set.

Chosen to describe *market state* rather than to generate signals — trend,
volatility, momentum, range and position-within-range. Signal logic belongs to
the strategy engine (phase 19); mixing the two here would bake one trading
opinion into the data layer that every later model is forced to inherit.

Every function is pure and reads only the window it is given. None of them
looks at `bars[-1]`'s future, because there isn't one: the last element *is*
the bar being described.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence

from app.features.base import feature
from app.services.point_in_time import BarView


def _closes(bars: Sequence[BarView]) -> list[float]:
    return [b.close for b in bars]


def _true_ranges(bars: Sequence[BarView]) -> list[float]:
    """Wilder's true range, which accounts for gaps between bars."""
    out: list[float] = []
    for previous, current in zip(bars, bars[1:], strict=False):
        out.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    return out


# ------------------------------------------------------------------- returns
@feature("return_1", lookback=1, description="Log return over one bar.")
def return_1(bars: Sequence[BarView]) -> float | None:
    previous, current = bars[-2].close, bars[-1].close
    if previous <= 0 or current <= 0:
        return None
    import math

    return math.log(current / previous)


@feature("return_5", lookback=5, description="Log return over five bars.")
def return_5(bars: Sequence[BarView]) -> float | None:
    import math

    previous, current = bars[-6].close, bars[-1].close
    if previous <= 0 or current <= 0:
        return None
    return math.log(current / previous)


# --------------------------------------------------------------------- trend
@feature("sma_20", lookback=19, description="20-bar simple moving average.")
def sma_20(bars: Sequence[BarView]) -> float | None:
    return statistics.fmean(_closes(bars[-20:]))


@feature("ema_20", lookback=59, description="20-bar exponential moving average.")
def ema_20(bars: Sequence[BarView]) -> float | None:
    """Seeded with an SMA and warmed over 3x the period.

    An EMA is technically infinite-memory; seeding it from an arbitrary start
    point makes the value depend on where the window happened to begin, which
    would break reproducibility. Three periods of warm-up puts the seeding
    error well below rounding.
    """
    period = 20
    closes = _closes(bars)
    alpha = 2 / (period + 1)
    value = statistics.fmean(closes[:period])
    for close in closes[period:]:
        value = alpha * close + (1 - alpha) * value
    return value


@feature(
    "close_over_sma_20",
    lookback=19,
    description="Close divided by its 20-bar SMA; >1 means above trend.",
)
def close_over_sma_20(bars: Sequence[BarView]) -> float | None:
    average = statistics.fmean(_closes(bars[-20:]))
    if average <= 0:
        return None
    return bars[-1].close / average


# ---------------------------------------------------------------- volatility
@feature("atr_14", lookback=14, description="14-bar average true range.")
def atr_14(bars: Sequence[BarView]) -> float | None:
    ranges = _true_ranges(bars[-15:])
    return statistics.fmean(ranges) if ranges else None


@feature(
    "atr_14_pct",
    lookback=14,
    description="ATR(14) as a fraction of price — comparable across instruments.",
)
def atr_14_pct(bars: Sequence[BarView]) -> float | None:
    ranges = _true_ranges(bars[-15:])
    close = bars[-1].close
    if not ranges or close <= 0:
        return None
    return statistics.fmean(ranges) / close


@feature(
    "realized_vol_20",
    lookback=20,
    description="Standard deviation of the last 20 log returns.",
)
def realized_vol_20(bars: Sequence[BarView]) -> float | None:
    import math

    closes = _closes(bars[-21:])
    returns = [
        math.log(b / a) for a, b in zip(closes, closes[1:], strict=False) if a > 0 and b > 0
    ]
    if len(returns) < 2:
        return None
    return statistics.pstdev(returns)


# ------------------------------------------------------------------ momentum
@feature("rsi_14", lookback=14, description="Wilder's RSI over 14 bars.")
def rsi_14(bars: Sequence[BarView]) -> float | None:
    closes = _closes(bars[-15:])
    gains, losses = [], []
    for previous, current in zip(closes, closes[1:], strict=False):
        change = current - previous
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = statistics.fmean(gains)
    avg_loss = statistics.fmean(losses)
    if avg_loss == 0:
        # All-up window. RSI is 100 by definition, not undefined.
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


# --------------------------------------------------------------------- range
@feature(
    "position_in_range_20",
    lookback=19,
    description="Where the close sits in the 20-bar high/low range: 0 = low, 1 = high.",
)
def position_in_range_20(bars: Sequence[BarView]) -> float | None:
    window = bars[-20:]
    high = max(b.high for b in window)
    low = min(b.low for b in window)
    if high <= low:
        return None  # a flat window has no meaningful position
    return (bars[-1].close - low) / (high - low)


@feature(
    "bar_range_pct",
    lookback=0,
    description="This bar's high-low range as a fraction of its close.",
)
def bar_range_pct(bars: Sequence[BarView]) -> float | None:
    bar = bars[-1]
    if bar.close <= 0:
        return None
    return (bar.high - bar.low) / bar.close


@feature(
    "body_ratio",
    lookback=0,
    description="Candle body as a fraction of its full range; 0 = doji.",
)
def body_ratio(bars: Sequence[BarView]) -> float | None:
    bar = bars[-1]
    span = bar.high - bar.low
    if span <= 0:
        return None
    return abs(bar.close - bar.open) / span


# ---------------------------------------------------------- classic indicators
#
# The widely-watched set, added as *state descriptors* like everything above:
# each publishes the number traders quote, not a buy/sell opinion. Signal
# logic stays in the brains, where it can be measured and refused.


def _ema(values: Sequence[float], period: int) -> float:
    alpha = 2.0 / (period + 1)
    out = values[0]
    for value in values[1:]:
        out = alpha * value + (1 - alpha) * out
    return out


@feature(
    "macd_hist_12_26_9",
    lookback=59,
    description="MACD histogram (12/26 EMA minus its 9-EMA signal).",
)
def macd_hist(bars: Sequence[BarView]) -> float | None:
    closes = _closes(bars[-60:])
    if len(closes) < 35:
        return None
    macd_line = [
        _ema(closes[: i + 1], 12) - _ema(closes[: i + 1], 26)
        for i in range(25, len(closes))
    ]
    if len(macd_line) < 9:
        return None
    return macd_line[-1] - _ema(macd_line, 9)


@feature(
    "bollinger_position_20",
    lookback=19,
    description="Close within the 20-bar 2-sigma bands: 0 lower, 0.5 mid, 1 upper.",
)
def bollinger_position(bars: Sequence[BarView]) -> float | None:
    closes = _closes(bars[-20:])
    mean = statistics.fmean(closes)
    spread = statistics.pstdev(closes)
    if spread == 0:
        return 0.5
    lower, upper = mean - 2 * spread, mean + 2 * spread
    return (closes[-1] - lower) / (upper - lower)


@feature(
    "bollinger_width_20",
    lookback=19,
    description="20-bar 2-sigma band width as a fraction of the mean (squeeze gauge).",
)
def bollinger_width(bars: Sequence[BarView]) -> float | None:
    closes = _closes(bars[-20:])
    mean = statistics.fmean(closes)
    if mean == 0:
        return None
    return 4 * statistics.pstdev(closes) / mean


@feature(
    "stochastic_k_14",
    lookback=13,
    description="Stochastic %K over 14 bars: close within the high/low range.",
)
def stochastic_k(bars: Sequence[BarView]) -> float | None:
    window = bars[-14:]
    highest = max(b.high for b in window)
    lowest = min(b.low for b in window)
    if highest == lowest:
        return 50.0
    return 100 * (window[-1].close - lowest) / (highest - lowest)


@feature(
    "adx_14",
    lookback=27,
    description="Wilder's ADX(14): trend strength, direction-blind.",
)
def adx_14(bars: Sequence[BarView]) -> float | None:
    window = bars[-28:]
    plus_dm, minus_dm = [], []
    for previous, current in zip(window, window[1:], strict=False):
        up = current.high - previous.high
        down = previous.low - current.low
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
    ranges = _true_ranges(window)
    dxs = []
    for i in range(13, len(ranges)):
        tr = sum(ranges[i - 13 : i + 1])
        if tr == 0:
            continue
        plus = 100 * sum(plus_dm[i - 13 : i + 1]) / tr
        minus = 100 * sum(minus_dm[i - 13 : i + 1]) / tr
        if plus + minus == 0:
            continue
        dxs.append(100 * abs(plus - minus) / (plus + minus))
    if not dxs:
        return None
    return statistics.fmean(dxs)


@feature("sma_50", lookback=49, description="50-bar simple moving average.")
def sma_50(bars: Sequence[BarView]) -> float | None:
    return statistics.fmean(_closes(bars[-50:]))


@feature("sma_200", lookback=199, description="200-bar simple moving average.")
def sma_200(bars: Sequence[BarView]) -> float | None:
    return statistics.fmean(_closes(bars[-200:]))


@feature(
    "sma_50_over_200",
    lookback=199,
    description="SMA50/SMA200; >1 is the golden-cross side, <1 the death-cross side.",
)
def sma_50_over_200(bars: Sequence[BarView]) -> float | None:
    closes = _closes(bars[-200:])
    slow = statistics.fmean(closes)
    fast = statistics.fmean(closes[-50:])
    if slow == 0:
        return None
    return fast / slow


@feature(
    "roc_20",
    lookback=20,
    description="Rate of change over 20 bars, as a fraction.",
)
def roc_20(bars: Sequence[BarView]) -> float | None:
    closes = _closes(bars[-21:])
    if closes[0] == 0:
        return None
    return closes[-1] / closes[0] - 1


@feature(
    "donchian_position_55",
    lookback=54,
    description="Close within the 55-bar Donchian channel: 0 low, 1 high.",
)
def donchian_position(bars: Sequence[BarView]) -> float | None:
    window = bars[-55:]
    highest = max(b.high for b in window)
    lowest = min(b.low for b in window)
    if highest == lowest:
        return 0.5
    return (window[-1].close - lowest) / (highest - lowest)


__all__ = [
    "atr_14",
    "atr_14_pct",
    "bar_range_pct",
    "body_ratio",
    "close_over_sma_20",
    "ema_20",
    "position_in_range_20",
    "realized_vol_20",
    "return_1",
    "return_5",
    "adx_14",
    "bollinger_position",
    "bollinger_width",
    "donchian_position",
    "macd_hist",
    "roc_20",
    "sma_50",
    "sma_200",
    "sma_50_over_200",
    "stochastic_k",
    "rsi_14",
    "sma_20",
]
