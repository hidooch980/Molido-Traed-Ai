"""Independent tests for stage 3: four break-even zones."""

from __future__ import annotations

from app.agents.pro_btb.engine import select_breakout_leg
from app.agents.pro_btb.stages.break_even import (
    assess_channel_top,
    assess_leg1_start,
    assess_leg2_start,
    assess_spike_top,
    compare_zones,
    identify_break_even_zones,
)
from app.agents.pro_btb.stages.strong_leg import assess_strong_leg
from app.agents.pro_btb.types import BreakEvenKind, Direction
from tests.pro_btb_bars import bear_bars, bull_bars, chop_bars


class TestBreakEvenZones:
    def test_each_zone_is_assessed_independently_on_chop(self):
        leg = assess_strong_leg(chop_bars())
        zones = (
            assess_leg1_start(leg),
            assess_leg2_start(chop_bars(), leg),
            assess_spike_top(chop_bars(), leg),
            assess_channel_top(chop_bars(), leg),
        )
        assert {z.kind for z in zones} == set(BreakEvenKind)
        assert all(not z.present for z in zones)
        assert compare_zones(zones) == ()

    def test_bull_leg1_and_spike_are_present_and_comparable(self):
        bars = bull_bars()
        leg = select_breakout_leg(bars)
        report = identify_break_even_zones(bars, leg)
        by_kind = {z.kind: z for z in report.zones}
        assert set(by_kind) == set(BreakEvenKind)
        assert by_kind[BreakEvenKind.LEG1_START].present
        assert by_kind[BreakEvenKind.LEG1_START].price == leg.start_price
        assert by_kind[BreakEvenKind.SPIKE_TOP].present
        assert by_kind[BreakEvenKind.SPIKE_TOP].price is not None
        # Comparable: present zones produce pairwise deltas of the same shape.
        assert report.comparisons
        assert all(hasattr(c, "delta") and c.left != c.right for c in report.comparisons)
        # Spike extreme of a bull move sits above the start of leg 1.
        assert by_kind[BreakEvenKind.SPIKE_TOP].price > by_kind[BreakEvenKind.LEG1_START].price

    def test_bear_zones_are_independent_and_mirrored(self):
        bars = bear_bars()
        leg = select_breakout_leg(bars)
        assert leg.direction is Direction.BEAR
        report = identify_break_even_zones(bars, leg)
        by_kind = {z.kind: z for z in report.zones}
        assert by_kind[BreakEvenKind.LEG1_START].present
        assert by_kind[BreakEvenKind.SPIKE_TOP].present
        # Bear spike "top" is the low extreme, below leg 1 start.
        assert by_kind[BreakEvenKind.SPIKE_TOP].price < by_kind[BreakEvenKind.LEG1_START].price
        assert {c.left for c in report.comparisons} | {c.right for c in report.comparisons}
