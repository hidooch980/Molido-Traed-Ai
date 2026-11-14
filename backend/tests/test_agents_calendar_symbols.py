"""Stage 12: RT06 calendar (free feed, default off, fail-safe) and dynamic symbols."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.enums import AssetClass
from app.models.instruments import Instrument
from app.services import agent_events, agent_symbols

NOW = datetime(2026, 11, 16, 13, 0, tzinfo=UTC)


def test_off_by_default_means_unknown(monkeypatch):
    monkeypatch.delenv(agent_events.FLAG, raising=False)
    assert agent_events.high_impact() is None


def test_feed_failure_is_unknown_not_quiet(monkeypatch):
    def broken(*a, **k):
        raise OSError("offline")

    monkeypatch.setattr(agent_events.calendar, "fetch", broken)
    assert agent_events.high_impact(force=True) is None


def test_feed_parsed_to_high_impact(monkeypatch):
    rel = [agent_events.calendar.Release(at=NOW, title="CPI", currency="usd", impact="High"),
           agent_events.calendar.Release(at=NOW, title="x", currency="EUR", impact="Low")]
    monkeypatch.setattr(agent_events.calendar, "fetch", lambda **k: "")
    monkeypatch.setattr(agent_events.calendar, "parse", lambda body: rel)
    monkeypatch.setattr(agent_events.calendar, "looks_shifted", lambda r: None)
    events = agent_events.high_impact(force=True)
    assert events == [{"time": NOW, "impact": "high", "currency": "USD", "title": "CPI"}]
    monkeypatch.setattr(agent_events.calendar, "looks_shifted", lambda r: "shifted")
    assert agent_events.high_impact(force=True) is None


def test_news_window():
    ev = [{"time": NOW, "impact": "high", "currency": "USD", "title": "NFP"}]
    assert agent_events.news_soon(ev, "XAUUSD", NOW - timedelta(minutes=45)) is True
    assert agent_events.news_soon(ev, "EURGBP", NOW) is False
    assert agent_events.news_soon(ev, "EURUSD", NOW + timedelta(hours=2)) is False
    assert agent_events.news_soon(None, "EURUSD", NOW) is None


def _inst(session, symbol, ac=AssetClass.FOREX):
    session.add(Instrument(symbol=symbol, name=symbol, asset_class=ac))
    session.flush()


def test_universe_follows_broker_specs(session):
    for s in ("EURUSD", "GBPUSD", "XAUUSD"):
        _inst(session, s, AssetClass.METAL if s == "XAUUSD" else AssetClass.FOREX)
    _inst(session, "SPX500", AssetClass.INDEX)
    none = agent_symbols.universe(session, broker=frozenset())
    assert none["symbols"] == ["EURUSD", "GBPUSD", "XAUUSD"] and "database" in none["source"]
    some = agent_symbols.universe(session, broker=frozenset({"EURUSD.", "XAUUSDm"}))
    assert some["symbols"] == ["EURUSD", "XAUUSD"] and some["excluded"] == ["GBPUSD"]


def test_endpoints(session):
    from fastapi.testclient import TestClient

    from app.db.session import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as c:
            assert c.get("/api/v1/agents/calendar").json()["events"] is None
            assert "source" in c.get("/api/v1/agents/symbols").json()
            assert "universe_source" in c.get("/api/v1/agents/rocket/scan").json()
    finally:
        app.dependency_overrides.clear()
