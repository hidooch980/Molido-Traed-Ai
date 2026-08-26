"""Interest paid or charged for holding a position, and its sign.

Almost everything here is about the sign. Spread and commission are money
leaving under every circumstance, so getting their direction wrong is caught by
`abs` before it can matter. Carry is the one cost that can be a credit, and an
absolute value applied to it turns a position that earns interest into one that
is charged interest - wrong by twice the carry, and wrong hardest on exactly
the trades where the carry is large enough to change the answer.
"""

from __future__ import annotations

import pytest

from app.brain import carry
from app.brain.expected_value import CostModel, costs_from_context


class TestSign:
    def test_a_long_in_a_paying_pair_is_a_credit(self):
        """AUD/JPY: the RBA charges more than the Bank of Japan.

        Long it, and the difference arrives every night. In a cost model
        positive means money leaving, so this has to be negative.
        """
        cost = carry.swap_cost(differential_pct=3.35, entry=100.0, direction="buy")
        assert cost < 0

    def test_the_same_pair_shorted_is_a_charge(self):
        cost = carry.swap_cost(differential_pct=3.35, entry=100.0, direction="sell")
        assert cost > 0

    def test_the_two_sides_are_equal_and_opposite(self):
        long_side = carry.swap_cost(differential_pct=3.35, entry=100.0, direction="buy")
        short_side = carry.swap_cost(
            differential_pct=3.35, entry=100.0, direction="sell"
        )
        assert long_side == pytest.approx(-short_side)

    def test_a_negative_differential_reverses_both(self):
        """EUR/USD: the ECB charges less than the Fed, so long it costs."""
        long_side = carry.swap_cost(
            differential_pct=-1.375, entry=1.1666, direction="buy"
        )
        assert long_side > 0

    def test_a_flat_differential_costs_nothing(self):
        assert carry.swap_cost(
            differential_pct=0.0, entry=1.1, direction="buy"
        ) == pytest.approx(0.0)


class TestMagnitude:
    def test_is_the_annual_rate_prorated_over_the_holding_period(self):
        # 3.65% of 100 is 3.65 a year; over ten of 365 days that is 0.10.
        cost = carry.swap_cost(
            differential_pct=3.65, entry=100.0, direction="sell", holding_days=10.0
        )
        assert cost == pytest.approx(0.1)

    def test_scales_with_the_holding_period(self):
        one = carry.swap_cost(
            differential_pct=2.0, entry=100.0, direction="sell", holding_days=1.0
        )
        ten = carry.swap_cost(
            differential_pct=2.0, entry=100.0, direction="sell", holding_days=10.0
        )
        assert ten == pytest.approx(one * 10)

    def test_scales_with_the_price(self):
        """Price units, so a yen pair and a euro pair are not comparable raw."""
        cheap = carry.swap_cost(differential_pct=2.0, entry=1.0, direction="sell")
        dear = carry.swap_cost(differential_pct=2.0, entry=100.0, direction="sell")
        assert dear == pytest.approx(cheap * 100)

    def test_a_zero_day_hold_costs_nothing(self):
        assert carry.swap_cost(
            differential_pct=5.0, entry=100.0, direction="buy", holding_days=0.0
        ) == pytest.approx(0.0)


class TestRefusals:
    def test_an_unknown_direction_is_refused(self):
        with pytest.raises(ValueError):
            carry.swap_cost(differential_pct=1.0, entry=1.0, direction="sideways")

    def test_a_nonpositive_entry_is_refused(self):
        """Carry is expressed as a share of the notional, and the notional is
        the price. Zero would silently produce a costless trade."""
        with pytest.raises(ValueError):
            carry.swap_cost(differential_pct=1.0, entry=0.0, direction="buy")

    def test_a_negative_holding_period_is_refused(self):
        with pytest.raises(ValueError):
            carry.swap_cost(
                differential_pct=1.0, entry=1.0, direction="buy", holding_days=-1.0
            )


class TestTheCostModelKeepsTheSign:
    def test_a_credit_reduces_the_total(self):
        """The whole reason `total` stopped taking the absolute value.

        A position paid to exist should cost less than an identical one that
        is not, and under the old arithmetic it cost more.
        """
        paid = CostModel(spread=0.001, commission=0.0, swap=-0.0005, slippage=0.0)
        charged = CostModel(spread=0.001, commission=0.0, swap=0.0005, slippage=0.0)
        flat = CostModel(spread=0.001, commission=0.0, swap=0.0, slippage=0.0)

        assert paid.total()[0] < flat.total()[0] < charged.total()[0]

    def test_the_other_costs_are_still_magnitudes(self):
        """Their direction says nothing, so a sign convention somebody got
        backwards must not be able to subtract from the total."""
        model = CostModel(spread=-0.001, commission=-0.0002, swap=0.0, slippage=0.0)
        assert model.total()[0] == pytest.approx(0.0012)

    def test_an_absent_swap_is_still_reported_unmeasured(self):
        known, missing = CostModel(spread=0.001).total()
        assert "swap" in missing
        assert known == pytest.approx(0.001)


class TestFallbackPrecedence:
    class FakeSymbol:
        margin_rules = {"swap_per_night": 0.00002}

    def test_the_brokers_own_number_wins(self):
        """It includes their markup; the interbank differential does not.

        A retail swap is commonly several times the differential, so treating
        the estimate as an override would replace the number that will
        actually be charged with a smaller one.
        """
        model = costs_from_context(
            spread=0.0001, broker_symbol=self.FakeSymbol(), carry=-0.5
        )
        assert model.swap == pytest.approx(0.00002)

    def test_the_estimate_fills_the_gap_when_there_is_no_broker(self):
        model = costs_from_context(spread=0.0001, carry=-0.5)
        assert model.swap == pytest.approx(-0.5)
        assert "swap" not in model.total()[1]

    def test_without_either_it_stays_unmeasured_rather_than_zero(self):
        """An unknown swap is not a free position to hold."""
        model = costs_from_context(spread=0.0001)
        assert model.swap is None
        assert "swap" in model.total()[1]
