"""Scorecard tests.

This module exists because I read a story into three buckets holding 34, 69 and
25 observations. So the tests are mostly about the sizes of sample at which it
must refuse to conclude anything, and about the two ways a backtest flatters
itself: measuring against the payoff it intended rather than the one it got,
and testing many strategies against a line meant for one.
"""

from __future__ import annotations

import pytest

from app.learning import scorecard as sc


def trials(*, wins: int, losses: int, win_r: float = 2.0, loss_r: float = -1.0,
           unresolved: int = 0, strategy: str = "trend_pullback") -> list[sc.Trial]:
    out = [sc.Trial(strategy, win_r) for _ in range(wins)]
    out += [sc.Trial(strategy, loss_r) for _ in range(losses)]
    out += [sc.Trial(strategy, None) for _ in range(unresolved)]
    return out


class TestItRefusesSmallSamples:
    def test_below_the_floor_there_is_no_verdict(self):
        card = sc.score(trials(wins=8, losses=12), strategy="x")

        assert card.verdict == "insufficient"
        assert card.hit_rate is None
        assert "answerable" in card.reason

    def test_the_exact_case_that_fooled_me(self):
        """25 trials at a 48% hit rate looked like the model working."""
        card = sc.score(trials(wins=12, losses=13), strategy="high_conviction")

        assert card.verdict == "insufficient"
        assert card.hit_rate is None

    def test_a_sample_with_no_losers_has_not_met_one_yet(self):
        card = sc.score(trials(wins=80, losses=0), strategy="x")

        assert card.verdict == "insufficient"
        assert "has not met a loser" in card.reason

    def test_a_sample_with_no_winners_is_equally_unmeasurable(self):
        card = sc.score(trials(wins=0, losses=80), strategy="x")

        assert card.verdict == "insufficient"


class TestBreakevenComesFromWhatHappened:
    def test_the_required_rate_uses_the_realised_payoff(self):
        """A strategy built to 2R that returns 1.3R needs 43%, not 33%."""
        card = sc.score(trials(wins=40, losses=60, win_r=1.3), strategy="x")

        assert card.realised_reward_risk == pytest.approx(1.3)
        assert card.required_hit_rate == pytest.approx(1 / 2.3, abs=1e-4)

    def test_a_two_to_one_payoff_needs_a_third(self):
        assert sc.breakeven_hit_rate(2.0) == pytest.approx(1 / 3)

    def test_a_one_to_one_payoff_needs_a_half(self):
        assert sc.breakeven_hit_rate(1.0) == pytest.approx(0.5)

    def test_a_nonsense_payoff_has_no_breakeven(self):
        assert sc.breakeven_hit_rate(0.0) is None

    def test_missing_targets_moves_the_bar_the_expensive_way(self):
        generous = sc.score(trials(wins=45, losses=105, win_r=2.0), strategy="x")
        realistic = sc.score(trials(wins=45, losses=105, win_r=1.2), strategy="x")

        assert realistic.required_hit_rate > generous.required_hit_rate


class TestTheIntervalDecides:
    def test_a_point_estimate_above_breakeven_is_not_enough(self):
        """0.36 against a breakeven of 0.33 with an interval spanning it."""
        card = sc.score(trials(wins=22, losses=39), strategy="x")

        assert card.hit_rate > card.required_hit_rate
        assert card.verdict == "insufficient"
        assert "straddles" in card.reason

    def test_a_clear_edge_is_reported_as_one(self):
        card = sc.score(trials(wins=300, losses=300, win_r=2.0), strategy="x")

        assert card.verdict == "edge"
        assert card.hit_rate_low > card.required_hit_rate

    def test_a_clearly_losing_strategy_is_named(self):
        card = sc.score(trials(wins=60, losses=540, win_r=2.0), strategy="x")

        assert card.verdict == "negative"
        assert "loses money at a measurable rate" in card.reason

    def test_wilson_does_not_misbehave_near_the_ends(self):
        low, high = sc.wilson_interval(0, 30)

        assert low == 0.0
        assert 0 < high < 0.2

    def test_the_interval_narrows_with_the_sample(self):
        small = sc.wilson_interval(15, 50)
        large = sc.wilson_interval(150, 500)

        assert (large[1] - large[0]) < (small[1] - small[0])


class TestManyStrategiesOneLine:
    def test_testing_more_strategies_widens_every_interval(self):
        """With enough families something clears any fixed threshold."""
        alone = sc.score(trials(wins=250, losses=350), strategy="x", comparisons=1)
        among_twelve = sc.score(trials(wins=250, losses=350), strategy="x", comparisons=12)

        assert among_twelve.hit_rate_low < alone.hit_rate_low
        assert among_twelve.hit_rate_high > alone.hit_rate_high

    def test_the_correction_is_disclosed_not_silent(self):
        card = sc.score(trials(wins=250, losses=350), strategy="x", comparisons=12)

        assert any("simultaneous comparisons" in n for n in card.notes)

    def test_score_all_counts_its_own_comparisons(self):
        cards = sc.score_all(
            {
                "a": trials(wins=200, losses=400),
                "b": trials(wins=210, losses=390),
                "c": trials(wins=190, losses=410),
            }
        )

        assert all(c.comparisons == 3 for c in cards)

    def test_a_marginal_winner_can_lose_its_edge_to_the_correction(self):
        """40% over 300 trials at 2R clears the line alone and does not clear
        it as one of twenty. That gap is the whole argument: the same evidence
        means less when it was the best of many looks."""
        alone = sc.score(trials(wins=120, losses=180), strategy="x", comparisons=1)
        corrected = sc.score(trials(wins=120, losses=180), strategy="x", comparisons=20)

        assert alone.verdict == "edge"
        assert corrected.verdict == "insufficient"


class TestUnresolvedTrials:
    def test_unresolved_trials_are_excluded_and_named(self):
        """Stops resolve faster than targets, so dropping them is not neutral."""
        card = sc.score(trials(wins=40, losses=60, unresolved=25), strategy="x")

        assert card.trials == 100
        assert card.unresolved == 25
        assert any("not neutral" in n for n in card.notes)

    def test_an_unresolved_trial_is_not_a_loss(self):
        with_open = sc.score(trials(wins=40, losses=60, unresolved=50), strategy="x")
        without = sc.score(trials(wins=40, losses=60), strategy="x")

        assert with_open.hit_rate == without.hit_rate


class TestReporting:
    def test_the_summary_answers_the_only_question_that_matters(self):
        summary = sc.summarise(
            sc.score_all(
                {
                    "winner": trials(wins=300, losses=300, win_r=2.0),
                    "loser": trials(wins=60, losses=540, win_r=2.0),
                }
            )
        )

        assert summary["any_edge"] is True
        assert summary["with_edge"] == ["winner"]
        assert summary["negative"] == ["loser"]

    def test_no_edge_anywhere_says_so_plainly(self):
        summary = sc.summarise(
            sc.score_all({"a": trials(wins=30, losses=70), "b": trials(wins=28, losses=72)})
        )

        assert summary["any_edge"] is False
        assert summary["with_edge"] == []

    def test_a_measured_edge_is_never_called_a_forecast(self):
        card = sc.score(trials(wins=300, losses=300), strategy="x")

        assert "evidence, not a forecast" in card.as_dict()["note"]

    def test_the_interval_is_published_with_the_rate(self):
        payload = sc.score(trials(wins=300, losses=300), strategy="x").as_dict()

        assert payload["hit_rate_95ci"][0] < payload["hit_rate"] < payload["hit_rate_95ci"][1]
