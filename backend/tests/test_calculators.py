"""The trader's calculators, and the refusal that makes them worth trusting.

These are ordinary tools - every broker's website has them. The reason to build
them again is that most of those assume a contract specification, and the
assumption is invisible and wrong by a factor of ten on some instruments.

Most of this file is about the refusals. A lot-size calculator that silently
assumes a standard lot is the difference between risking 1% and 10%, and it
looks correct in both cases.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.services import calculators as calc


class TestNothingIsComputedFromAnAssumedSpecification:
    def test_no_tick_value_refuses_and_names_it(self):
        result = calc.lot_size(
            symbol="XAUUSD",
            equity=10000,
            risk_percent=1,
            stop_distance_price=5.0,
            tick_value=None,
            tick_size=0.01,
        )

        assert result["available"] is False
        assert result["missing"] == "tick_value"

    def test_no_tick_value_refuses_a_pip_price_too(self):
        result = calc.pip_value(
            symbol="EURUSD",
            lots=1.0,
            contract_size=100000,
            tick_value=None,
            tick_size=0.00001,
        )

        assert result["available"] is False

    def test_a_zero_tick_value_is_treated_as_absent(self):
        """The bridge publishes 0.0 when the broker supplied nothing, and zero
        divides into an infinite position."""
        result = calc.lot_size(
            symbol="EURUSD",
            equity=10000,
            risk_percent=1,
            stop_distance_price=0.0025,
            tick_value=0.0,
            tick_size=0.00001,
        )

        assert result["available"] is False


class TestLotSizing:
    def sized(self, **overrides):
        args = dict(
            symbol="EURUSD",
            equity=10000.0,
            risk_percent=1.0,
            stop_distance_price=0.0025,
            tick_value=1.0,
            tick_size=0.00001,
            volume_min=0.01,
            volume_step=0.01,
        )
        args.update(overrides)
        return calc.lot_size(**args)

    def test_the_risk_taken_matches_the_risk_asked_for(self):
        result = self.sized()

        assert result["actual_risk_percent"] == pytest.approx(1.0, abs=0.05)

    def test_it_rounds_down_never_up(self):
        """Rounding up exceeds the requested risk on every trade rather than
        occasionally."""
        result = self.sized(volume_step=0.1)

        assert result["lots"] <= result["lots_exact"]
        assert result["actual_risk_percent"] <= result["risk_percent"]

    def test_a_size_below_the_brokers_minimum_reports_nothing_tradeable(self):
        """Taking the minimum instead would risk more than was asked, silently."""
        result = self.sized(equity=100.0, volume_min=1.0, volume_step=1.0)

        assert result["tradeable"] is False
        assert result["lots"] == 0.0
        assert "would risk" in result["reason"]

    def test_a_zero_stop_refuses_rather_than_sizing_to_infinity(self):
        result = self.sized(stop_distance_price=0.0)

        assert result["available"] is False

    def test_a_wider_stop_gives_a_smaller_size(self):
        narrow = self.sized(stop_distance_price=0.0010)["lots"]
        wide = self.sized(stop_distance_price=0.0100)["lots"]

        assert wide < narrow


class TestPipValue:
    def test_a_jpy_pair_uses_a_different_pip(self):
        """0.01 on JPY quotes, 0.0001 elsewhere - a convention, and one this
        publishes rather than hides."""
        assert calc.pip_size("USDJPY") == 0.01
        assert calc.pip_size("EURUSD") == 0.0001

    def test_the_convention_is_published_with_the_answer(self):
        """So a broker that disagrees is visible rather than silently wrong."""
        result = calc.pip_value(
            symbol="EURUSD", lots=1, contract_size=100000, tick_value=1.0, tick_size=0.00001
        )

        assert "assumed" in result
        assert "0.0001" in result["assumed"]

    def test_value_scales_with_size(self):
        one = calc.pip_value(
            symbol="EURUSD", lots=1, contract_size=100000, tick_value=1.0, tick_size=0.00001
        )
        two = calc.pip_value(
            symbol="EURUSD", lots=2, contract_size=100000, tick_value=1.0, tick_size=0.00001
        )

        assert two["value"] == pytest.approx(one["value"] * 2)


class TestSessions:
    def test_the_london_new_york_overlap_is_reported(self):
        """It carries most of the day's volume, and a spread quoted outside it
        is not the spread a backtest assumed."""
        result = calc.sessions_at(datetime(2026, 8, 17, 14, 0, tzinfo=UTC))

        assert "London" in result["open"]
        assert "New York" in result["open"]
        assert result["overlap"] is True

    def test_a_session_crossing_midnight_is_handled(self):
        """Sydney opens at 21:00 and closes at 06:00. A naive between-check
        reports it closed for the nine hours it is actually open."""
        result = calc.sessions_at(datetime(2026, 8, 17, 23, 0, tzinfo=UTC))

        assert "Sydney" in result["open"]

    def test_the_quiet_hour_reports_no_overlap(self):
        result = calc.sessions_at(datetime(2026, 8, 17, 10, 0, tzinfo=UTC))

        assert result["overlap"] is False

    def test_the_approximation_is_stated(self):
        """Presenting these to the minute would claim a precision the concept
        does not have."""
        assert "approximate" in calc.sessions_at()["note"]


class TestVolatility:
    def test_it_is_labelled_as_a_measure_not_a_forecast(self):
        """A number describing yesterday, presented as one predicting tomorrow,
        is how a risk tool becomes a source of confidence."""
        result = calc.volatility(symbol="EURUSD", atr=0.0025, price=1.1000)

        assert "not a forecast" in result["note"]

    def test_the_percentage_is_the_comparable_figure(self):
        """Gold moving 20 dollars and EURUSD moving 20 pips are the same
        statement only as a percentage."""
        gold = calc.volatility(symbol="XAUUSD", atr=24.0, price=2400.0)
        euro = calc.volatility(symbol="EURUSD", atr=0.011, price=1.1000)

        assert gold["atr_percent"] == pytest.approx(euro["atr_percent"], abs=0.01)

    def test_a_missing_atr_refuses(self):
        result = calc.volatility(symbol="EURUSD", atr=None, price=1.1)

        assert result["available"] is False
