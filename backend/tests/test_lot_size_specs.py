"""A broker can publish a wrong tick value, and this one did.

On 2026-09-02 term-g's terminal reported XAUUSD `tick_value` 0.1 against a
0.01 tick - ten dollars per point per lot. The live position proved a
hundred: 1.22 lots moved $100 per dollar of gold, not $10. The sizing had
opened a position it believed carried $373 of risk and which actually
carried $3,731, 1.87% of a 200,000 account against a configured 0.75%.

The numbers in these tests are that account's, read off the terminal.
"""

from __future__ import annotations

import pytest

from app.services import calculators

# Read from term-g's molido_symbols.json on 2026-09-02. The gold line is the
# wrong one; the other two agree with the account's own profit and loss to
# four figures, which is how the fault was localised to one symbol.
XAUUSD = dict(tick_value=0.1, tick_size=0.01, contract_size=100.0, volume_min=0.01, volume_step=0.01)
XAUEUR = dict(tick_value=1.15866, tick_size=0.01, contract_size=100.0, volume_min=0.01, volume_step=0.01)
CADJPY = dict(tick_value=0.62981414, tick_size=0.001, contract_size=100000.0, volume_min=0.01, volume_step=0.01)
EURUSD = dict(tick_value=1.0, tick_size=1e-05, contract_size=100000.0, volume_min=0.01, volume_step=0.01)


def size(symbol: str, spec: dict, *, stop: float, equity: float = 200_000.0, risk: float = 0.75, currency="USD"):
    return calculators.lot_size(
        symbol=symbol,
        equity=equity,
        risk_percent=risk,
        stop_distance_price=stop,
        account_currency=currency,
        **spec,
    )


class TestTheQuoteCurrencyIsReadOnlyWhenItIsCertain:
    @pytest.mark.parametrize(
        ("symbol", "expected"),
        [("EURUSD", "USD"), ("XAUUSD", "USD"), ("CADJPY", "JPY"), ("XAUEUR", "EUR")],
    )
    def test_a_six_letter_name_names_its_quote(self, symbol, expected):
        assert calculators.quote_currency(symbol) == expected

    @pytest.mark.parametrize("symbol", [".US500Cash", "BRENT", "", "US30", "EURUSD.pro"])
    def test_anything_else_is_not_guessed(self, symbol):
        """A guess here is a guess about how much money a position risks."""
        assert calculators.quote_currency(symbol) is None


class TestTheGoldPositionThatWasTooBig:
    STOP = 30.58  # 7.5 x ATR, as the live position carried it

    def test_the_broker_figure_alone_sizes_it_five_times_too_large(self):
        """What shipped: $10 per point believed, $100 charged."""
        naive = calculators.lot_size(
            symbol="XAUUSD",
            equity=200_000.0,
            risk_percent=0.75,
            stop_distance_price=self.STOP,
            tick_value=0.1,
            tick_size=0.01,
            volume_min=0.01,
            volume_step=0.01,
        )

        assert naive["lots"] == pytest.approx(4.9, abs=0.05)
        # And the true risk of that size, at $100 a point:
        assert 4.9 * self.STOP * 100 / 200_000 * 100 == pytest.approx(7.5, abs=0.1)

    def test_the_contract_size_cross_check_sizes_it_correctly(self):
        sized = size("XAUUSD", XAUUSD, stop=self.STOP)

        assert sized["lots"] == pytest.approx(0.49, abs=0.005)
        assert sized["actual_risk"] == pytest.approx(1498.4, abs=5)
        assert sized["actual_risk_percent"] == pytest.approx(0.75, abs=0.01)

    def test_it_says_why_the_position_is_smaller(self):
        sized = size("XAUUSD", XAUUSD, stop=self.STOP)

        assert "understated by 10.0x" in sized["spec_disagreement"]
        assert "quoted in USD" in sized["spec_disagreement"]

    def test_the_position_actually_open_was_1_87_percent(self):
        """The arithmetic that made this a finding rather than a suspicion."""
        assert 1.22 * self.STOP * 100 / 199_797 * 100 == pytest.approx(1.87, abs=0.01)


class TestTheSymbolsThatWereAlreadyRight:
    def test_a_yen_quote_keeps_its_tick_value(self):
        """CADJPY pays in yen. Its contract size says nothing about dollars
        without a conversion this function does not have, and using it would
        size 158 times too small."""
        sized = size("CADJPY", CADJPY, stop=0.484)

        assert sized["spec_disagreement"] is None
        assert sized["loss_per_lot"] == pytest.approx(304.8, abs=1.0)

    def test_gold_in_euro_keeps_its_tick_value(self):
        sized = size("XAUEUR", XAUEUR, stop=24.93)

        assert sized["spec_disagreement"] is None
        assert sized["loss_per_lot"] == pytest.approx(2888.5, abs=5)

    def test_a_pair_whose_two_figures_agree_is_untouched(self):
        sized = size("EURUSD", EURUSD, stop=0.0026)

        assert sized["spec_disagreement"] is None
        assert sized["loss_per_lot"] == pytest.approx(260.0, abs=0.5)


class TestTheCheckCanOnlyShrinkAPosition:
    def test_a_contract_size_smaller_than_the_tick_value_implies_is_ignored(self):
        """Only upward. If the currency reading is ever wrong, the cost is a
        position smaller than intended - the direction a sizing bug should
        fail in - and never a larger one."""
        spec = dict(XAUUSD, tick_value=10.0, contract_size=1.0)
        sized = size("XAUUSD", spec, stop=10.0)

        assert sized["spec_disagreement"] is None
        assert sized["loss_per_lot"] == pytest.approx(10_000.0)

    def test_a_missing_contract_size_changes_nothing(self):
        spec = dict(XAUUSD)
        spec.pop("contract_size")
        sized = size("XAUUSD", spec, stop=30.58)

        assert sized["spec_disagreement"] is None

    def test_an_unknown_account_currency_changes_nothing(self):
        sized = size("XAUUSD", XAUUSD, stop=30.58, currency=None)

        assert sized["spec_disagreement"] is None

    def test_a_five_per_cent_gap_is_slack_not_a_fault(self):
        """A broker quoting a tick value that includes a small fee must not
        trip this; ten times is not slack."""
        spec = dict(XAUUSD, tick_value=0.98, contract_size=100.0)
        sized = size("XAUUSD", spec, stop=30.58)

        assert sized["spec_disagreement"] is None
