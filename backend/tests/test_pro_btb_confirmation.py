"""Independent tests for stage 5: confirmation (accept or wait, reason logged)."""

from __future__ import annotations

from app.agents.pro_btb.engine import select_breakout_leg
from app.agents.pro_btb.stages.bo_candle import validate_bo_candle
from app.agents.pro_btb.stages.confirmation import confirm_setup
from app.agents.pro_btb.stages.retest import assess_retest
from tests.pro_btb_bars import bear_bars, bull_bars, bull_impulse_bars, chop_bars


def _bundle(bars):
    leg = select_breakout_leg(bars)
    bo = validate_bo_candle(bars, leg)
    retest = assess_retest(bars, bo)
    return leg, bo, retest, confirm_setup(leg, bo, retest)


class TestConfirmation:
    def test_chop_is_rejected_and_waits(self):
        _, _, _, conf = _bundle(chop_bars())
        # select_breakout_leg on chop falls back to a STOP result.
        assert not conf.accepted
        assert "rejected" in conf.reason
        assert "continue waiting" in conf.reason
        assert conf.checks["strong_leg_valid"] is False

    def test_impulse_without_return_is_rejected(self):
        # Cut before the pullback reaches the BTB zone.
        bars = bull_impulse_bars()
        _, _, retest, conf = _bundle(bars)
        assert not retest.returned
        assert not conf.accepted
        assert conf.checks["price_returned_to_btb"] is False

    def test_bull_retest_is_accepted_with_a_reason(self):
        _, _, _, conf = _bundle(bull_bars())
        assert conf.accepted
        assert conf.reason.startswith("accepted:")
        assert all(conf.checks.values())

    def test_bear_retest_is_accepted(self):
        _, _, _, conf = _bundle(bear_bars())
        assert conf.accepted
        assert "accepted" in conf.reason
