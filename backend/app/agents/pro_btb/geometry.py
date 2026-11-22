"""Deterministic bar geometry used by every stage. No trading decisions."""

from __future__ import annotations

from collections.abc import Sequence

from app.agents.analyzers.bars import Candle, atr, swings
from app.agents.pro_btb.params import ProBtbParams
from app.agents.pro_btb.types import CycleLabel, Direction


def require_atr(bars: Sequence[Candle], params: ProBtbParams) -> float | None:
    return atr(tuple(bars), params.atr_period)


def overlap_ratio(bars: Sequence[Candle]) -> float:
    if len(bars) < 2:
        return 0.0
    ratios: list[float] = []
    for prev, cur in zip(bars, bars[1:], strict=False):
        left, right = max(prev.low, cur.low), min(prev.high, cur.high)
        overlap = max(0.0, right - left)
        denom = max(cur.high - cur.low, 1e-12)
        ratios.append(overlap / denom)
    return sum(ratios) / len(ratios)


def body_ratio(bars: Sequence[Candle], direction: Direction) -> float:
    if not bars:
        return 0.0
    signed = 0.0
    total = 0.0
    for bar in bars:
        rng = bar.high - bar.low
        total += max(rng, 1e-12)
        body = bar.close - bar.open
        if direction is Direction.BULL:
            signed += max(body, 0.0)
        elif direction is Direction.BEAR:
            signed += max(-body, 0.0)
    return signed / total if total else 0.0


def displacement(start: float, end: float) -> float:
    return abs(end - start)


def single_bar_share(bars: Sequence[Candle], direction: Direction) -> float:
    if not bars:
        return 0.0
    moves = []
    for bar in bars:
        signed = (bar.close - bar.open) if direction is Direction.BULL else (bar.open - bar.close)
        moves.append(signed)
    total = sum(max(m, 0.0) for m in moves)
    if total <= 0:
        return 0.0
    return max(max(m, 0.0) for m in moves) / total


def two_sided_score(bars: Sequence[Candle]) -> float:
    """0 means perfectly two-sided; 0.5 means all bars close in one direction."""
    if not bars:
        return 0.0
    ups = sum(1 for b in bars if b.close > b.open)
    return abs(ups / len(bars) - 0.5)


def classify_window(
    bars: Sequence[Candle], params: ProBtbParams, last_atr: float | None,
) -> CycleLabel:
    """RESEARCH thresholds. Labels a window as SP, CH, TR, or UNKNOWN."""
    if len(bars) < 2 or last_atr is None or last_atr <= 0:
        return CycleLabel.UNKNOWN
    net = displacement(bars[0].open, bars[-1].close)
    ov = overlap_ratio(bars)
    n = len(bars)
    sided = two_sided_score(bars)
    spike_like = (
        n <= params.spike_max_bars
        and net / last_atr >= params.spike_min_atr
        and ov <= params.spike_max_overlap
    )
    if spike_like:
        return CycleLabel.SPIKE
    if sided < params.range_two_sided_max and ov >= params.range_min_overlap:
        return CycleLabel.TRADING_RANGE
    channel_like = (
        n >= params.channel_min_bars
        and ov <= params.channel_max_overlap
        and sided >= params.range_two_sided_max
    )
    if channel_like:
        return CycleLabel.CHANNEL
    return CycleLabel.UNKNOWN


def last_swings(bars: Sequence[Candle], params: ProBtbParams) -> tuple[list[int], list[int]]:
    return swings(tuple(bars), params.swing_k)


def microchannel(bars: Sequence[Candle], direction: Direction, needed: int) -> bool:
    if needed < 2 or len(bars) < needed:
        return False
    window = list(bars)[-needed:]
    if direction is Direction.BULL:
        return all(window[i].low > window[i - 1].low for i in range(1, len(window)))
    if direction is Direction.BEAR:
        return all(window[i].high < window[i - 1].high for i in range(1, len(window)))
    return False


def close_at_extreme(bar: Candle, direction: Direction, frac: float) -> bool:
    rng = bar.high - bar.low
    if rng <= 0:
        return False
    if direction is Direction.BULL:
        return (bar.high - bar.close) / rng <= frac
    if direction is Direction.BEAR:
        return (bar.close - bar.low) / rng <= frac
    return False
