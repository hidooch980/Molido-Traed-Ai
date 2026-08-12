"""Stress and risk-of-ruin tests (phase 24).

Ruin is the number most likely to be quoted back at the risk engine in an
argument for a bigger position, so most of these tests are about the conditions
under which the module must refuse to produce one — and about the property that
no scenario, input or ordering makes it more permissive than the base case.
"""

from __future__ import annotations

import dataclasses
import math

import pytest

from app.brain import stress
from app.brain.risk import HardLimits
from app.core.enums import RiskVerdict


def measured(**overrides) -> stress.TradeHistory:
    """A history large enough and honest enough to support an estimate."""
    defaults = dict(
        trades=200,
        wins=110,
        average_win_r=1.5,
        average_loss_r=1.0,
        calibrated=True,
    )
    defaults.update(overrides)
    return stress.TradeHistory(**defaults)


# ================================================================== scenarios
class TestScenarios:
    def test_all_four_are_defined(self):
        names = [s.name for s in stress.SCENARIOS]

        assert names == ["base", "adverse", "stress", "extreme"]

    def test_severity_is_monotone_across_the_four(self):
        """A 'stress' case milder than 'adverse' would silently invert the report."""
        losses = [s.loss_multiplier for s in stress.SCENARIOS]
        deltas = [s.win_rate_delta for s in stress.SCENARIOS]
        shocks = [s.correlation_shock for s in stress.SCENARIOS]

        assert losses == sorted(losses)
        assert deltas == sorted(deltas, reverse=True)
        assert shocks == sorted(shocks)

    def test_extreme_assumes_total_correlation(self):
        """Anything less is a second stress case wearing the name."""
        assert stress.EXTREME.correlation_shock == 1.0

    def test_shocked_win_rate_stays_a_probability(self):
        brutal = stress.StressScenario("brutal", 5.0, -0.9, 1.0)

        assert brutal.shocked_win_rate(0.2) == 0.0
        assert stress.BASE.shocked_win_rate(1.0) == 1.0

    def test_scenarios_are_frozen(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            stress.EXTREME.loss_multiplier = 1.0  # type: ignore[misc]


# =============================================================== trade history
class TestTradeHistory:
    def test_small_sample_has_no_win_rate(self):
        """Six winners out of ten is six winners, not a 60% hit rate."""
        assert stress.TradeHistory(trades=10, wins=6).win_rate is None

    def test_large_sample_has_one(self):
        assert measured().win_rate == pytest.approx(0.55)

    def test_payoff_needs_both_averages(self):
        assert measured(average_win_r=None).payoff_ratio is None
        assert measured(average_loss_r=None).payoff_ratio is None
        assert measured().payoff_ratio == pytest.approx(1.5)


# ============================================================== risk of ruin
class TestRuinRefusals:
    def test_uncalibrated_win_rate_yields_no_ruin_number(self):
        """The headline refusal: a ruin figure from an imagined hit rate."""
        estimate = stress.risk_of_ruin(
            win_rate=0.55, payoff_ratio=1.5, risk_fraction=0.01,
            average_loss_r=1.0, calibrated=False, trades_observed=500,
        )

        assert estimate.available is False
        assert estimate.probability is None
        assert "calibrated" in estimate.reason

    def test_small_sample_yields_no_ruin_number(self):
        estimate = stress.risk_of_ruin(
            win_rate=0.55, payoff_ratio=1.5, risk_fraction=0.01,
            average_loss_r=1.0, calibrated=True, trades_observed=12,
        )

        assert estimate.available is False
        assert "12 resolved trades" in estimate.reason

    def test_missing_win_rate_is_not_substituted(self):
        estimate = stress.risk_of_ruin(
            win_rate=None, payoff_ratio=1.5, risk_fraction=0.01,
            average_loss_r=1.0, calibrated=True, trades_observed=500,
        )

        assert estimate.available is False
        assert estimate.probability is None

    def test_a_sample_with_no_losses_cannot_bound_ruin(self):
        """The formula would return 0.0 — the most confident lie available."""
        estimate = stress.risk_of_ruin(
            win_rate=1.0, payoff_ratio=1.5, risk_fraction=0.01,
            average_loss_r=1.0, calibrated=True, trades_observed=500,
        )

        assert estimate.available is False
        assert estimate.probability is None
        assert "no losing trades" in estimate.reason

    def test_nonsense_risk_fraction_is_refused(self):
        for fraction in (0.0, -0.01, 1.5):
            estimate = stress.risk_of_ruin(
                win_rate=0.55, payoff_ratio=1.5, risk_fraction=fraction,
                average_loss_r=1.0, calibrated=True, trades_observed=500,
            )

            assert estimate.available is False

    def test_unavailable_payload_carries_no_number(self):
        payload = stress.risk_of_ruin(
            win_rate=0.55, payoff_ratio=1.5, risk_fraction=0.01,
            average_loss_r=1.0, calibrated=False, trades_observed=500,
        ).as_dict()

        assert payload["available"] is False
        assert "probability" not in payload


class TestRuinArithmetic:
    def test_even_money_matches_the_classic_gamblers_ruin(self):
        """With a 1:1 payoff the root collapses to q/p, so the answer is (q/p)^N.

        Checked against the closed form because the solver is a bisection on a
        functional equation, and a bisection that converges to the wrong root
        produces a number that looks entirely reasonable.
        """
        estimate = stress.risk_of_ruin(
            win_rate=0.6, payoff_ratio=1.0, risk_fraction=0.05,
            average_loss_r=1.0, calibrated=True, trades_observed=500,
        )

        assert estimate.probability == pytest.approx((0.4 / 0.6) ** 20, rel=1e-6)

    def test_no_edge_means_certain_ruin(self):
        estimate = stress.risk_of_ruin(
            win_rate=0.4, payoff_ratio=1.0, risk_fraction=0.01,
            average_loss_r=1.0, calibrated=True, trades_observed=500,
        )

        assert estimate.probability == 1.0
        assert estimate.certain is True
        assert "expectancy" in estimate.note

    def test_certainty_from_no_edge_is_distinguishable_from_bad_sizing(self):
        """Only one of the two can be fixed by trading smaller."""
        sizing = stress.risk_of_ruin(
            win_rate=0.55, payoff_ratio=1.5, risk_fraction=0.9,
            average_loss_r=1.0, calibrated=True, trades_observed=500,
        )

        assert sizing.certain is False

    def test_larger_positions_raise_ruin(self):
        """The core monotonicity: size is the lever, not the edge.

        Both sizes are kept coarse enough to stay above the reporting floor.
        The same edge at 1% per trade is 100 units deep and its ruin is finer
        than the win rate underneath it, which the next test covers.
        """
        small = stress.risk_of_ruin(
            win_rate=0.55, payoff_ratio=1.5, risk_fraction=0.05,
            average_loss_r=1.0, calibrated=True, trades_observed=500,
        )
        large = stress.risk_of_ruin(
            win_rate=0.55, payoff_ratio=1.5, risk_fraction=0.1,
            average_loss_r=1.0, calibrated=True, trades_observed=500,
        )

        assert small.probability < large.probability

    def test_a_size_the_sample_cannot_resolve_is_named_not_printed(self):
        """The monotonicity taken to its limit stops being a number.

        One standard error on a hit rate measured over 500 trades moves a
        1e-20 ruin probability by ten orders of magnitude, so publishing it
        would be the same confident lie as a ruin figure from an imagined win
        rate. "Negligible" is the honest form, and it stays distinguishable
        from "unknown".
        """
        estimate = stress.risk_of_ruin(
            win_rate=0.55, payoff_ratio=1.5, risk_fraction=0.01,
            average_loss_r=1.0, calibrated=True, trades_observed=500,
        )

        assert estimate.probability is None
        assert estimate.negligible is True
        assert estimate.available is False

    def test_a_shallower_ruin_threshold_is_more_likely_to_be_hit(self):
        shallow = stress.risk_of_ruin(
            win_rate=0.55, payoff_ratio=1.5, risk_fraction=0.01,
            average_loss_r=1.0, calibrated=True, trades_observed=500, ruin_drawdown_pct=0.1,
        )
        total = stress.risk_of_ruin(
            win_rate=0.55, payoff_ratio=1.5, risk_fraction=0.01,
            average_loss_r=1.0, calibrated=True, trades_observed=500, ruin_drawdown_pct=0.3,
        )

        assert shallow.probability > total.probability

    def test_units_of_capital_are_reported(self):
        estimate = stress.risk_of_ruin(
            win_rate=0.55, payoff_ratio=1.5, risk_fraction=0.01,
            average_loss_r=1.0, calibrated=True, trades_observed=500,
        )

        assert estimate.units == pytest.approx(100.0)


# ============================================================ consecutive loss
class TestConsecutiveLoss:
    def test_exact_small_case(self):
        """Two coin flips, both losing: 0.25 and nothing approximate about it."""
        assert stress.consecutive_loss_probability(0.5, 2, 2) == pytest.approx(0.25)

    def test_three_in_three(self):
        assert stress.consecutive_loss_probability(0.5, 3, 3) == pytest.approx(0.125)

    def test_overlapping_runs_are_not_double_counted(self):
        """P(a run of 2 in 3 flips) is 3/8 — the naive q^k·n shorthand says 0.5."""
        assert stress.consecutive_loss_probability(0.5, 2, 3) == pytest.approx(0.375)

    def test_a_run_that_cannot_fit_is_a_measured_zero_not_a_null(self):
        """The distinction the caller must be able to make."""
        result = stress.consecutive_loss_probability(0.5, 10, 3)

        assert result == 0.0
        assert result is not None

    def test_invalid_inputs_are_null_not_zero(self):
        assert stress.consecutive_loss_probability(1.5, 3, 10) is None
        assert stress.consecutive_loss_probability(-0.1, 3, 10) is None
        assert stress.consecutive_loss_probability(0.5, 0, 10) is None
        assert stress.consecutive_loss_probability(0.5, 3, 0) is None

    def test_never_winning_makes_any_fitting_streak_certain(self):
        assert stress.consecutive_loss_probability(0.0, 5, 5) == pytest.approx(1.0)

    def test_never_losing_makes_every_streak_impossible(self):
        assert stress.consecutive_loss_probability(1.0, 2, 50) == pytest.approx(0.0)

    def test_longer_windows_make_streaks_likelier(self):
        short = stress.consecutive_loss_probability(0.55, 4, 20)
        long = stress.consecutive_loss_probability(0.55, 4, 200)

        assert long > short

    def test_longer_streaks_are_rarer(self):
        assert stress.consecutive_loss_probability(
            0.55, 6, 50
        ) < stress.consecutive_loss_probability(0.55, 3, 50)


class TestDailyLoss:
    def test_exact_two_trade_day(self):
        """At 1 R a trade, only two losses spend a 2 R limit: 0.5² = 0.25."""
        probability = stress.daily_loss_probability(
            win_rate=0.5, average_win_r=1.0, average_loss_r=1.0,
            trades_per_day=2, limit_r=2.0,
        )

        assert probability == pytest.approx(0.25)

    def test_scattered_losses_still_spend_the_limit(self):
        """Four losses around two wins reach the limit as surely as four in a row."""
        scattered = stress.daily_loss_probability(
            win_rate=0.5, average_win_r=0.1, average_loss_r=1.0,
            trades_per_day=6, limit_r=3.0,
        )
        consecutive = stress.consecutive_loss_probability(0.5, 3, 6)

        assert scattered > consecutive

    def test_invalid_inputs_return_null(self):
        assert stress.daily_loss_probability(
            win_rate=0.5, average_win_r=1.0, average_loss_r=1.0,
            trades_per_day=0, limit_r=3.0,
        ) is None
        assert stress.daily_loss_probability(
            win_rate=0.5, average_win_r=1.0, average_loss_r=0.0,
            trades_per_day=5, limit_r=3.0,
        ) is None


# ============================================================== concentration
class TestConcentration:
    def test_an_empty_book_has_no_concentration_to_measure(self):
        """Not 0.0: an empty book and a perfectly spread one are different facts."""
        result = stress.concentration([], correlation=1.0)

        assert result.known is True
        assert result.total_risk_r == 0.0
        assert result.largest_share is None
        assert result.herfindahl is None

    def test_an_unsupplied_book_is_not_an_empty_one(self):
        """The likeliest caller mistake, and it used to buy the best answer."""
        result = stress.concentration(stress.UNKNOWN_OPEN_BOOK, correlation=1.0)

        assert result.known is False
        assert result.total_risk_r is None
        assert result.worst_case_loss_r is None
        assert "not supplied" in result.reason

    def test_a_position_of_unmeasured_risk_is_not_a_position_risking_nothing(self):
        result = stress.concentration([1.0, None, 0.5], correlation=1.0)

        assert result.known is False
        assert result.worst_case_loss_r is None
        assert "no measured risk" in result.reason

    def test_a_book_of_breakeven_stops_genuinely_risks_nothing(self):
        """The mirror of the case above: this zero is a measurement."""
        result = stress.concentration([0.0, 0.0], correlation=1.0)

        assert result.known is True
        assert result.worst_case_loss_r == 0.0

    def test_one_position_is_wholly_concentrated(self):
        result = stress.concentration([1.0], correlation=0.0)

        assert result.largest_share == pytest.approx(1.0)
        assert result.herfindahl == pytest.approx(1.0)
        assert result.effective_positions == pytest.approx(1.0)

    def test_four_independent_one_r_positions_still_lose_four_r(self):
        """The defect this replaces: quadrature was published as the loss.

        Independent stops can all fill on the same morning — independence makes
        that morning rarer, not cheaper. The quadrature figure is the standard
        deviation of a sum of independent P&Ls, and reporting it as the loss
        understated the book by sqrt(n).
        """
        result = stress.concentration([1.0, 1.0, 1.0, 1.0], correlation=0.0)

        assert result.worst_case_loss_r == pytest.approx(4.0)
        assert result.correlated_loss_r == pytest.approx(2.0)
        assert result.effective_positions == pytest.approx(4.0)

    def test_the_worst_case_does_not_depend_on_correlation(self):
        losses = [
            stress.concentration([1.0, 0.5, 0.75], correlation=rho).worst_case_loss_r
            for rho in (0.0, 0.5, 1.0)
        ]

        assert losses == [pytest.approx(2.25)] * 3

    def test_full_correlation_collapses_the_two_figures(self):
        result = stress.concentration([1.0, 1.0, 1.0, 1.0], correlation=1.0)

        assert result.correlated_loss_r == pytest.approx(4.0)
        assert result.worst_case_loss_r == pytest.approx(4.0)

    def test_the_equicorrelation_form_is_used_not_a_linear_blend(self):
        """A linear blend sits below sqrt at every rho, so it was permissive."""
        result = stress.concentration([1.0, 1.0, 1.0, 1.0], correlation=0.5)
        linear_blend = 0.5 * 2.0 + 0.5 * 4.0

        assert result.correlated_loss_r == pytest.approx(math.sqrt(0.5 * 4 + 0.5 * 16))
        assert result.correlated_loss_r > linear_blend

    def test_correlation_only_ever_increases_the_loss(self):
        risks = [1.0, 0.5, 0.75]
        losses = [
            stress.concentration(risks, correlation=rho).correlated_loss_r
            for rho in (0.0, 0.25, 0.5, 0.75, 1.0)
        ]

        assert losses == sorted(losses)

    def test_unmeasured_correlation_is_treated_as_total(self):
        """Unmeasured is not uncorrelated, and no flag can say otherwise."""
        unmeasured = stress.concentration([1.0, 1.0, 1.0], correlation=None)

        assert unmeasured.correlation_used == 1.0
        assert unmeasured.correlation_measured is False
        assert unmeasured.correlated_loss_r == pytest.approx(3.0)

    def test_loss_multiplier_scales_the_book(self):
        base = stress.concentration([1.0, 1.0], correlation=1.0)
        doubled = stress.concentration([1.0, 1.0], correlation=1.0, loss_multiplier=2.0)

        assert doubled.correlated_loss_r == pytest.approx(base.correlated_loss_r * 2)
        assert doubled.worst_case_loss_r == pytest.approx(base.worst_case_loss_r * 2)


# =================================================================== evaluate
class TestEvaluateRefusals:
    def test_too_few_trades_reports_insufficient_not_a_percentage(self):
        result = stress.evaluate(
            stress.BASE,
            history=stress.TradeHistory(trades=8, wins=5, average_loss_r=1.0),
            r_value_pct=0.005,
        )

        assert result.available is False
        assert result.projected_drawdown_pct is None
        assert "resolved trades" in result.reason

    def test_an_unrunnable_scenario_never_approves(self):
        """A stress test that did not run is not a stress test that passed."""
        result = stress.evaluate(
            stress.EXTREME,
            history=stress.TradeHistory(trades=8, wins=5),
            r_value_pct=0.005,
        )

        assert result.verdict is not RiskVerdict.APPROVE

    def test_unknown_r_value_cannot_be_compared_to_a_ceiling(self):
        result = stress.evaluate(stress.BASE, history=measured(), r_value_pct=0.0)

        assert result.available is False
        assert result.verdict is RiskVerdict.REDUCE

    def test_uncalibrated_history_still_projects_but_reports_no_ruin(self):
        """Drawdown is arithmetic on measured trades; ruin needs calibration."""
        result = stress.evaluate(
            stress.BASE, history=measured(calibrated=False), r_value_pct=0.0025,
            open_risk_r=[]
        )

        assert result.available is True
        assert result.projected_drawdown_r is not None
        assert result.ruin.available is False


class TestEvaluateProjection:
    def test_a_well_sized_account_survives_the_extreme(self):
        result = stress.evaluate(
            stress.EXTREME, history=measured(), r_value_pct=0.0025, trades_per_day=2,
            open_risk_r=[]
        )

        assert result.survives is True
        assert result.verdict is not RiskVerdict.BLOCK

    def test_the_same_strategy_sized_at_one_percent_does_not(self):
        """The module discriminates on size, which is the only lever there is."""
        result = stress.evaluate(
            stress.EXTREME, history=measured(), r_value_pct=0.01, trades_per_day=2,
            open_risk_r=[]
        )

        assert result.survives is False
        assert result.verdict is RiskVerdict.BLOCK

    def test_a_breach_reports_the_size_that_would_survive(self):
        """'0.4% instead of 1%' is actionable where 'blocked' is only frustrating."""
        result = stress.evaluate(
            stress.EXTREME, history=measured(), r_value_pct=0.012, open_risk_r=[]
        )

        assert result.survives is False
        assert result.survivable_r_value_pct is not None
        assert 0 < result.survivable_r_value_pct < 0.012

    def test_severity_never_improves_the_projection(self):
        """The adversarial property: no scenario is kinder than the one before it."""
        drawdowns = [
            stress.evaluate(
                scenario, history=measured(), r_value_pct=0.002, measured_correlation=0.0,
                open_risk_r=[1.0, 1.0],
            ).projected_drawdown_r
            for scenario in stress.SCENARIOS
        ]

        assert drawdowns == sorted(drawdowns)

    def test_existing_drawdown_eats_the_remaining_ceiling(self):
        fresh = stress.evaluate(
            stress.STRESS, history=measured(), r_value_pct=0.004, open_risk_r=[]
        )
        wounded = stress.evaluate(
            stress.STRESS, history=measured(), r_value_pct=0.004,
            current_drawdown_pct=0.085, open_risk_r=[]
        )

        assert fresh.survives is True
        assert wounded.survives is False

    def test_already_at_the_ceiling_blocks_before_any_projection(self):
        result = stress.evaluate(
            stress.BASE, history=measured(), r_value_pct=0.005, current_drawdown_pct=0.10
        )

        assert result.verdict is RiskVerdict.BLOCK
        assert any("before any stress" in b for b in result.breaches)

    def test_both_streak_lengths_are_reported(self):
        result = stress.evaluate(stress.BASE, history=measured(), r_value_pct=0.002)

        assert result.severe_streak >= result.typical_streak


class TestUncertaintyOnlyTightens:
    def test_unmeasured_correlation_stresses_the_book_as_one_position(self):
        book = [1.0, 1.0, 1.0, 1.0]

        known = stress.evaluate(
            stress.BASE, history=measured(), r_value_pct=0.002,
            open_risk_r=book, measured_correlation=0.0,
        )
        unknown = stress.evaluate(
            stress.BASE, history=measured(), r_value_pct=0.002,
            open_risk_r=book, measured_correlation=None,
        )

        # The worst case is the same 4 R either way — every stop can fill on
        # one morning whatever the correlation. What measuring it changes is
        # the ordinary bad day, and only in the direction of a smaller number.
        assert known.open_book_loss_r == pytest.approx(4.0)
        assert unknown.open_book_loss_r == pytest.approx(4.0)
        assert known.open_book_correlated_loss_r == pytest.approx(2.0)
        assert unknown.open_book_correlated_loss_r == pytest.approx(4.0)
        assert any("single position" in w for w in unknown.warnings)

    def test_the_base_case_is_not_exempt_from_the_correlation_rule(self):
        """Starting from an optimistic premise would make all four scenarios wrong."""
        result = stress.evaluate(
            stress.BASE, history=measured(), r_value_pct=0.002,
            open_risk_r=[1.0, 1.0], measured_correlation=None,
        )

        assert result.concentration.correlation_used == 1.0

    def test_concentrated_books_are_named(self):
        result = stress.evaluate(
            stress.BASE, history=measured(), r_value_pct=0.002,
            open_risk_r=[3.0, 0.25, 0.25], measured_correlation=0.0,
        )

        assert any("one position" in w for w in result.warnings)

    def test_open_book_alone_can_breach_without_any_history(self):
        """A fact about the positions, not a projection from past performance."""
        result = stress.evaluate(
            stress.EXTREME,
            history=stress.TradeHistory(trades=3, wins=2),
            r_value_pct=0.02,
            open_risk_r=[1.0, 1.0, 1.0, 1.0],
        )

        assert result.available is False
        assert result.verdict is RiskVerdict.BLOCK
        assert any("open positions alone" in b for b in result.breaches)

    def test_unmeasured_trading_frequency_is_named_not_guessed(self):
        result = stress.evaluate(stress.BASE, history=measured(), r_value_pct=0.002)

        assert result.daily_loss_probability is None
        assert any("trades per day not measured" in w for w in result.warnings)

    def test_daily_loss_risk_is_estimated_when_frequency_is_known(self):
        result = stress.evaluate(
            stress.BASE, history=measured(), r_value_pct=0.002, trades_per_day=6
        )

        assert result.daily_loss_probability is not None

    def test_negative_measured_expectancy_is_called_out_in_every_scenario(self):
        losing = measured(wins=60, average_win_r=1.0, average_loss_r=1.0)

        for scenario in stress.SCENARIOS:
            result = stress.evaluate(scenario, history=losing, r_value_pct=0.001)

            assert any("expectancy" in w for w in result.warnings)


# ==================================================================== run_all
class TestRunAll:
    def test_every_scenario_is_returned_including_the_passing_ones(self):
        report = stress.run_all(history=measured(), r_value_pct=0.002)

        assert set(report.scenarios) == {"base", "adverse", "stress", "extreme"}

    def test_the_worst_verdict_wins(self):
        report = stress.run_all(history=measured(), r_value_pct=0.01, trades_per_day=2)

        assert report.verdict is RiskVerdict.BLOCK
        assert report.scenarios["base"].verdict is not RiskVerdict.BLOCK

    def test_an_extreme_breach_blocks_the_whole_report(self):
        report = stress.run_all(history=measured(), r_value_pct=0.01)

        assert any(b.startswith("extreme:") for b in report.breaches)
        assert report.cleared is False

    def test_a_conservatively_sized_account_clears(self):
        """A module that can never approve is as useless as one that always does."""
        report = stress.run_all(
            history=measured(), r_value_pct=0.002, trades_per_day=1, open_risk_r=[],
        )

        assert report.cleared is True
        assert report.verdict is RiskVerdict.APPROVE

    def test_cleared_and_verdict_answer_different_questions(self):
        """'Survivable, trade smaller' must not read the same as 'we could not tell'."""
        unknown = stress.run_all(
            history=stress.TradeHistory(trades=5, wins=3), r_value_pct=0.002
        )

        assert unknown.verdict is RiskVerdict.REDUCE
        assert unknown.cleared is False

    def test_report_ruin_comes_from_measured_history_not_a_shock(self):
        report = stress.run_all(history=measured(), r_value_pct=0.002)

        assert report.ruin.win_rate == pytest.approx(0.55)

    def test_a_tighter_hard_ceiling_can_only_tighten_the_verdict(self):
        loose = stress.run_all(history=measured(), r_value_pct=0.004)
        tight = stress.run_all(
            history=measured(), r_value_pct=0.004,
            hard=HardLimits(max_total_drawdown_pct=0.03),
        )

        assert len(tight.breaches) >= len(loose.breaches)

    def test_no_report_claims_execution_authority(self):
        payload = stress.run_all(history=measured(), r_value_pct=0.002).as_dict()

        assert payload["authorises_execution"] is False
        assert "phase 25" in payload["note"]

    def test_payload_of_a_refusal_carries_the_reason_not_a_number(self):
        payload = stress.run_all(
            history=stress.TradeHistory(trades=4, wins=2), r_value_pct=0.002
        ).as_dict()

        assert payload["risk_of_ruin"]["available"] is False
        assert payload["scenarios"]["extreme"]["projected_drawdown_pct"] is None
        assert payload["scenarios"]["extreme"]["reason"]


# ======================================================== review reproductions
class TestReviewReproductions:
    """Temporary reproductions of the adversarial review's findings."""

    def test_an_unsupplied_open_book_is_not_an_empty_one(self):
        report = stress.run_all(history=measured(), r_value_pct=0.002, trades_per_day=1)

        assert report.cleared is False
        assert any("open" in w for w in report.warnings)

    def test_four_independent_one_r_positions_can_lose_four_r(self):
        result = stress.evaluate(
            stress.BASE, history=measured(), r_value_pct=0.002,
            open_risk_r=[1.0, 1.0, 1.0, 1.0], measured_correlation=0.0,
        )

        assert result.open_book_loss_r == pytest.approx(4.0)

    def test_the_interpolation_uses_the_equicorrelation_form(self):
        result = stress.concentration([1.0, 1.0, 1.0, 1.0], correlation=0.5)

        assert result.correlated_loss_r == pytest.approx(math.sqrt(0.5 * 4.0 + 0.5 * 16.0))

    def test_impossible_history_is_refused(self):
        with pytest.raises(ValueError):
            stress.TradeHistory(
                trades=200, wins=300, average_win_r=1.5, average_loss_r=1.0, calibrated=True
            )

    def test_ruin_depends_on_the_size_of_the_average_loss(self):
        small = stress.run_all(
            history=measured(average_loss_r=0.5, average_win_r=0.75), r_value_pct=0.05
        )
        large = stress.run_all(
            history=measured(average_loss_r=2.0, average_win_r=3.0), r_value_pct=0.05
        )

        assert large.ruin.probability > small.ruin.probability

    def test_ruin_does_not_underflow_to_zero(self):
        estimate = stress.risk_of_ruin(
            win_rate=0.55, payoff_ratio=1.5, risk_fraction=0.0005,
            average_loss_r=1.0, calibrated=True, trades_observed=500,
        )

        assert estimate.probability is None
        assert estimate.negligible is True
        assert estimate.as_dict()["below"] == stress.MIN_REPORTABLE_RUIN

    def test_ruin_counts_only_the_capital_that_is_left(self):
        fresh = stress.run_all(history=measured(), r_value_pct=0.05)
        wounded = stress.run_all(
            history=measured(), r_value_pct=0.05, current_drawdown_pct=0.09
        )

        assert wounded.ruin.probability > fresh.ruin.probability

    def test_the_suggested_size_survives(self):
        first = stress.evaluate(
            stress.EXTREME, history=measured(), r_value_pct=0.012, open_risk_r=[]
        )
        again = stress.evaluate(
            stress.EXTREME, history=measured(), r_value_pct=first.survivable_r_value_pct,
            open_risk_r=[],
        )

        assert again.survives is True

    def test_the_suggested_size_survives_with_an_open_book(self):
        first = stress.evaluate(
            stress.EXTREME, history=measured(), r_value_pct=0.008,
            open_risk_r=[2.0], measured_correlation=0.0,
        )
        again = stress.evaluate(
            stress.EXTREME, history=measured(), r_value_pct=first.survivable_r_value_pct,
            open_risk_r=[2.0], measured_correlation=0.0,
        )

        assert again.survives is True

    def test_the_stress_case_is_built_on_the_severe_streak(self):
        result = stress.evaluate(
            stress.STRESS, history=measured(), r_value_pct=0.004, open_risk_r=[]
        )

        assert result.severe_streak > result.typical_streak
        assert result.streak_drawdown_r == pytest.approx(
            result.severe_streak * result.assumed_average_loss_r
        )

    def test_a_zero_horizon_is_refused(self):
        result = stress.evaluate(
            stress.BASE, history=measured(), r_value_pct=0.002, horizon_trades=0
        )

        assert result.available is False

    def test_unmeasured_position_risk_is_not_a_measured_zero(self):
        result = stress.concentration([None, None, None], correlation=1.0)

        assert result.correlated_loss_r is None
