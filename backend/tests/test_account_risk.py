"""Risk per account, because the smallest trade a broker takes is a fixed size.

0.01 lots of EURUSD behind a 26-pip stop risks $2.60 whatever the account
holds. A $50 account at 0.75% may risk 38 cents, so every order it computes
rounds to zero and it trades nothing - not because a rule refused it but
because arithmetic did. A single global figure cannot fix that without
putting $10,000 behind every trade on the $196,000 account in the same fleet.

So the override is per account, and every test here is about it not leaking.
"""

from __future__ import annotations

import pytest

from app.workers import autotrade


@pytest.fixture()
def table(monkeypatch):
    def _set(value: str):
        from app.core.config import get_settings

        monkeypatch.setattr(get_settings(), "account_risk_percent", value, raising=False)
        monkeypatch.setattr(get_settings(), "autotrade_risk_percent", 0.75, raising=False)

    return _set


class TestItOnlyTouchesTheAccountsItNames:
    def test_a_named_account_gets_its_own_figure(self, table):
        table("10012494599=3.0")

        assert autotrade._risk_percent("10012494599") == 3.0

    def test_every_other_account_keeps_the_fleet_figure(self, table):
        table("10012494599=3.0")

        assert autotrade._risk_percent("10012494823") == 0.75
        assert autotrade._risk_percent("5055372785") == 0.75

    def test_no_login_at_all_is_the_fleet_figure(self, table):
        """The reports and the daily-limit arithmetic call it without one."""
        table("10012494599=3.0")

        assert autotrade._risk_percent() == 0.75
        assert autotrade._risk_percent(None) == 0.75

    def test_several_accounts_can_be_named(self, table):
        table("10012494599=3.0,5055372630=2.0")

        assert autotrade._risk_percent("10012494599") == 3.0
        assert autotrade._risk_percent("5055372630") == 2.0


class TestATypoCostsLessThanIntendedAndNeverMore:
    def test_an_absurd_figure_is_capped(self, table):
        """`5` and `50` are one keystroke apart, and one of them is half the
        account behind a single stop."""
        table("10012494599=50")

        assert autotrade._risk_percent("10012494599") == autotrade.MAX_ACCOUNT_RISK_PERCENT

    def test_a_value_that_is_not_a_number_falls_back_rather_than_raising(self, table):
        """An environment variable with a stray character must not stop a
        fleet from trading."""
        table("10012494599=three")

        assert autotrade._risk_percent("10012494599") == 0.75

    def test_a_malformed_entry_does_not_take_the_others_with_it(self, table):
        table("10012494599=oops,5055372630=2.0")

        assert autotrade._risk_percent("10012494599") == 0.75
        assert autotrade._risk_percent("5055372630") == 2.0

    def test_zero_and_negative_are_ignored_rather_than_disabling_an_account(self, table):
        """A zero would make R undefined and refuse the cycle by a different
        route; that is a halt, and a halt belongs in the kill switch."""
        table("10012494599=0,5055372630=-1")

        assert autotrade._risk_percent("10012494599") == 0.75
        assert autotrade._risk_percent("5055372630") == 0.75

    def test_an_empty_table_changes_nothing(self, table):
        table("")

        assert autotrade._risk_percent("10012494599") == 0.75


class TestTheArithmeticItExistsFor:
    def test_the_fifty_dollar_account_can_reach_the_minimum_lot(self, table):
        """$2.60 is what one minimum lot of EURUSD risks behind a 26-pip
        stop. At 0.75% a $50 account may risk 38 cents; at 5% it may risk
        $2.50, which still does not reach EURUSD - and does reach USDCNH at
        24 cents, which is the point. The cap is not a promise that every
        symbol becomes tradeable."""
        table("10012494599=5.0")
        equity = 50.0

        allowed = equity * autotrade._risk_percent("10012494599") / 100.0

        assert allowed == pytest.approx(2.50)
        assert allowed < 2.60  # EURUSD still out of reach
        assert allowed > 0.24  # USDCNH within it

    def test_the_big_account_is_untouched_by_that_change(self, table):
        table("10012494599=5.0")

        assert autotrade._risk_percent("10012494823") == 0.75
        assert 196_559 * 0.75 / 100 == pytest.approx(1474.19, abs=0.01)
