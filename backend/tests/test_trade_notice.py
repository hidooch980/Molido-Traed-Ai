"""A fill notice that says which account, and never breaks the trade.

The channel could answer questions and could not tell anybody anything, so
learning that an order had filled meant thinking to ask. What matters in the
tests below is the two ways this can go wrong: saying the wrong thing about a
real position, and letting a chat outage reach back into the loop that opened
one.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.integrations import notify, trade_notice

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def notice(**over):
    base = dict(
        terminal="term-g",
        login="111927791",
        symbol="EURUSD",
        side="long",
        lots=0.03,
        fill=1.15904,
        stop=1.15680,
        target=1.16240,
        risk_money=3.96,
        currency="USD",
        risk_percent=0.75,
        strategy="cross-sectional-stretch",
        ticket=10309362681,
        at=NOW,
    )
    base.update(over)
    return trade_notice.position_opened(**base)


class TestTheAccountIsNamedFirst:
    """Eight terminals, and a notice that does not say which one traded is a
    notice that starts a hunt."""

    def test_the_terminal_and_login_are_both_present(self):
        body = notice().body

        assert "term-g" in body
        assert "111927791" in body

    def test_the_account_line_comes_before_the_instrument(self):
        lines = notice().body.splitlines()

        assert lines[0].startswith("حساب")
        assert "EURUSD" not in lines[0]

    def test_a_terminal_with_no_login_still_names_itself(self):
        """Better a partial answer than a notice about nobody."""
        assert "term-g" in notice(login=None).body


class TestEveryNumberIsWhatTheBrokerReturned:
    def test_the_fill_price_is_reported_not_the_intended_one(self):
        assert "1.15904" in notice().body

    def test_the_stop_distance_is_measured_from_the_fill(self):
        """22.4 pips from 1.15904 to 1.15680, not from wherever the rule
        decided."""
        body = notice().body

        assert "22.4 پیپ" in body

    def test_the_target_distance_too(self):
        assert "33.6 پیپ" in notice().body

    def test_a_missing_fill_says_so_rather_than_printing_zero(self):
        body = notice(fill=None).body

        assert "—" in body
        assert "0.0 پیپ" not in body


class TestUnitsAreHonestPerInstrument:
    def test_a_yen_pair_uses_the_yen_pip(self):
        assert trade_notice.pip_size("USDJPY") == pytest.approx(0.01)

    def test_everything_else_uses_the_standard_pip(self):
        assert trade_notice.pip_size("EURUSD") == pytest.approx(0.0001)

    def test_metals_are_not_reported_in_pips_at_all(self):
        """A gold stop of 20.85 is 20.85 dollars an ounce. Calling it 2085
        pips is a number nobody can act on."""
        body = notice(
            symbol="XAUUSD", fill=4328.70, stop=4349.55, target=4297.42
        ).body

        assert "پیپ" not in body
        assert "20.85" in body

    def test_a_metal_is_not_a_pair_despite_being_six_letters(self):
        """XAUUSD wears a pair's shape. Reading it as one turned a 20.85
        dollar stop into 208,500 pips - the same mistake as COPPER becoming
        COP and PER."""
        assert trade_notice.is_currency_pair("XAUUSD") is False
        assert trade_notice.is_currency_pair("EURUSD") is True
        assert trade_notice.is_currency_pair("XAGUSD") is False

    def test_an_index_keeps_its_own_units(self):
        assert "پیپ" not in notice(symbol=".US500Cash", fill=5000.0, stop=4950.0).body


class TestTheDirectionReadsInTheChannelsLanguage:
    @pytest.mark.parametrize("side", ["long", "buy"])
    def test_a_buy_is_a_buy(self, side):
        assert "خرید" in notice(side=side).body

    @pytest.mark.parametrize("side", ["short", "sell"])
    def test_a_sell_is_a_sell(self, side):
        assert "فروش" in notice(side=side).body

    def test_an_unknown_side_is_passed_through_rather_than_guessed(self):
        assert "sideways" in notice(side="sideways").body


class TestAFillIsNotAnEmergency:
    def test_it_is_sent_as_information(self):
        """Sending a working system at a higher urgency trains whoever reads
        this to ignore the urgencies that mean something."""
        assert notice().urgency is notify.Urgency.INFO

    def test_the_title_says_what_happened(self):
        assert "پوزیشن باز شد" in notice().title


class TestOptionalFactsAreOmittedNotInvented:
    def test_no_strategy_means_no_strategy_line(self):
        assert "مغز" not in notice(strategy=None).body

    def test_no_ticket_means_no_ticket_line(self):
        assert "تیکت" not in notice(ticket=None).body

    def test_no_risk_figure_means_no_risk_line(self):
        assert "ریسک" not in notice(risk_money=None).body


class TestTheChannelCannotBreakTheTrade:
    """The order is already at the broker by the time this runs. A telegram
    outage must not raise into a loop that would then forget a position the
    account genuinely holds."""

    def test_a_failing_send_is_reported_rather_than_raised(self, monkeypatch):
        from app.integrations import telegram

        def explode(*_args, **_kwargs):
            raise RuntimeError("token revoked")

        monkeypatch.setattr(telegram, "send", explode)

        result = trade_notice.announce(None, notice())

        assert result["sent"] is False
        assert "while announcing the fill" in result["reason"]

    def test_a_successful_send_says_so(self, monkeypatch):
        from app.integrations import telegram

        monkeypatch.setattr(
            telegram,
            "send",
            lambda *a, **k: telegram.Delivery(sent=True, reason=None),
        )

        assert trade_notice.announce(None, notice())["sent"] is True

    def test_nothing_is_deduplicated(self, monkeypatch):
        """Two fills on one symbol are two events even when every visible
        field matches, and collapsing them would hide the second position
        from the only place it was announced."""
        from app.integrations import telegram

        seen: list[dict] = []
        monkeypatch.setattr(
            telegram,
            "send",
            lambda message, **kw: seen.append(kw)
            or telegram.Delivery(sent=True, reason=None),
        )

        trade_notice.announce(None, notice())

        assert seen and "fingerprint" not in seen[0]
