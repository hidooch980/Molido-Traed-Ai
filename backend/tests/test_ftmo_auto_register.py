"""An FTMO account connected but not registered registers itself, strictly."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.brain import rulebooks
from app.services import challenge_accounts
from app.workers import autotrade

NOW = datetime(2026, 9, 23, 9, 0, tzinfo=UTC)
LOGIN = "1520012345"


def published(**over):
    base = {
        "login": LOGIN,
        "server": "FTMO-Demo2",
        "balance": 99_850.0,
        "equity": 99_850.0,
        "currency": "USD",
    }
    base.update(over)
    return base


def registrations(session):
    return challenge_accounts.listing(
        session, tenant_id=challenge_accounts.default_tenant(session)
    )


def test_an_unregistered_ftmo_account_is_registered_on_the_strictest_rules(session):
    ok, why = autotrade._register_ftmo(session, published(), NOW)

    assert (ok, why) == (True, "")
    [view] = registrations(session)
    assert LOGIN in view.account.label
    assert view.account.rulebook_key == rulebooks.FTMO_STRICTEST_KEY
    assert view.account.starting_balance == Decimal("100000.00")
    assert view.account.is_active


def test_the_registration_makes_it_a_prop_account(session):
    """The weekend lock and the prop caps read the registration."""
    autotrade._register_ftmo(session, published(), NOW)

    assert autotrade._is_prop_account(session, LOGIN)
    assert LOGIN in autotrade._prop_registered_logins(session)


def gate(session, equity):
    return autotrade._challenge_gate(
        session,
        published(balance=100_000.0, equity=equity, margin=0.0),
        0,
        0.01,
        today=date(2026, 9, 23),
        moment=NOW,
    )


def test_a_fresh_registered_account_may_trade(session):
    """Registered and still tradable: the rulebook is complete enough to
    size against, so a 1% order on a flat account is approved."""
    autotrade._register_ftmo(session, published(balance=100_000.0), NOW)

    allowed, why, room = gate(session, 100_000.0)

    assert allowed is True, why
    assert room is not None and room > 0


def test_the_registered_rules_now_gate_the_account(session):
    """Before, an unregistered FTMO login passed the gate with no limits.
    Below the 10% floor ($90,000 on $100,000) it is refused."""
    autotrade._register_ftmo(session, published(balance=100_000.0), NOW)

    allowed, why, _ = gate(session, 89_500.0)

    assert allowed is False
    assert "challenge rules" in why


def test_a_second_cycle_does_not_register_it_again(session):
    autotrade._register_ftmo(session, published(), NOW)
    autotrade._register_ftmo(session, published(), NOW)

    assert len(registrations(session)) == 1


def test_a_registration_switched_off_by_the_owner_is_respected(session):
    tenant = challenge_accounts.default_tenant(session)
    row = challenge_accounts.create(
        session,
        tenant_id=tenant,
        label=f"FTMO 2-step {LOGIN}",
        rulebook_key="ftmo-challenge-2step-phase1",
        starting_balance=Decimal("100000"),
    )
    challenge_accounts.set_active(session, tenant_id=tenant, account_id=row.id, active=False)

    autotrade._register_ftmo(session, published(), NOW)

    assert len(registrations(session)) == 1


def test_another_broker_is_left_alone(session):
    ok, _ = autotrade._register_ftmo(session, published(server="RoboForex-ECN"), NOW)

    assert ok is True
    assert registrations(session) == []


def test_a_registration_that_fails_refuses_rather_than_trading_unprotected(
    session, monkeypatch
):
    def broken(*_a, **_k):
        raise RuntimeError("database down")

    monkeypatch.setattr(challenge_accounts, "create", broken)

    ok, why = autotrade._register_ftmo(session, published(), NOW)

    assert ok is False
    assert "could not be registered" in why


@pytest.mark.parametrize(
    ("balance", "start"),
    [
        (100_000.0, 100_000.0),
        (99_120.0, 100_000.0),
        (201_500.0, 200_000.0),
        (10_050.0, 10_000.0),
        (80_000.0, 80_000.0),  # 20% from every size: taken as it is
    ],
)
def test_the_starting_balance_is_the_nearest_ftmo_size(balance, start):
    assert autotrade._ftmo_starting_balance(balance) == start


def test_the_strictest_rulebook_is_the_tighter_of_both_products():
    strict = rulebooks.get(rulebooks.FTMO_STRICTEST_KEY).rules
    one = rulebooks.get("ftmo-challenge-1step").rules
    two = rulebooks.get("ftmo-challenge-2step-phase1").rules

    assert strict.max_daily_drawdown_pct == min(
        one.max_daily_drawdown_pct, two.max_daily_drawdown_pct
    )
    assert strict.total_drawdown_trailing is True
    assert strict.min_trading_days == 4
    assert strict.max_single_day_profit_share == 0.50
