"""Stage 16: agent health, forward performance, explain, alerts (read-only)."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from app.agents import memory
from app.agents.analyzers.runner import ANALYZERS
from app.agents.risk_gate import RiskContext
from app.core.enums import Timeframe
from app.services import agent_health, agent_run
from tests.conftest import insert_bar
from tests.test_agents_dashboard_api import client  # noqa: F401


def seed_bars(session, instrument, provider, now, n=150, drift=0.0):
    rnd, price = random.Random(3), 1.10
    for i in range(n, 0, -1):
        t = now - timedelta(hours=i)
        nxt = price + drift + rnd.gauss(0, 0.0005)
        insert_bar(session, instrument.id, provider.id, event_time=t,
                   ingested_at=t + timedelta(hours=1), close=nxt, open_=price)
        price = nxt


def record_run(session, agents, *, symbol="EURUSD", as_of=None, tf="H1"):
    as_of = as_of or datetime.now(UTC)
    memory.remember(session, "BRAIN-01", "agent", "run", symbol=symbol,
                    content={"event": "run", "timeframe": tf, "as_of": as_of.isoformat(),
                             "agents": agents})


def test_health_lists_all_51_and_flags_errors(session):
    ok = {"ok": True, "error": None, "ms": 2.0, "recommendation": "WAIT"}
    for i in range(5):
        agents = {a: dict(ok) for a in ANALYZERS}
        if i < 3:
            agents["TA02"] = {"ok": False, "error": "RuntimeError: x", "ms": 1.0,
                              "recommendation": "WAIT"}
        record_run(session, agents)
    rep = agent_health.health(session)
    assert len(rep["agents"]) == 51
    by = {a["id"]: a for a in rep["agents"]}
    assert by["TA02"]["status"] == "degraded" and by["TA02"]["error_rate"] == 0.6
    assert by["SC01"]["status"] == "ok" and by["SC01"]["runs"] == 5
    assert by["RK01"]["status"] == "ok" and by["RK01"]["runs"] == 5


def test_never_run_and_stale(session):
    assert all(a["status"] == "never_run" for a in agent_health.health(session)["agents"])
    record_run(session, {"SC01": {"ok": True, "ms": 1.0, "recommendation": "WAIT"}})
    later = datetime.now(UTC) + timedelta(days=2)
    by = {a["id"]: a for a in agent_health.health(session, now=later)["agents"]}
    assert by["SC01"]["status"] == "stale"


def test_performance_scores_direction_after_the_horizon(session, instrument, provider):
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    seed_bars(session, instrument, provider, now, drift=0.001)
    as_of = now - timedelta(hours=20)
    record_run(session, {"SC03": {"ok": True, "recommendation": "BUY"},
                         "SC04": {"ok": True, "recommendation": "SELL"},
                         "SC05": {"ok": True, "recommendation": "WAIT"}}, as_of=as_of)
    record_run(session, {"SC03": {"ok": True, "recommendation": "BUY"}}, as_of=now)
    rep = {r["id"]: r for r in agent_health.performance(session, now=now)["agents"]}
    assert rep["SC03"]["hit_rate"] == 1.0 and rep["SC03"]["pending"] == 1
    assert rep["SC04"]["hit_rate"] == 0.0 and "SC05" not in rep
    assert rep["SC03"]["enough_data"] is False


def test_explain_traces_a_real_run(session, instrument, provider):
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    seed_bars(session, instrument, provider, now)
    run = agent_run.run_symbol(session, "EURUSD", Timeframe.H1, as_of=now)
    ex = agent_health.explain(run)
    assert len(ex["trace"]) == len(ANALYZERS)
    assert "NO ORDER" in ex["decision"] and "spread" in ex["missing_inputs"]
    assert sum(ex["votes"].values()) == len(ANALYZERS)
    assert agent_health.explain({"status": "unknown_symbol"})["trace"] == []


def test_alerts_from_risk_and_challenge(session):
    ctx = RiskContext(equity=10_000, daily_pnl_pct=-2.5, open_symbols=(), data_fresh=False,
                      kill_switch=True, source="test")
    ftmo = {"accounts": [{"account": {"label": "A"}, "status": "monitored",
                          "verdict": {"verdict": "block"}},
                         {"account": {"label": "B"}, "status": "not_linked"}]}
    rep = agent_health.alerts(session, risk_ctx=ctx, ftmo=ftmo)
    levels = [a["level"] for a in rep["alerts"]]
    assert levels == sorted(levels, key=["critical", "warning", "info"].index)
    text = " ".join(a["message"] for a in rep["alerts"])
    assert "kill switch" in text and "stale" in text and "past half" in text
    assert "A: challenge rules say block" in text and "B: not_linked" in text
    assert "nothing is sent" in rep["delivery"]


def test_unknown_account_alerts(session):
    rep = agent_health.alerts(session, risk_ctx=RiskContext(source="bridge unavailable"))
    assert any("all signals BLOCK" in a["message"] for a in rep["alerts"])


def test_run_cycle_records_and_feeds_health(session, instrument, provider):
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    seed_bars(session, instrument, provider, now)
    res = agent_run.run_cycle(session, symbols=["EURUSD", "NOPE"])
    assert res["ran"] == 1 and res["skipped"] == ["NOPE"]
    by = {a["id"]: a for a in agent_health.health(session)["agents"]}
    assert by["SC01"]["runs"] == 1


def test_run_flag_off_by_default(monkeypatch, capsys):
    monkeypatch.delenv(agent_run.RUN_FLAG, raising=False)
    assert agent_run.main() == 0 and "off" in capsys.readouterr().out


def test_symbol_view_collects_everything(session, instrument, provider):
    from app.services import agent_symbol_view
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    seed_bars(session, instrument, provider, now)
    v = agent_symbol_view.view(session, "eurusd", Timeframe.H1, now=now)
    assert v["status"] == "ran" and v["mode"] == "shadow_only"
    assert len(v["explain"]["trace"]) == len(ANALYZERS)
    assert v["ensemble"]["decision"] in ("BUY", "SELL", "WAIT")
    assert v["calendar"] is None and "signals" in v["rocket"]
    assert agent_symbol_view.view(session, "NOPE", now=now)["status"] == "unknown_symbol"


def test_symbol_endpoint(client):  # noqa: F811
    r = client.get("/api/v1/agents/symbol/EURUSD")
    assert r.status_code == 200 and r.json()["status"] in ("unknown_symbol", "ran")
