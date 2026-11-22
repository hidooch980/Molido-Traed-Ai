"""Spike & Imbalance: ATR spike, FVG via SMC adapter, mitigation agreement."""

from __future__ import annotations

from app.agents.analyzers.smc import fair_value_gaps
from app.agents.v2.rules import spike_imbalance_counts
from app.agents.v2.spike_imbalance.engine import SpikeImbalanceEngine, fvg_is_mitigated
from tests.v2_bars import bull_spike_bars, fvg_then_fill


class TestSpikeImbalance:
    def test_fvg_comes_from_the_existing_helper_not_a_copy(self):
        bars = fvg_then_fill()
        report = SpikeImbalanceEngine().run(bars)
        raw = fair_value_gaps(tuple(bars))
        assert len(report.fvgs) == len(raw)
        assert {(z.side, z.low, z.high, z.formed_at) for z in report.fvgs} == set(raw)
        assert report.as_dict()["fvg_source"] == "app.agents.analyzers.smc.fair_value_gaps"

    def test_mitigation_agrees_with_sm04_fill_rule(self):
        bars = fvg_then_fill()
        report = SpikeImbalanceEngine().run(bars)
        raw = fair_value_gaps(tuple(bars))
        for side, low, high, formed_at in raw:
            filled, at = fvg_is_mitigated(bars, side, low, high, formed_at)
            # SM04: later bars after formed_at (not including the gap bar).
            later = bars[formed_at + 1:]
            sm04 = any(b.low <= low for b in later) if side == "bull" else \
                any(b.high >= high for b in later)
            assert filled is sm04
            match = next(z for z in report.fvgs if z.formed_at == formed_at and z.side == side)
            assert match.mitigated is sm04
            if filled:
                assert at is not None
        assert any(z.mitigated for z in report.fvgs)
        assert any(not z.mitigated for z in report.fvgs)
        assert report.continuation_probability is None
        assert report.reversal_probability is None

    def test_atr_spike_flags_the_gapped_impulse(self):
        report = SpikeImbalanceEngine().run(bull_spike_bars())
        # The gapped impulse bar is far larger than the quiet-range ATR.
        assert report.spikes
        assert all(s.range_atr >= 2.5 for s in report.spikes)

    def test_counts_include_research_thresholds(self):
        counts = spike_imbalance_counts()
        assert counts["VERIFIED"] == 0
        assert counts["TESTED"] > 0 and counts["RESEARCH"] > 0
