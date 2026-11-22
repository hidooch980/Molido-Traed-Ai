"""Stage 2: BO candle validation (gap, follow-through, close at the extreme)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.agents.analyzers.bars import Candle
from app.agents.pro_btb.geometry import close_at_extreme, last_swings
from app.agents.pro_btb.params import ProBtbParams
from app.agents.pro_btb.stages.strong_leg import StrongLegResult
from app.agents.pro_btb.types import Direction, PipelineDecision, StageSnapshot


@dataclass(frozen=True)
class BoCandleResult:
    found: bool
    valid: bool
    direction: Direction
    bo_index: int | None
    reference: float | None
    has_gap: bool
    has_follow_through: bool
    closes_at_extreme: bool
    risk_flags: tuple[str, ...]
    reasons: tuple[str, ...]

    def snapshot(self) -> StageSnapshot:
        return StageSnapshot(
            stage="bo_candle",
            valid=self.valid,
            decision=PipelineDecision.CONTINUE if self.valid else PipelineDecision.WAIT,
            reasons=self.reasons,
            details={
                "found": self.found,
                "bo_index": self.bo_index,
                "reference": self.reference,
                "has_gap": self.has_gap,
                "has_follow_through": self.has_follow_through,
                "closes_at_extreme": self.closes_at_extreme,
                "risk_flags": list(self.risk_flags),
                "definitions_status": "RESEARCH",
            },
        )


def _empty(direction: Direction, reasons: list[str]) -> BoCandleResult:
    return BoCandleResult(
        found=False, valid=False, direction=direction, bo_index=None, reference=None,
        has_gap=False, has_follow_through=False, closes_at_extreme=False,
        risk_flags=(), reasons=tuple(reasons),
    )


def _prior_reference(
    bars: Sequence[Candle], leg: StrongLegResult, params: ProBtbParams,
) -> float | None:
    """RESEARCH: the swing extreme on the opposite side that the leg broke."""
    if leg.start_index is None:
        return None
    highs, lows = last_swings(bars[:leg.start_index + 1], params)
    if leg.direction is Direction.BULL:
        prior = [i for i in highs if i < leg.start_index]
        return bars[prior[-1]].high if prior else max(b.high for b in bars[:leg.start_index])
    if leg.direction is Direction.BEAR:
        prior = [i for i in lows if i < leg.start_index]
        return bars[prior[-1]].low if prior else min(b.low for b in bars[:leg.start_index])
    return None


def _broke(bar: Candle, reference: float, direction: Direction) -> bool:
    if direction is Direction.BULL:
        return bar.close > reference
    if direction is Direction.BEAR:
        return bar.close < reference
    return False


def _gap(prev: Candle, bo: Candle, direction: Direction) -> bool:
    """RESEARCH: full gap beyond the previous bar's extreme."""
    if direction is Direction.BULL:
        return bo.open > prev.high
    if direction is Direction.BEAR:
        return bo.open < prev.low
    return False


def _follow_through(bo: Candle, nxt: Candle, direction: Direction) -> bool:
    """RESEARCH: the next bar closes beyond the BO extreme."""
    if direction is Direction.BULL:
        return nxt.close > bo.high
    if direction is Direction.BEAR:
        return nxt.close < bo.low
    return False


def validate_bo_candle(
    bars: Sequence[Candle],
    leg: StrongLegResult,
    params: ProBtbParams | None = None,
) -> BoCandleResult:
    params = params or ProBtbParams()
    if not leg.valid or leg.start_index is None or leg.end_index is None:
        return _empty(leg.direction, ["no valid strong leg; BO is not assessed"])
    if leg.start_index < 1:
        return _empty(leg.direction, ["not enough bars before the leg for a reference"])

    reference = _prior_reference(bars, leg, params)
    if reference is None:
        return _empty(leg.direction, ["no breakout reference; BO is not assessed"])

    bo_index = None
    for i in range(leg.start_index, min(leg.end_index + 1, len(bars))):
        if _broke(bars[i], reference, leg.direction):
            bo_index = i
            break
    if bo_index is None or bo_index < 1:
        return _empty(leg.direction, [f"no close beyond reference {reference:.5f} inside the leg"])

    bo = bars[bo_index]
    prev = bars[bo_index - 1]
    has_gap = _gap(prev, bo, leg.direction)
    has_ft = False
    if bo_index + 1 < len(bars):
        has_ft = _follow_through(bo, bars[bo_index + 1], leg.direction)
    closes = close_at_extreme(bo, leg.direction, params.close_extreme_frac)

    flags: list[str] = []
    if not has_gap:
        flags.append("MISSING_GAP")
    if bo_index + 1 >= len(bars):
        flags.append("FT_NOT_YET_AVAILABLE")
    elif not has_ft:
        flags.append("MISSING_FT")
    if not closes:
        flags.append("CLOSE_NOT_AT_EXTREME")

    reasons = [
        f"BO bar {bo_index} close {bo.close:.5f} vs reference {reference:.5f}",
        "gap present" if has_gap else "no gap (risk raised)",
        (
            "follow-through present" if has_ft
            else "no follow-through (risk raised or not yet available)"
        ),
        "close at extreme" if closes else "close not at the extreme",
    ]
    # A found BO is valid enough to continue; missing gap/FT raise risk, they do
    # not by themselves invalidate (SPECIFIED). Close-at-extreme is recorded.
    return BoCandleResult(
        found=True, valid=True, direction=leg.direction, bo_index=bo_index,
        reference=reference, has_gap=has_gap, has_follow_through=has_ft,
        closes_at_extreme=closes, risk_flags=tuple(flags), reasons=tuple(reasons),
    )
