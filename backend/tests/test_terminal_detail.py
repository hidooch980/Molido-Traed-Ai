"""One terminal's own account, positions and decisions - not the fleet's.

The failure this route exists to prevent is attribution: a fleet-wide read
that hands one terminal's positions to whichever member of the fleet the
reader happened to be looking at. Every test below is about that.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app
from app.models.journal import ARM_CONTROL, ARM_RULE, JournalEntry

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


@pytest.fixture()
def client(session):
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def bridge_dir(tmp_path, key: str, *, login: str, positions: list[dict]):
    """A directory shaped like a terminal's Common\\Files."""
    directory = tmp_path / key
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "molido_account.json").write_text(
        json.dumps(
            {
                "published_at": NOW.strftime("%Y.%m.%d %H:%M:%S"),
                "login": int(login),
                "server": "MetaQuotes-Demo",
                "company": "MetaQuotes Ltd.",
                "currency": "USD",
                "balance": 1000.0,
                "equity": 1000.0,
                "margin": 0.0,
                "free_margin": 1000.0,
                "leverage": 100,
                "trade_allowed": True,
                "trade_mode": 0,
                "connected": True,
            }
        ),
        encoding="utf-8",
    )
    (directory / "molido_positions.json").write_text(
        json.dumps({"positions": positions}), encoding="utf-8"
    )
    (directory / "molido_heartbeat.json").write_text(
        json.dumps(
            {
                "published_at": NOW.strftime("%Y.%m.%d %H:%M:%S"),
                "connected": True,
                "trade_allowed": True,
                "refresh_seconds": 20,
            }
        ),
        encoding="utf-8",
    )
    return directory


def journal(session, *, traded_by=None, symbol="EURUSD", outcome=None, r=None, arm=ARM_RULE):
    """One decision, optionally carrying an order for one account.

    `traded_by` is a login. The fleet records a decision once and offers it to
    every account; the account-specific fact is the order under
    `during["orders"][login]`, which is where the cycle writes it. Filtering on
    `account_key` was wrong - it is NULL on all 21,804 live rows, because
    nothing populates it.
    """
    during = {"orders": {traded_by: {"state": "filled", "lots": 0.03}}} if traded_by else {}
    session.add(
        JournalEntry(
            symbol=symbol,
            decision="long",
            opened_at=NOW - timedelta(hours=2),
            closed_at=NOW - timedelta(hours=1) if outcome else None,
            outcome=outcome,
            r_multiple=r,
            arm=arm,
            price_source="broker",
            timeframe="H1",
            strategy="cross-sectional-stretch",
            before={},
            during=during,
            after={},
        )
    )
    session.commit()


@pytest.fixture()
def two_terminals(tmp_path, monkeypatch):
    from app.providers import metatrader

    dirs = {
        "term-b": bridge_dir(
            tmp_path,
            "term-b",
            login="111",
            positions=[
                {
                    "ticket": 1,
                    "symbol": "EURUSD",
                    "side": "sell",
                    "volume": 0.03,
                    "price_open": 1.15891,
                    "stop": 1.16151,
                    "target": 1.15501,
                    "profit": 0.63,
                }
            ],
        ),
        "term-c": bridge_dir(
            tmp_path,
            "term-c",
            login="222",
            positions=[
                {
                    "ticket": 2,
                    "symbol": "XAUUSD",
                    "side": "buy",
                    "volume": 0.5,
                    "price_open": 4387.8,
                    "stop": 4357.2,
                    "target": 4433.7,
                    "profit": -12.0,
                }
            ],
        ),
    }
    monkeypatch.setattr(metatrader, "bridge_dirs", lambda *a, **k: dirs)
    from app.api.v1 import brokers as brokers_module

    monkeypatch.setattr(brokers_module, "bridge_dirs", lambda *a, **k: dirs)
    return dirs


class TestItAnswersForOneTerminal:
    def test_the_positions_are_that_terminals_own(self, client, two_terminals):
        b = client.get("/api/v1/brokers/terminals/term-b").json()
        c = client.get("/api/v1/brokers/terminals/term-c").json()

        assert [p["symbol"] for p in b["positions"]] == ["EURUSD"]
        assert [p["symbol"] for p in c["positions"]] == ["XAUUSD"]

    def test_the_account_is_that_terminals_own(self, client, two_terminals):
        b = client.get("/api/v1/brokers/terminals/term-b").json()

        assert str(b["account"]["login"]) == "111"
        assert b["terminal"] == "term-b"

    def test_an_unknown_terminal_is_named_rather_than_returning_the_default(
        self, client, two_terminals
    ):
        """Falling back to the first bridge would answer a question nobody
        asked, with somebody else's account."""
        response = client.get("/api/v1/brokers/terminals/term-z")

        assert response.status_code >= 400
        assert "term-z" in response.text


class TestTheDecisionsAreFilteredByAccount:
    def test_only_the_trades_this_account_sent_appear(self, client, session, two_terminals):
        journal(session, traded_by="111", symbol="EURUSD", outcome="win", r=1.5)
        journal(session, traded_by="222", symbol="XAUUSD", outcome="loss", r=-1.0)

        b = client.get("/api/v1/brokers/terminals/term-b").json()

        assert [d["symbol"] for d in b["decisions"]] == ["EURUSD"]

    def test_a_decision_nobody_traded_is_not_this_accounts_history(self, client, session, two_terminals):
        """The fleet is offered thousands of decisions a day and each account
        sends orders for a handful. Listing the offers as an account's trades
        would put a month of the fleet's thinking under one login."""
        journal(session, traded_by=None, symbol="GBPUSD", outcome="win", r=2.0)

        b = client.get("/api/v1/brokers/terminals/term-b").json()

        assert b["decisions"] == []

    def test_the_brokers_answer_for_this_order_is_carried(self, client, session, two_terminals):
        journal(session, traded_by="111", symbol="EURUSD", outcome="win", r=1.5)

        [row] = client.get("/api/v1/brokers/terminals/term-b").json()["decisions"]

        assert row["order_state"] == "filled"
        assert row["lots"] == 0.03

    def test_the_control_arm_is_not_shown_as_a_trade(self, client, session, two_terminals):
        """The control never reached a broker. Listing it under an account's
        trades would put a number beside a position that never existed."""
        journal(session, traded_by="111", symbol="EURUSD", outcome="win", r=1.5)
        journal(
            session, traded_by="111", symbol="EURUSD", outcome="loss", r=-1.0, arm=ARM_CONTROL
        )

        b = client.get("/api/v1/brokers/terminals/term-b").json()

        assert b["summary"]["decisions"] == 1
        assert b["summary"]["total_r"] == 1.5

    def test_the_summary_counts_only_what_resolved(self, client, session, two_terminals):
        journal(session, traded_by="111", symbol="EURUSD", outcome="win", r=2.0)
        journal(session, traded_by="111", symbol="GBPUSD", outcome=None, r=None)

        summary = client.get("/api/v1/brokers/terminals/term-b").json()["summary"]

        assert summary["decisions"] == 2
        assert summary["resolved"] == 1
        assert summary["open"] == 1
        assert summary["hit_rate"] == 1.0
        assert summary["average_r"] == 2.0

    def test_no_history_is_an_empty_list_rather_than_an_error(self, client, two_terminals):
        payload = client.get("/api/v1/brokers/terminals/term-b").json()

        assert payload["decisions"] == []
        assert payload["summary"]["hit_rate"] is None
        assert payload["summary"]["average_r"] is None
