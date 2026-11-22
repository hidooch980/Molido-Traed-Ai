"""Independent tests for stage 1: Strong Leg Assessment."""

from __future__ import annotations

from app.agents.pro_btb.params import ProBtbParams
from app.agents.pro_btb.stages.strong_leg import assess_strong_leg, list_strong_legs
from app.agents.pro_btb.types import Direction
from tests.pro_btb_bars import bear_impulse_bars, bull_bars, bull_impulse_bars, chop_bars


class TestStrongLeg:
    def test_short_history_stops(self):
        result = assess_strong_leg(chop_bars(5))
        assert result.stopped and not result.valid
        assert result.direction is Direction.NONE

    def test_chop_does_not_qualify(self):
        result = assess_strong_leg(chop_bars(30))
        assert result.stopped
        assert not result.valid
        assert list_strong_legs(chop_bars(30)) == ()

    def test_bull_impulse_is_a_strong_bull_leg(self):
        bars = bull_impulse_bars()
        legs = list_strong_legs(bars)
        bulls = [leg for leg in legs if leg.direction is Direction.BULL]
        assert bulls, "expected at least one bullish strong leg"
        latest = bulls[-1]
        assert latest.valid and not latest.stopped
        assert latest.start_index is not None and latest.end_index is not None
        assert latest.end_index > latest.start_index
        assert latest.start_price is not None and latest.end_price is not None
        assert latest.end_price > latest.start_price
        assert latest.length_atr is not None and latest.length_atr >= ProBtbParams().min_leg_atr

    def test_bear_impulse_is_a_strong_bear_leg(self):
        bars = bear_impulse_bars()
        bears = [leg for leg in list_strong_legs(bars) if leg.direction is Direction.BEAR]
        assert bears
        latest = bears[-1]
        assert latest.valid
        assert latest.start_price is not None and latest.end_price is not None
        assert latest.end_price < latest.start_price

    def test_extended_impulse_is_high_risk(self):
        # The hand-built impulse is ~7 ATR, above the RESEARCH extended threshold.
        legs = [leg for leg in list_strong_legs(bull_impulse_bars()) if leg.direction is Direction.BULL]
        assert legs[-1].high_risk
        assert any("high-risk" in reason for reason in legs[-1].reasons)

    def test_full_series_still_lists_the_impulse(self):
        starts = {(leg.direction, leg.start_index, leg.end_index) for leg in list_strong_legs(bull_bars())}
        assert any(direction is Direction.BULL and end == 30 for direction, start, end in starts)
