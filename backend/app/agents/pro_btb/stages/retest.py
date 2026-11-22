"""Stage 4: BTB retest — store the zone as a range, wait for a return, classify structure."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.agents.analyzers.bars import Candle
from app.agents.pro_btb.geometry import classify_window, microchannel, require_atr
from app.agents.pro_btb.params import ProBtbParams
from app.agents.pro_btb.rules import RULE_BY_ID
from app.agents.pro_btb.stages.bo_candle import BoCandleResult
from app.agents.pro_btb.types import (
    CycleLabel,
    Direction,
    PipelineDecision,
    PriceRange,
    StageSnapshot,
)


def build_btb_zone(bars: Sequence[Candle], bo: BoCandleResult) -> PriceRange | None:
    """RESEARCH construction: span the breakout reference and the BO candle range."""
    if not bo.found or bo.bo_index is None or bo.reference is None:
        return None
    candle = bars[bo.bo_index]
    low = min(bo.reference, candle.low, candle.open, candle.close)
    high = max(bo.reference, candle.high, candle.open, candle.close)
    rule = RULE_BY_ID["BTB_ZONE_IS_PRICE_RANGE"]
    return PriceRange(low=low, high=high, rule_id=rule.id, rule_status=rule.status)


@dataclass(frozen=True)
class RetestResult:
    zone: PriceRange | None
    returned: bool
    return_index: int | None
    microchannel: bool
    cycle: CycleLabel
    reasons: tuple[str, ...]

    def snapshot(self) -> StageSnapshot:
        return StageSnapshot(
            stage="btb_retest",
            valid=self.zone is not None,
            decision=PipelineDecision.CONTINUE if self.returned else PipelineDecision.WAIT,
            reasons=self.reasons,
            details={
                "zone": None if self.zone is None else self.zone.as_dict(),
                "returned": self.returned,
                "return_index": self.return_index,
                "microchannel": self.microchannel,
                "cycle": self.cycle.value,
                "zone_construction_status": "RESEARCH",
            },
        )


def assess_retest(
    bars: Sequence[Candle],
    bo: BoCandleResult,
    params: ProBtbParams | None = None,
) -> RetestResult:
    params = params or ProBtbParams()
    zone = build_btb_zone(bars, bo)
    if zone is None or bo.bo_index is None:
        return RetestResult(None, False, None, False, CycleLabel.UNKNOWN,
                            ("no BTB zone; retest cannot be assessed",))
    # RESEARCH: a retest is a return *after* price has left the zone, not the
    # follow-through bar that still overlaps the breakout range.
    start = bo.bo_index + 1
    earliest = start + max(params.min_bars_after_bo - 1, 0)
    left = False
    return_index = None
    for i in range(start, len(bars)):
        hits = zone.intersects(bars[i].low, bars[i].high)
        if not hits:
            left = True
            continue
        if left and i >= earliest:
            return_index = i
            break
    returned = return_index is not None
    direction = bo.direction
    mc = False
    if returned and direction is not Direction.NONE:
        tails = (
            bars[:return_index + 1],
            bars[return_index:],
            bars,
        )
        mc = any(microchannel(t, direction, params.microchannel_bars) for t in tails)
    last_atr = require_atr(bars, params)
    if bo.bo_index < len(bars):
        cycle = classify_window(bars[bo.bo_index:], params, last_atr)
    else:
        cycle = CycleLabel.UNKNOWN
    reasons = [
        f"BTB range [{zone.low:.5f}, {zone.high:.5f}] (construction: RESEARCH)",
        (
            f"price returned at bar {return_index}" if returned
            else "still waiting for a return to the BTB range"
        ),
        "microchannel present" if mc else "no microchannel at the return (definition is RESEARCH)",
        f"post-BO structure: {cycle.value} (thresholds are RESEARCH)",
    ]
    return RetestResult(zone, returned, return_index, mc, cycle, tuple(reasons))
