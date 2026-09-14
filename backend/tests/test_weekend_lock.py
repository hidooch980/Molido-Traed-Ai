"""The weekend lock for prop accounts."""

from __future__ import annotations

from datetime import UTC, datetime

from app.workers import autotrade, trailing


def test_the_lock_list_comes_from_the_setting(monkeypatch):
    monkeypatch.setenv("MOLIDO_WEEKEND_LOCK_LOGINS", "1514533027, 42")
    assert autotrade.weekend_lock_logins() == {"1514533027", "42"}
    monkeypatch.delenv("MOLIDO_WEEKEND_LOCK_LOGINS")
    assert autotrade.weekend_lock_logins() == set()


def test_friday_afternoon_is_weekend_ahead():
    assert autotrade._weekend_ahead(datetime(2026, 9, 18, 16, 0, tzinfo=UTC))
    assert not autotrade._weekend_ahead(datetime(2026, 9, 18, 15, 59, tzinfo=UTC))


def test_a_winner_below_the_trail_start_goes_to_entry():
    stop, why = trailing.proposed_stop(
        side="buy", entry=100.0, stop=99.0, price=100.4, risk=1.0, lock_at_r=0.3
    )
    assert stop == 100.0
    assert "weekend" in why


def test_a_trade_not_far_enough_ahead_is_left_alone():
    stop, _ = trailing.proposed_stop(
        side="buy", entry=100.0, stop=99.0, price=100.2, risk=1.0, lock_at_r=0.3
    )
    assert stop is None


def test_a_short_locks_to_entry_the_other_way():
    stop, _ = trailing.proposed_stop(
        side="sell", entry=100.0, stop=101.0, price=99.5, risk=1.0, lock_at_r=0.3
    )
    assert stop == 100.0


def test_a_stop_already_past_entry_is_not_pulled_back():
    stop, _ = trailing.proposed_stop(
        side="buy", entry=100.0, stop=100.2, price=100.5, risk=1.0, lock_at_r=0.3
    )
    assert stop is None


def test_without_the_lock_nothing_changes_below_the_trail_start():
    stop, _ = trailing.proposed_stop(side="buy", entry=100.0, stop=99.0, price=100.5, risk=1.0)
    assert stop is None
