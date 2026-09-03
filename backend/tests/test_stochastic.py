"""The stochastic oscillator, checked against arithmetic anybody can redo.

An indicator that is wrong produces a measurement that is precisely wrong,
and the measurement will not say so - it will report a rule that has no edge,
which is indistinguishable from a correct rule that has no edge. So the maths
is pinned to hand-computed values before it is measured on anything.
"""

from __future__ import annotations

import pytest

from app.learning.rules import PROPOSED, StochasticReversion


def bars(values: list[tuple[float, float, float]]):
    """(high, low, close) triples, oldest first - the shape the snapshot uses."""
    return values


class TestTheArithmetic:
    def test_a_close_at_the_top_of_the_range_is_a_hundred(self):
        rule = StochasticReversion(window=3, smoothing=1)
        # Range 10..20 over the window, closing at 20.
        series = bars([(20, 10, 15), (18, 12, 16), (20, 14, 20)])

        assert rule.percent_d(series) == pytest.approx(100.0)

    def test_a_close_at_the_bottom_is_zero(self):
        rule = StochasticReversion(window=3, smoothing=1)
        series = bars([(20, 10, 15), (18, 12, 16), (19, 14, 10)])

        assert rule.percent_d(series) == pytest.approx(0.0)

    def test_the_middle_is_fifty(self):
        rule = StochasticReversion(window=3, smoothing=1)
        series = bars([(20, 10, 15), (18, 12, 16), (19, 14, 15)])

        assert rule.percent_d(series) == pytest.approx(50.0)

    def test_the_smoothed_line_is_the_mean_of_the_last_three(self):
        rule = StochasticReversion(window=2, smoothing=3)
        # %K on the last three windows: 100, 0, 50 -> mean 50.
        series = bars([(10, 0, 5), (10, 0, 10), (10, 0, 0), (10, 0, 5)])

        assert rule.percent_d(series) == pytest.approx(50.0)

    def test_a_window_that_never_moved_has_no_position_inside_itself(self):
        """Not fifty. Fifty would be a claim about the middle of nothing."""
        rule = StochasticReversion(window=3, smoothing=1)

        assert rule.percent_d(bars([(5, 5, 5)] * 3)) is None

    def test_too_little_history_is_none_rather_than_a_partial_window(self):
        rule = StochasticReversion(window=14, smoothing=3)

        assert rule.percent_d(bars([(10, 5, 7)] * 10)) is None

    def test_it_uses_the_published_parameters(self):
        """A threshold tuned on this data would make the measurement that
        follows a measurement of the tuning."""
        rule = StochasticReversion()

        assert (rule.window, rule.smoothing) == (14, 3)
        assert (rule.oversold, rule.overbought) == (20.0, 80.0)


def snapshot_of(**series):
    return {name: {"bars": rows, "closes": [r[2] for r in rows]} for name, rows in series.items()}


class TestWhatItPicks:
    def rising(self, n=20):
        """Closing at the top of a rising range."""
        return [(10 + i, 5 + i, 10 + i) for i in range(n)]

    def falling(self, n=20):
        return [(10 + (n - i), 5 + (n - i), 5 + (n - i)) for i in range(n)]

    def test_it_shorts_what_is_at_the_top_of_its_range(self):
        picks = StochasticReversion()(
            snapshot_of(EURUSD=self.rising()), universe=frozenset({"EURUSD"})
        )

        assert picks.shorts == ("EURUSD",)
        assert picks.longs == ()

    def test_it_buys_what_is_at_the_bottom(self):
        picks = StochasticReversion()(
            snapshot_of(EURUSD=self.falling()), universe=frozenset({"EURUSD"})
        )

        assert picks.longs == ("EURUSD",)

    def test_nothing_in_a_band_is_a_decline_not_an_empty_opinion(self):
        flat = [(10 + (i % 2), 5 - (i % 2), 7.5) for i in range(20)]

        picks = StochasticReversion()(
            snapshot_of(EURUSD=flat), universe=frozenset({"EURUSD"})
        )

        assert picks.empty
        assert "edge of its range" in (picks.declined or "")

    def test_it_takes_at_most_two_a_side(self):
        rising = {f"S{i}": self.rising() for i in range(5)}

        picks = StochasticReversion()(snapshot_of(**rising), universe=frozenset(rising))

        assert len(picks.shorts) == 2


class TestItIsNotDeployedYet:
    def test_it_is_proposed_rather_than_a_candidate(self):
        """`forward.record_forward` iterates CANDIDATES and writes a decision
        for every rule in it every cycle, so putting it there is deploying
        it, not proposing it. It moves when its measurement says so."""
        from app.learning import rules

        assert "stochastic-reversion" in PROPOSED
        assert "stochastic-reversion" not in rules.CANDIDATES

    def test_but_the_lab_can_still_find_it(self):
        from app.learning import rules

        assert rules.get("stochastic-reversion") is not None
