"""Stage 8: the read-only endpoints the agent pages render."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from tests.conftest import insert_bar


@pytest.fixture()
def client(session):
    from app.db.session import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_rocket_scan_reads_stored_bars_and_only_proposes(client, session, instrument, provider):
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    rnd = random.Random(3)
    price = 1.10
    for i in range(300, 1, -1):
        t = now - timedelta(hours=i)
        nxt = price + rnd.gauss(0, 0.0005)
        insert_bar(session, instrument.id, provider.id, event_time=t, ingested_at=t + timedelta(
            hours=1), close=nxt, open_=price)
        price = nxt
    t = now - timedelta(hours=1)
    insert_bar(session, instrument.id, provider.id, event_time=t, ingested_at=now,
               close=price + 0.02, open_=price)

    body = client.get("/api/v1/agents/rocket/scan?timeframe=H1").json()
    assert body["mode"] == "shadow_only"
    (row,) = body["scanned"]
    assert row["symbol"] == "EURUSD" and row["status"] == "scanned" and row["bars"] >= 120
    for sig in body["signals"]:
        assert sig["status"] == "PROPOSED" and sig["risk_approval_status"] == "NOT_SUBMITTED"
    assert body["signals"], row


def test_rocket_scan_empty_state(client):
    body = client.get("/api/v1/agents/rocket/scan").json()
    assert body["signals"] == [] and body["scanned"] == []


def test_usage_totals_present_when_empty(client):
    body = client.get("/api/v1/agents/gateway/usage").json()
    assert body["requests"] == 0 and body["cost_usd"] is None and body["agents"] == []
