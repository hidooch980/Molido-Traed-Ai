"""WTI was refused eleven times a cycle for not being a currency pair.

The news gate splits a symbol into two currencies and matches the calendar
against them. An instrument priced in one currency - WTI, UKOIL, INTC, the
indices - split into nothing, and the gate refused it outright with "its news
exposure cannot be checked". That was eleven of the forty-nine candidates
term-c and term-d were offered in one cycle, on instruments they could
actually afford, and both accounts have never sent an order in their lives.

Refusing is not the conservative reading it looks like. It claims the
exposure is unknown, when these are priced in the account's own currency and
their exposure to that currency's releases is the plainest fact about them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.workers.autotrade import _news_gate, _quoted_in_account_currency

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)

# WTI as term-f publishes it: tick_value/tick_size == contract_size == 1.0.
WTI = {"tick_value": 0.01, "tick_size": 0.01, "contract_size": 1.0}
# Gold, whose published tick value is ten times too small - the defect that
# cost $3,730. The identity does not hold, so nothing is claimed.
XAUUSD_BROKEN = {"tick_value": 0.1, "tick_size": 0.01, "contract_size": 100.0}

# "High" with the capital, and inside the five-minute window - both read off
# NEWS_IMPACTS and NEWS_WINDOW_MINUTES rather than assumed. A test that gets
# either wrong reports a gate held open when the gate is working.
HIGH_IMPACT_USD = [
    {
        "currency": "USD",
        "impact": "High",
        "title": "Nonfarm payrolls",
        "at": (NOW + timedelta(minutes=3)).isoformat(),
    }
]
QUIET = []


class TestTheIdentity:
    def test_an_instrument_that_agrees_is_quoted_in_the_account_currency(self):
        assert _quoted_in_account_currency(WTI, "USD") == "USD"

    def test_a_specification_that_disagrees_claims_nothing(self):
        """The gold defect made these two numbers disagree by ten times. A
        guess here would be a guess built on a number already known wrong."""
        assert _quoted_in_account_currency(XAUUSD_BROKEN, "USD") is None

    def test_no_account_currency_means_no_claim(self):
        assert _quoted_in_account_currency(WTI, None) is None

    def test_a_specification_missing_its_numbers_claims_nothing(self):
        assert _quoted_in_account_currency({"tick_value": 0.01}, "USD") is None


class TestTheGate:
    def test_wti_is_now_checked_rather_than_refused(self):
        clear, reason = _news_gate("WTI", NOW, QUIET, quoted_in="USD")

        assert clear
        assert "cannot be checked" not in (reason or "")

    def test_and_it_is_actually_held_when_a_release_is_imminent(self):
        """The point is a check where there was none - not a gate held open."""
        clear, reason = _news_gate("WTI", NOW, HIGH_IMPACT_USD, quoted_in="USD")

        assert not clear
        assert "USD" in (reason or "")

    def test_without_a_derived_currency_the_old_refusal_stands(self):
        """There is genuinely nothing to match on, and unknown is not safe."""
        clear, reason = _news_gate("WTI", NOW, QUIET, quoted_in=None)

        assert not clear
        assert "cannot be split into currencies" in (reason or "")

    def test_a_pair_is_unaffected_by_any_of_this(self):
        clear, _ = _news_gate("EURUSD", NOW, QUIET, quoted_in="USD")
        held, reason = _news_gate("EURUSD", NOW, HIGH_IMPACT_USD, quoted_in="USD")

        assert clear
        assert not held
        assert "USD" in (reason or "")

    def test_a_calendar_that_could_not_be_read_still_refuses_everything(self):
        """A feed failing is not a quiet week, and that must not change for
        the instruments this fix is about."""
        clear, reason = _news_gate("WTI", NOW, None, quoted_in="USD")

        assert not clear
        assert "could not be read" in (reason or "")
