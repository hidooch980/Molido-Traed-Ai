"""The book-wide open-risk cap, the R-to-equity conversion, and silenced votes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.learning import brain_selection
from app.models.journal import ARM_RULE, JournalEntry
from app.workers import autotrade

SPECS = {"EURUSD": {"tick_size": 0.00001, "tick_value": 1.0}}
NOW = datetime(2026, 9, 14, 20, 0, tzinfo=UTC)


def position(risk_usd: float, *, stop=True):
    return {"symbol": "EURUSD", "price_open": 1.10, "stop": 1.09 if stop else 0.0, "volume": risk_usd / 1_000.0}


class TestOpenRiskCap:
    def test_room_is_what_is_left_under_six_percent(self):
        ok, _, room = autotrade._open_risk_room([position(2_000)], SPECS, 100_000.0)
        assert ok is True
        assert room == pytest.approx(0.04)

    def test_a_book_at_the_cap_refuses(self):
        ok, why, room = autotrade._open_risk_room([position(6_000)], SPECS, 100_000.0)
        assert ok is False and room == 0.0
        assert "6% cap" in why

    def test_an_unpriced_position_refuses(self):
        ok, why, _ = autotrade._open_risk_room([position(100, stop=False)], SPECS, 100_000.0)
        assert ok is False
        assert "cannot be priced" in why


class TestRAsEquityFraction:
    def test_r_is_converted_through_currency_per_r(self):
        account = SimpleNamespace(currency_per_r=1_500.0)
        assert autotrade._r_as_equity_fraction(0.55, account, 200_000.0) == pytest.approx(0.004125)

    def test_none_stays_none(self):
        assert autotrade._r_as_equity_fraction(None, SimpleNamespace(currency_per_r=1_500.0), 200_000.0) is None


def _vote(session, strategy, *, minutes_ago=5):
    session.add(
        JournalEntry(
            symbol="EURUSD",
            decision="long",
            opened_at=NOW - timedelta(minutes=minutes_ago),
            arm=ARM_RULE,
            strategy=strategy,
            timeframe="H1",
            during={},
        )
    )
    session.flush()


def test_a_losing_brain_loses_its_vote_but_keeps_recording(session, monkeypatch):
    autotrade._SILENCED_CACHE.clear()
    standings = [
        brain_selection.Standing("loser", 20, -0.4, 0.0),
        brain_selection.Standing("thin-loser", 5, -0.9, 0.0),
        brain_selection.Standing("winner", 20, 0.6, 0.0),
    ]
    monkeypatch.setattr(brain_selection, "standings", lambda session: standings)
    for name in ("loser", "thin-loser", "winner"):
        _vote(session, name)

    votes = autotrade._fresh_votes(session, NOW)

    assert votes[("EURUSD", "long")] == {"thin-loser", "winner"}
    autotrade._SILENCED_CACHE.clear()
