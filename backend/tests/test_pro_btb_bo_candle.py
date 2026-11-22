"""Independent tests for stage 2: BO candle validation."""

from __future__ import annotations

from app.agents.pro_btb.engine import select_breakout_leg
from app.agents.pro_btb.stages.bo_candle import validate_bo_candle
from app.agents.pro_btb.stages.strong_leg import assess_strong_leg
from app.agents.pro_btb.types import Direction
from tests.pro_btb_bars import (
    bear_bars,
    bull_bars,
    bull_bars_no_ft,
    bull_bars_no_gap,
    chop_bars,
)


class TestBoCandle:
    def test_no_leg_means_no_bo(self):
        leg = assess_strong_leg(chop_bars())
        result = validate_bo_candle(chop_bars(), leg)
        assert not result.found and not result.valid

    def test_bull_gap_ft_and_close_at_extreme(self):
        bars = bull_bars()
        bo = validate_bo_candle(bars, select_breakout_leg(bars))
        assert bo.found and bo.valid
        assert bo.direction is Direction.BULL
        assert bo.has_gap and bo.has_follow_through and bo.closes_at_extreme
        assert bo.risk_flags == ()
        assert bo.reference is not None and bo.bo_index is not None
        assert bars[bo.bo_index].close > bo.reference

    def test_bear_gap_ft_and_close_at_extreme(self):
        bars = bear_bars()
        bo = validate_bo_candle(bars, select_breakout_leg(bars))
        assert bo.found and bo.valid
        assert bo.direction is Direction.BEAR
        assert bo.has_gap and bo.has_follow_through and bo.closes_at_extreme
        assert bo.reference is not None
        assert bars[bo.bo_index].close < bo.reference

    def test_missing_gap_raises_risk_but_does_not_invalidate(self):
        bars = bull_bars_no_gap()
        bo = validate_bo_candle(bars, select_breakout_leg(bars))
        assert bo.found and bo.valid
        assert not bo.has_gap
        assert "MISSING_GAP" in bo.risk_flags

    def test_missing_ft_raises_risk_but_does_not_invalidate(self):
        bars = bull_bars_no_ft()
        bo = validate_bo_candle(bars, select_breakout_leg(bars))
        assert bo.found and bo.valid
        assert not bo.has_follow_through
        assert "MISSING_FT" in bo.risk_flags
