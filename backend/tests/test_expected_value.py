"""Expected-value tests (phase 21).

EV is the number a system uses to justify risking money, so these tests are
mostly about the circumstances in which it must refuse to produce one.
"""

from __future__ import annotations

import pytest

from app.brain import expected_value as ev
from app.brain.calibration import Bucket, CalibrationReport


def calibrated(observed: float = 0.7) -> CalibrationReport:
    """A report that has earned the word 'probability'.

    Buckets matter: `to_probability` returns the *observed frequency* of the
    bucket a score falls into, not the score itself. That is the whole point of
    calibration — a source that says 80% and is right 55% of the time gets
    0.55, and EV is computed on the truth rather than the claim.
    """
    return CalibrationReport(
        calibrated=True,
        source="council",
        count=500,
        brier=0.18,
        calibration_error=0.03,
        buckets=[
            Bucket(lower=0.0, upper=0.5, count=200, mean_forecast=0.3, observed_rate=0.28),
            Bucket(lower=0.5, upper=1.0, count=300, mean_forecast=0.75, observed_rate=observed),
        ],
    )


def uncalibrated() -> CalibrationReport:
    return CalibrationReport(
        calibrated=False,
        source="council",
        count=12,
        reason="only 12 resolved forecasts, needs 100",
    )


BUY = dict(entry=1.1000, stop=1.0950, target=1.1150, direction="buy")


class TestRefusals:
    def test_uncalibrated_score_yields_no_ev(self):
        """The central rule: conviction is not probability."""
        result = ev.compute(score=0.8, calibration=uncalibrated(), **BUY)

        assert result.available is False
        assert result.verdict == "wait"
        assert "calibrat" in result.reason.lower()

    def test_stop_on_the_wrong_side_is_refused(self):
        result = ev.compute(
            entry=1.10, stop=1.12, target=1.15, direction="buy",
            score=0.8, calibration=calibrated(),
        )

        assert result.available is False
        assert "risk" in result.reason

    def test_target_on_the_wrong_side_is_refused(self):
        result = ev.compute(
            entry=1.10, stop=1.09, target=1.05, direction="buy",
            score=0.8, calibration=calibrated(),
        )

        assert result.available is False

    def test_unknown_direction_is_refused(self):
        result = ev.compute(score=0.8, calibration=calibrated(),
                            entry=1.1, stop=1.09, target=1.12, direction="hedge")

        assert result.available is False


class TestArithmetic:
    def test_reward_and_risk_come_from_the_levels(self):
        result = ev.compute(score=0.7, calibration=calibrated(), **BUY)

        assert result.risk == pytest.approx(0.005)
        assert result.reward == pytest.approx(0.015)
        assert result.reward_risk == pytest.approx(3.0)

    def test_sell_side_distances_are_mirrored(self):
        result = ev.compute(
            entry=1.1000, stop=1.1050, target=1.0850, direction="sell",
            score=0.7, calibration=calibrated(),
        )

        assert result.risk == pytest.approx(0.005)
        assert result.reward == pytest.approx(0.015)

    def test_breakeven_probability_is_reported(self):
        """The honest companion to EV: what hit rate the shape demands."""
        result = ev.compute(score=0.7, calibration=calibrated(), **BUY)

        # 3:1 reward:risk breaks even at 25% before costs.
        assert result.breakeven_probability == pytest.approx(0.25, abs=0.01)

    def test_costs_reduce_expected_value(self):
        free = ev.compute(score=0.7, calibration=calibrated(), **BUY)
        costly = ev.compute(
            score=0.7, calibration=calibrated(),
            costs=ev.CostModel(spread=0.0004, commission=0.0001, swap=0.0, slippage=0.0),
            **BUY,
        )

        assert costly.expected_value < free.expected_value
        assert costly.unmeasured_costs == []


class TestHonesty:
    def test_unmeasured_costs_are_named(self):
        """An EV missing slippage is optimistic by exactly that much."""
        result = ev.compute(
            score=0.7, calibration=calibrated(),
            costs=ev.CostModel(spread=0.0002), **BUY,
        )

        assert "slippage" in result.unmeasured_costs
        assert "commission" in result.unmeasured_costs
        assert any("optimistic" in n for n in result.notes)

    def test_thin_edge_becomes_wait(self):
        """Inside the noise of the cost estimate is not an edge.

        At 1:1 reward:risk the edge is exactly `2p − 1`, so a source that is
        right 51% of the time yields 0.02 R — real on paper, indistinguishable
        from zero once the unmeasured costs are considered.
        """
        result = ev.compute(
            entry=1.1000, stop=1.0900, target=1.1100, direction="buy",
            score=0.6, calibration=calibrated(observed=0.51),
            costs=ev.CostModel(spread=0.0, commission=0.0, swap=0.0, slippage=0.0),
        )

        assert result.available is True
        assert result.probability == pytest.approx(0.51)
        assert result.expected_value_r == pytest.approx(0.02, abs=0.001)
        assert result.verdict == "wait"

    def test_poor_reward_risk_is_refused_whatever_the_probability(self):
        """A 0.3 R:R setup needs a hit rate nothing here has earned."""
        result = ev.compute(
            entry=1.1000, stop=1.0900, target=1.1030, direction="buy",
            score=0.95, calibration=calibrated(),
        )

        assert result.verdict == "wait"
        assert any("reward:risk" in n for n in result.notes)

    def test_good_setup_is_allowed(self):
        result = ev.compute(
            score=0.75, calibration=calibrated(),
            costs=ev.CostModel(spread=0.0001, commission=0.0, swap=0.0, slippage=0.0),
            **BUY,
        )

        assert result.verdict == "trade"
        assert result.expected_value_r > ev.MIN_EV_R

    def test_payload_of_a_refusal_still_says_wait(self):
        payload = ev.compute(score=0.8, calibration=uncalibrated(), **BUY).as_dict()

        assert payload["available"] is False
        assert payload["verdict"] == "wait"


class TestCostAssembly:
    def test_spread_is_crossed_twice(self):
        model = ev.costs_from_context(spread=0.0002)

        assert model.spread == pytest.approx(0.0004)

    def test_slippage_stays_unknown_without_fills(self):
        """Assuming zero slippage would make every EV quietly optimistic."""
        model = ev.costs_from_context(spread=0.0002)

        assert model.slippage is None
        _, missing = model.total()
        assert "slippage" in missing

    def test_broker_costs_are_used_when_configured(self):
        class FakeBrokerSymbol:
            margin_rules = {"commission_per_lot": 0.00007, "swap_per_night": 0.00002}

        model = ev.costs_from_context(spread=0.0002, broker_symbol=FakeBrokerSymbol())

        assert model.commission == pytest.approx(0.00007)
        assert model.swap == pytest.approx(0.00002)
