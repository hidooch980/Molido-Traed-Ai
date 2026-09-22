"""The prop guard: a challenge is lost on the whole book, not on one order.

14 Sep 2026, FTMO phase 2 at $200,000: seven orders that each passed the gate
held $11,077 behind their stops against a $6,000 daily limit, and the daily
floor was anchored to live equity so it could never be reached.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.brain import rulebooks
from app.models.equity import EquitySample
from app.services import equity as equity_series
from app.workers import autotrade

RULES = rulebooks.get("ftmo-challenge-2step-phase2").rules  # 5% daily, 5% target, 4 days
NOW = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
LOGIN = "1514533027"
SPECS = {"EURUSD": {"tick_size": 0.00001, "tick_value": 1.0}}


def account(**over):
    base = dict(starting_balance=200_000.0, currency_per_r=1_500.0, created_at=None)
    base.update(over)
    return SimpleNamespace(**base)


def position(risk_usd: float, *, stop=True):
    # 0.01 price distance on EURUSD = 1,000 ticks; volume sets the dollars.
    return {
        "symbol": "EURUSD",
        "price_open": 1.10,
        "stop": 1.09 if stop else 0.0,
        "volume": risk_usd / 1_000.0,
    }


def guard(session, positions, *, equity=200_000.0, acct=None, headroom=2.0):
    return autotrade._prop_guard(
        session,
        RULES,
        acct or account(),
        {"login": LOGIN, "equity": equity},
        positions,
        SPECS,
        headroom,
        NOW,
    )


def sample(session, at, *, balance=200_000.0, open_positions=1):
    session.add(
        EquitySample(
            id=uuid.uuid4(),
            account_key=LOGIN,
            recorded_at=at,
            equity=balance,
            balance=balance,
            margin=0.0,
            open_positions=open_positions,
            currency="USD",
        )
    )
    session.flush()


BOUNDARY = datetime(2026, 9, 13, 22, 0, tzinfo=UTC)  # 00:00 CE(S)T on the 14th


def test_open_stops_above_seventy_percent_of_the_daily_allowance_refuse(session):
    allowed, why, _ = guard(session, [position(5_000), position(3_000)])  # 8,000 > 7,000
    assert allowed is False
    assert "open stops risk" in why


def test_a_position_without_a_stop_refuses(session):
    allowed, why, _ = guard(session, [position(100, stop=False)])
    assert allowed is False
    assert "no stop" in why


def test_room_shrinks_by_what_is_already_open(session):
    allowed, _, room = guard(session, [position(2_700)], headroom=5.0)
    assert allowed is True
    # A quarter of the room left before the daily floor, open stops counted:
    # 0.25 * (200,000 - 2,700 - 190,000) = 1,825, at 1,500 per R.
    assert room == pytest.approx(1_825 / 1_500)


def test_the_day_stops_after_half_the_allowance_is_lost(session):
    sample(session, BOUNDARY + timedelta(minutes=1))
    allowed, why, _ = guard(session, [], equity=194_900.0)  # down 5,100 >= 5,000
    assert allowed is False
    assert "today" in why


def test_the_target_locks_once_the_days_are_met(session):
    for day in range(4):
        sample(session, BOUNDARY - timedelta(days=day) + timedelta(hours=3))
    since = BOUNDARY - timedelta(days=10)
    allowed, why, _ = guard(session, [], equity=210_500.0, acct=account(created_at=since))
    assert allowed is False
    assert "target is reached" in why


def test_the_target_does_not_lock_before_the_minimum_days(session):
    sample(session, BOUNDARY + timedelta(hours=3))
    since = BOUNDARY - timedelta(days=10)
    allowed, _, _ = guard(session, [], equity=210_500.0, acct=account(created_at=since))
    assert allowed is True


def test_the_day_open_is_none_when_nobody_watched_the_boundary(session):
    sample(session, BOUNDARY + timedelta(hours=5))
    assert equity_series.day_open_balance(session, LOGIN, at=NOW) is None


def test_the_day_open_is_the_first_sample_at_the_boundary(session):
    sample(session, BOUNDARY + timedelta(minutes=2), balance=199_000.0)
    sample(session, BOUNDARY + timedelta(hours=2), balance=205_000.0)
    assert equity_series.day_open_balance(session, LOGIN, at=NOW) == 199_000.0


class TestRiskBudget:
    """Size from where the challenge stands, not a fixed percentage."""

    def budget(self, **over):
        base = dict(start=200_000.0, equity=200_000.0, day_open=200_000.0, allowance=6_000.0, open_risk=0.0)
        base.update(over)
        return autotrade._risk_budget(RULES, **base)

    def test_a_fresh_day_takes_a_quarter_of_the_daily_room(self):
        assert self.budget() == pytest.approx(1_500.0)

    def test_open_stops_shrink_the_next_trade(self):
        assert self.budget(open_risk=2_000.0) == pytest.approx(1_000.0)

    def test_a_losing_day_shrinks_the_next_trade(self):
        assert self.budget(equity=197_000.0) == pytest.approx(750.0)

    def test_near_the_target_it_risks_only_half_of_what_is_missing(self):
        # 1,000 short of 210,000: half of it at a 1.5 R target is 333.
        assert self.budget(equity=209_000.0, day_open=209_000.0) == pytest.approx(1_000 * 0.5 / 1.5)

    def test_near_the_total_floor_the_total_room_governs(self):
        # 181,000 against a 180,000 floor: an eighth of 1,000.
        assert self.budget(equity=181_000.0, day_open=181_000.0) == pytest.approx(125.0)


def test_a_sample_fifteen_minutes_after_the_boundary_is_still_the_day_open(session):
    sample(session, BOUNDARY + timedelta(minutes=15), balance=198_500.0)
    assert equity_series.day_open_balance(session, LOGIN, at=NOW) == 198_500.0
