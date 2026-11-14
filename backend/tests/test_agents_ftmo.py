"""Stage 13: FTMO monitor over recorded challenge accounts and live bridge data."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.services import agent_ftmo, challenge_accounts

NOW = datetime(2026, 11, 16, 12, tzinfo=UTC)


def live(equity, balance=100_000.0, daily=0.0, **kw):
    return {"available": True, "read_only": True, "equity": equity, "balance": balance,
            "daily_pnl_pct": daily, "open_symbols": [], "days_traded": 2, **kw}


def add(session, label="ftmo-1", key="ftmo-challenge-2step-phase1", confirmed=True):
    challenge_accounts.create(session, tenant_id=challenge_accounts.default_tenant(session),
                              label=label, rulebook_key=key,
                              starting_balance=Decimal("100000"), rules_confirmed=confirmed,
                              currency_per_r=Decimal("500"),
                              now=NOW)


def test_no_accounts_is_empty(session):
    out = agent_ftmo.monitor(session, now=NOW, snapshots={})
    assert out["accounts"] == [] and out["mode"] == "read_only"


def test_healthy_account_is_monitored(session):
    add(session)
    out = agent_ftmo.monitor(session, now=NOW, snapshots={"ftmo-1": live(101_000.0)})
    (row,) = out["accounts"]
    assert row["status"] == "monitored" and row["bridge_account_key"] == "ftmo-1"
    assert "verdict" in row["verdict"]


def test_breach_is_reported(session):
    add(session)
    ok = agent_ftmo.monitor(session, now=NOW, snapshots={"ftmo-1": live(101_000.0)})
    bad = agent_ftmo.monitor(session, now=NOW, snapshots={"ftmo-1": live(89_000.0,
                                                                         daily=-6.0)})
    assert bad["accounts"][0]["verdict"]["verdict"] != ok["accounts"][0]["verdict"]["verdict"]
    assert bad["accounts"][0]["verdict"]["verdict"] == "block"


def test_unknowns_are_not_zero(session):
    add(session)
    assert agent_ftmo.monitor(session, now=NOW, snapshots={"ftmo-1": live(
        100_000.0, daily=None)})["accounts"][0]["status"] == "unknown_daily"
    assert agent_ftmo.monitor(session, now=NOW, snapshots={"ftmo-1": {
        "available": False, "reason": "stale"}})["accounts"][0]["status"] == "no_live_data"
    add(session, label="other")
    rows = agent_ftmo.monitor(session, now=NOW, snapshots={"x": live(1.0), "y": live(1.0)})
    assert {r["status"] for r in rows["accounts"]} == {"not_linked"}


def test_single_pair_links_without_matching_label(session):
    add(session, label="my challenge")
    out = agent_ftmo.monitor(session, now=NOW, snapshots={"main": live(100_000.0)})
    assert out["accounts"][0]["bridge_account_key"] == "main"
