"""Stage 3: four independently modelled break-even zones, then a comparison."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.agents.analyzers.bars import Candle
from app.agents.pro_btb.geometry import classify_window, last_swings, require_atr
from app.agents.pro_btb.params import ProBtbParams
from app.agents.pro_btb.rules import RULE_BY_ID
from app.agents.pro_btb.stages.strong_leg import StrongLegResult
from app.agents.pro_btb.types import (
    BreakEvenKind,
    BreakEvenZone,
    CycleLabel,
    Direction,
    PipelineDecision,
    StageSnapshot,
    ZoneComparison,
)


def _zone(kind: BreakEvenKind, rule_id: str, present: bool, price: float | None,
          index: int | None, reasons: list[str]) -> BreakEvenZone:
    return BreakEvenZone(
        kind=kind, present=present, price=price, bar_index=index,
        reasons=tuple(reasons), rule_id=rule_id,
        rule_status=RULE_BY_ID[rule_id].status,
    )


def assess_leg1_start(leg: StrongLegResult) -> BreakEvenZone:
    if leg.start_index is None or leg.start_price is None:
        return _zone(BreakEvenKind.LEG1_START, "BE_ZONE_LEG1_START", False, None, None,
                     ["leg 1 start is not available"])
    return _zone(BreakEvenKind.LEG1_START, "BE_ZONE_LEG1_START", True, leg.start_price,
                 leg.start_index, ["leg 1 starts at the first impulse extreme"])


def assess_leg2_start(
    bars: Sequence[Candle],
    leg: StrongLegResult,
    params: ProBtbParams | None = None,
) -> BreakEvenZone:
    """RESEARCH identification: a pullback after leg 1, then a new impulse."""
    params = params or ProBtbParams()
    if not leg.valid or leg.end_index is None or leg.direction is Direction.NONE:
        return _zone(BreakEvenKind.LEG2_START, "BE_ZONE_LEG2_START", False, None, None,
                     ["no valid first leg"])
    rest = list(bars[leg.end_index:])
    if len(rest) < params.swing_k * 2 + 3:
        return _zone(BreakEvenKind.LEG2_START, "BE_ZONE_LEG2_START", False, None, None,
                     ["not enough bars after leg 1 to confirm a second leg"])
    highs, lows = last_swings(rest, params)
    if leg.direction is Direction.BULL:
        # Pullback low after the first high, then a later high.
        if not lows:
            return _zone(BreakEvenKind.LEG2_START, "BE_ZONE_LEG2_START", False, None, None,
                         ["no confirmed pullback low after leg 1"])
        pull_i = lows[0] + leg.end_index
        later_highs = [i + leg.end_index for i in highs if i + leg.end_index > pull_i]
        if not later_highs:
            return _zone(BreakEvenKind.LEG2_START, "BE_ZONE_LEG2_START", False, None, None,
                         ["pullback found, but no second impulse yet"])
        return _zone(BreakEvenKind.LEG2_START, "BE_ZONE_LEG2_START", True, bars[pull_i].low,
                     pull_i, ["leg 2 starts at the pullback low after leg 1"])
    if not highs:
        return _zone(BreakEvenKind.LEG2_START, "BE_ZONE_LEG2_START", False, None, None,
                     ["no confirmed pullback high after leg 1"])
    pull_i = highs[0] + leg.end_index
    later_lows = [i + leg.end_index for i in lows if i + leg.end_index > pull_i]
    if not later_lows:
        return _zone(BreakEvenKind.LEG2_START, "BE_ZONE_LEG2_START", False, None, None,
                     ["pullback found, but no second impulse yet"])
    return _zone(BreakEvenKind.LEG2_START, "BE_ZONE_LEG2_START", True, bars[pull_i].high,
                 pull_i, ["leg 2 starts at the pullback high after leg 1"])


def _window_after_leg(bars: Sequence[Candle], leg: StrongLegResult) -> tuple[int, int] | None:
    if leg.start_index is None:
        return None
    end = len(bars) - 1
    if end <= leg.start_index:
        return None
    return leg.start_index, end


def assess_spike_top(
    bars: Sequence[Candle],
    leg: StrongLegResult,
    params: ProBtbParams | None = None,
) -> BreakEvenZone:
    params = params or ProBtbParams()
    span = _window_after_leg(bars, leg)
    if span is None or leg.direction is Direction.NONE:
        return _zone(BreakEvenKind.SPIKE_TOP, "BE_ZONE_SPIKE_TOP", False, None, None,
                     ["no window to search for a spike"])
    start, end = span
    # Search prefix windows first so a later channel does not hide an early spike.
    last_atr = require_atr(bars, params)
    found: tuple[int, int] | None = None
    max_len = min(params.spike_max_bars, end - start + 1)
    for length in range(2, max_len + 1):
        label = classify_window(bars[start:start + length], params, last_atr)
        if label is CycleLabel.SPIKE:
            found = (start, start + length - 1)
            break
    if found is None:
        return _zone(BreakEvenKind.SPIKE_TOP, "BE_ZONE_SPIKE_TOP", False, None, None,
                     ["no spike classified in the post-leg window (thresholds are RESEARCH)"])
    a, b = found
    if leg.direction is Direction.BULL:
        idx = max(range(a, b + 1), key=lambda i: bars[i].high)
        price = bars[idx].high
    else:
        idx = min(range(a, b + 1), key=lambda i: bars[i].low)
        price = bars[idx].low
    return _zone(BreakEvenKind.SPIKE_TOP, "BE_ZONE_SPIKE_TOP", True, price, idx,
                 [f"spike extreme at bar {idx}"])


def assess_channel_top(
    bars: Sequence[Candle],
    leg: StrongLegResult,
    params: ProBtbParams | None = None,
) -> BreakEvenZone:
    params = params or ProBtbParams()
    span = _window_after_leg(bars, leg)
    if span is None or leg.direction is Direction.NONE:
        return _zone(BreakEvenKind.CHANNEL_TOP, "BE_ZONE_CHANNEL_TOP", False, None, None,
                     ["no window to search for a channel"])
    start, end = span
    last_atr = require_atr(bars, params)
    if end - start + 1 < params.channel_min_bars:
        return _zone(BreakEvenKind.CHANNEL_TOP, "BE_ZONE_CHANNEL_TOP", False, None, None,
                     ["not enough bars for a channel window"])
    label = classify_window(bars[start:end + 1], params, last_atr)
    # A late channel may sit after a spike: also try the suffix of the window.
    if label is not CycleLabel.CHANNEL and end - start + 1 > params.channel_min_bars:
        for mid in range(start + 1, end - params.channel_min_bars + 2):
            if classify_window(bars[mid:end + 1], params, last_atr) is CycleLabel.CHANNEL:
                start = mid
                label = CycleLabel.CHANNEL
                break
    if label is not CycleLabel.CHANNEL:
        return _zone(BreakEvenKind.CHANNEL_TOP, "BE_ZONE_CHANNEL_TOP", False, None, None,
                     ["no channel classified in the post-leg window (thresholds are RESEARCH)"])
    if leg.direction is Direction.BULL:
        idx = max(range(start, end + 1), key=lambda i: bars[i].high)
        price = bars[idx].high
    else:
        idx = min(range(start, end + 1), key=lambda i: bars[i].low)
        price = bars[idx].low
    return _zone(BreakEvenKind.CHANNEL_TOP, "BE_ZONE_CHANNEL_TOP", True, price, idx,
                 [f"channel extreme at bar {idx}"])


def compare_zones(zones: Sequence[BreakEvenZone]) -> tuple[ZoneComparison, ...]:
    present = [z for z in zones if z.present and z.price is not None]
    out: list[ZoneComparison] = []
    for i, left in enumerate(present):
        for right in present[i + 1:]:
            assert left.price is not None and right.price is not None
            out.append(ZoneComparison(left.kind, right.kind, right.price - left.price))
    return tuple(out)


@dataclass(frozen=True)
class BreakEvenReport:
    zones: tuple[BreakEvenZone, ...]
    comparisons: tuple[ZoneComparison, ...]
    reasons: tuple[str, ...]

    def snapshot(self) -> StageSnapshot:
        present = sum(1 for z in self.zones if z.present)
        return StageSnapshot(
            stage="break_even",
            valid=True,
            decision=PipelineDecision.CONTINUE,
            reasons=self.reasons,
            details={
                "zones": [z.as_dict() for z in self.zones],
                "comparisons": [c.as_dict() for c in self.comparisons],
                "present_count": present,
            },
        )


def identify_break_even_zones(
    bars: Sequence[Candle],
    leg: StrongLegResult,
    params: ProBtbParams | None = None,
) -> BreakEvenReport:
    params = params or ProBtbParams()
    zones = (
        assess_leg1_start(leg),
        assess_leg2_start(bars, leg, params),
        assess_spike_top(bars, leg, params),
        assess_channel_top(bars, leg, params),
    )
    comparisons = compare_zones(zones)
    reasons = [f"{z.kind.value}: {'present @ ' + f'{z.price:.5f}' if z.present else 'absent'}"
               for z in zones]
    reasons.append(f"{len(comparisons)} pairwise comparisons")
    return BreakEvenReport(zones=zones, comparisons=comparisons, reasons=tuple(reasons))
