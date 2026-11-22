"""Stage 1: Strong Leg Assessment. Independent detector."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.agents.analyzers.bars import Candle
from app.agents.pro_btb.geometry import (
    body_ratio,
    displacement,
    last_swings,
    overlap_ratio,
    require_atr,
    single_bar_share,
)
from app.agents.pro_btb.params import ProBtbParams
from app.agents.pro_btb.types import Direction, PipelineDecision, StageSnapshot


@dataclass(frozen=True)
class StrongLegResult:
    valid: bool
    stopped: bool
    high_risk: bool
    direction: Direction
    start_index: int | None
    end_index: int | None
    start_price: float | None
    end_price: float | None
    length_atr: float | None
    reasons: tuple[str, ...]
    metrics: dict[str, float]

    def snapshot(self) -> StageSnapshot:
        decision = PipelineDecision.STOP if self.stopped else PipelineDecision.CONTINUE
        return StageSnapshot(
            stage="strong_leg",
            valid=self.valid,
            decision=decision,
            reasons=self.reasons,
            details={
                "high_risk": self.high_risk,
                "direction": self.direction.value,
                "start_index": self.start_index,
                "end_index": self.end_index,
                "start_price": self.start_price,
                "end_price": self.end_price,
                "length_atr": self.length_atr,
                "metrics": self.metrics,
            },
        )


def _stop(reasons: list[str], metrics: dict[str, float] | None = None) -> StrongLegResult:
    return StrongLegResult(
        valid=False, stopped=True, high_risk=False, direction=Direction.NONE,
        start_index=None, end_index=None, start_price=None, end_price=None,
        length_atr=None, reasons=tuple(reasons), metrics=metrics or {},
    )


def _evaluate_leg(
    bars: Sequence[Candle],
    start_i: int,
    end_i: int,
    direction: Direction,
    last_atr: float,
    params: ProBtbParams,
) -> StrongLegResult:
    if direction is Direction.BULL:
        start_price, end_price = bars[start_i].low, bars[end_i].high
    else:
        start_price, end_price = bars[start_i].high, bars[end_i].low
    window = list(bars[start_i:end_i + 1])
    bar_count = len(window)
    length_atr = displacement(start_price, end_price) / last_atr
    bodies = body_ratio(window, direction)
    overlap = overlap_ratio(window)
    share = single_bar_share(window, direction)
    metrics = {
        "bar_count": float(bar_count),
        "length_atr": length_atr,
        "body_ratio": bodies,
        "overlap_ratio": overlap,
        "single_bar_share": share,
        "atr": last_atr,
    }
    reasons: list[str] = [
        f"{direction.value} leg {start_i}->{end_i}",
        f"displacement {length_atr:.2f} ATR over {bar_count} bars",
    ]
    problems: list[str] = []
    if bar_count < params.min_leg_bars:
        problems.append(f"bar count {bar_count} < {params.min_leg_bars}")
    if length_atr < params.min_leg_atr:
        problems.append(f"displacement {length_atr:.2f} ATR < {params.min_leg_atr}")
    if bodies < params.min_body_ratio:
        problems.append(f"body ratio {bodies:.2f} < {params.min_body_ratio}")
    if overlap > params.max_overlap_ratio:
        problems.append(f"overlap {overlap:.2f} > {params.max_overlap_ratio}")
    if problems:
        return StrongLegResult(
            valid=False, stopped=True, high_risk=False, direction=direction,
            start_index=start_i, end_index=end_i, start_price=start_price,
            end_price=end_price, length_atr=length_atr,
            reasons=tuple(
                reasons + ["invalid: " + "; ".join(problems), "assessment stopped"]
            ),
            metrics=metrics,
        )
    high_risk = length_atr >= params.extended_leg_atr or share >= params.max_single_bar_share
    if high_risk:
        why = (
            "extended displacement"
            if length_atr >= params.extended_leg_atr
            else "one bar dominates the leg"
        )
        reasons.append("high-risk: " + why)
    else:
        reasons.append("structure acceptable; not flagged high-risk")
    return StrongLegResult(
        valid=True, stopped=False, high_risk=high_risk, direction=direction,
        start_index=start_i, end_index=end_i, start_price=start_price,
        end_price=end_price, length_atr=length_atr, reasons=tuple(reasons),
        metrics=metrics,
    )


def _candidate_legs(highs: list[int], lows: list[int]) -> list[tuple[int, int, Direction]]:
    """Consecutive opposite swings, in time order. Selection among legs is RESEARCH."""
    events = sorted([(i, "H") for i in highs] + [(i, "L") for i in lows])
    out: list[tuple[int, int, Direction]] = []
    prev_i, prev_t = events[0]
    for idx, typ in events[1:]:
        if typ == prev_t:
            prev_i, prev_t = idx, typ
            continue
        if prev_t == "L" and typ == "H":
            out.append((prev_i, idx, Direction.BULL))
        elif prev_t == "H" and typ == "L":
            out.append((prev_i, idx, Direction.BEAR))
        prev_i, prev_t = idx, typ
    return out


def assess_strong_leg(
    bars: Sequence[Candle], params: ProBtbParams | None = None,
) -> StrongLegResult:
    """Assess swing-to-swing legs and keep the most recent one that qualifies as strong.

    A later weak pullback does not erase an earlier qualifying impulse. If no
    leg qualifies, the pipeline stops. Cutoffs are RESEARCH parameters.
    """
    params = params or ProBtbParams()
    if len(bars) < params.min_history_bars:
        return _stop([f"fewer than {params.min_history_bars} bars; assessment stopped"])
    last_atr = require_atr(bars, params)
    if last_atr is None or last_atr <= 0:
        return _stop(["ATR is undefined; assessment stopped"])

    highs, lows = last_swings(bars, params)
    if not highs or not lows:
        return _stop(["no confirmed swing high and low; assessment stopped"])
    legs = _candidate_legs(highs, lows)
    if not legs:
        return _stop(["no opposite-swing leg; assessment stopped"])

    evaluated = [
        _evaluate_leg(bars, start, end, direction, last_atr, params)
        for start, end, direction in legs
        if end > start
    ]
    if not evaluated:
        return _stop(["no ordered swing-to-swing leg; assessment stopped"])
    strong = [r for r in evaluated if r.valid]
    if strong:
        chosen = strong[-1]
        return StrongLegResult(
            valid=chosen.valid, stopped=False, high_risk=chosen.high_risk,
            direction=chosen.direction, start_index=chosen.start_index,
            end_index=chosen.end_index, start_price=chosen.start_price,
            end_price=chosen.end_price, length_atr=chosen.length_atr,
            reasons=chosen.reasons + (
                f"selected as most recent qualifying strong leg of {len(strong)}",
            ),
            metrics=chosen.metrics,
        )
    latest = evaluated[-1]
    return latest


def list_strong_legs(
    bars: Sequence[Candle], params: ProBtbParams | None = None,
) -> tuple[StrongLegResult, ...]:
    """Every qualifying strong swing-to-swing leg, oldest first. Cutoffs are RESEARCH."""
    params = params or ProBtbParams()
    if len(bars) < params.min_history_bars:
        return ()
    last_atr = require_atr(bars, params)
    if last_atr is None or last_atr <= 0:
        return ()
    highs, lows = last_swings(bars, params)
    if not highs or not lows:
        return ()
    out: list[StrongLegResult] = []
    for start, end, direction in _candidate_legs(highs, lows):
        if end <= start:
            continue
        result = _evaluate_leg(bars, start, end, direction, last_atr, params)
        if result.valid:
            out.append(result)
    return tuple(out)
