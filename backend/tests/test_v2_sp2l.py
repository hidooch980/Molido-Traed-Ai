"""SP2L engine: spike, P-Gap, legs, HL/LH, ratio, breakout, retest, WAIT entry."""

from __future__ import annotations

from app.agents.pro_btb.types import Direction
from app.agents.v2.rules import sp2l_counts
from app.agents.v2.sp2l.engine import Sp2lEngine, detect_spike
from tests.v2_bars import bear_spike_bars, bull_spike_bars, three_weekdays_oct2026


class TestSp2l:
    def test_bull_spike_with_pgap_and_second_leg(self):
        bars = bull_spike_bars()
        report = Sp2lEngine().run(bars)
        assert report.spike is not None and report.spike.valid
        assert report.direction is Direction.BULL
        assert report.spike.has_pgap
        assert report.leg1 is not None and report.leg2 is not None
        assert report.hl_lh
        assert report.leg_ratio is not None and report.leg_ratio > 0
        assert report.entry_action == "WAIT"
        assert report.entry is report.stop_loss is report.take_profit is None
        assert report.risk_reward is None

    def test_bear_mirror_is_valid(self):
        report = Sp2lEngine().run(bear_spike_bars())
        assert report.direction is Direction.BEAR
        assert report.spike is not None and report.spike.valid and report.spike.has_pgap
        assert report.leg2 is not None
        assert report.entry_action == "WAIT"

    def test_spike_without_a_gap_is_invalid(self):
        bars = three_weekdays_oct2026()  # overlapping range, no P-Gap impulse
        spike = detect_spike(bars)
        report = Sp2lEngine().run(bars)
        # Either no spike, or a detected run is rejected for missing P-Gap.
        if spike is None:
            assert report.spike is None
            assert report.entry_action == "WAIT"
        else:
            if not spike.has_pgap:
                assert not spike.valid
                assert report.entry_action == "WAIT"

    def test_catalog_keeps_placement_rules_in_research(self):
        counts = sp2l_counts()
        assert counts["VERIFIED"] == 0
        assert counts["TESTED"] > 0 and counts["RESEARCH"] > 0
