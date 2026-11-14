"""Stage 19: brain+agents shadow, backtest gate, Telegram alerts, nightly report."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.agents import memory
from app.agents.risk_gate import RiskContext
from app.core.enums import Timeframe
from app.services import (
    agent_backtest_gate,
    agent_brain_shadow,
    agent_notify,
    agent_ops,
    agent_report,
    ea_config,
)
from tests.test_agents_dashboard_api import client  # noqa: F401
from tests.test_agents_health import seed_bars


@dataclass
class _Dec:
    value: str


@dataclass
class _Prop:
    decision: _Dec
    conviction: float = 0.6


def _run(symbol="EURUSD", calls=("BUY", "BUY", "BUY")):
    return {"symbol": symbol, "timeframe": "H1", "status": "ran",
            "messages": [{"agent_id": f"SC0{i + 1}", "recommendation": c}
                         for i, c in enumerate(calls)]}


def test_combine_is_veto_only():
    assert agent_brain_shadow.combine("BUY", "SELL") == "WAIT"
    assert agent_brain_shadow.combine("BUY", "BUY") == "BUY"
    assert agent_brain_shadow.combine("WAIT", "BUY") == "WAIT"
    assert agent_brain_shadow.combine("SELL", "WAIT") == "SELL"


def test_shadow_records_and_evaluates_with_registry(session, instrument, provider):
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    seed_bars(session, instrument, provider, now, n=200, drift=0.0004)
    for k in range(70, 5, -1):
        at = now - timedelta(hours=k)
        agent_brain_shadow.record(session, _run(calls=("SELL", "SELL")), {},
                                  think=lambda *a: _Prop(_Dec("buy")), now=at)
    # a second call within the gap is skipped
    assert agent_brain_shadow.record(session, _run(), {}, think=lambda *a: _Prop(_Dec("buy")),
                                     now=now - timedelta(hours=6) + timedelta(minutes=5)) is None
    out = agent_brain_shadow.evaluate(session, now=now)
    assert out["production"]["n"] >= 60 and out["with_agents"]["n"] == 0
    assert out["status"] == "SHADOW" and out["live_effect"].startswith("none")
    st = agent_brain_shadow.status(session)
    assert st["latest_verdict"]["status"] == "SHADOW" and st["recent"][0]["with_agents"] == "WAIT"


def test_shadow_cycle_survives_brain_errors(session, instrument, provider):
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    seed_bars(session, instrument, provider, now)

    def boom(*a):
        raise RuntimeError("x")

    assert agent_brain_shadow.cycle(session, [_run()], {}, think=boom, now=now) == {
        "recorded": 0, "errors": 1}


def test_gate_verdicts():
    v = agent_backtest_gate.verdict
    assert v(10, 0.5) == "INSUFFICIENT" and v(40, 0.1) == "PASS"
    assert v(40, -0.2) == "FAIL" and v(40, -0.01) == "INSUFFICIENT"


def test_strategy_gate_runs_once_and_blocks_paper_on_fail(session, monkeypatch):
    calls = []

    def bt(session, sym, tf, folds, lookback):
        calls.append(sym)
        return {"bars": 1500, "overall": {"n": 20, "total_r": -6.0}, "folds": []}

    monkeypatch.setenv(agent_backtest_gate.FLAG, "1")
    r = agent_backtest_gate.run_strategy_gate(session, backtest=bt)
    assert r["verdict"] == "FAIL" and r["trades"] == 60 and len(calls) == 3
    agent_backtest_gate.run_strategy_gate(session, backtest=bt)
    assert len(calls) == 3
    allowed, why = agent_backtest_gate.paper_allowed(session)
    assert not allowed and "FAIL" in why
    monkeypatch.delenv(agent_backtest_gate.FLAG)
    assert agent_backtest_gate.paper_allowed(session)[0]


def test_ea_release_withheld_until_gate_passes(session, monkeypatch):
    monkeypatch.setenv(agent_backtest_gate.FLAG, "1")
    rel = {"ea_latest_version": "1.30", "ea_sha256": "a" * 64}
    monkeypatch.setattr(ea_config, "ea_release", lambda *a, **k: rel)
    assert ea_config.config(session)["ea_latest_version"] is None
    agent_backtest_gate.run_strategy_gate(session, backtest=lambda *a, **k: {
        "overall": {"n": 40, "total_r": 8.0}})
    assert agent_backtest_gate.run_ea_gate(session, rel)["verdict"] == "PASS"
    assert ea_config.config(session)["ea_latest_version"] == "1.30"


def test_notify_off_without_env_and_dedups(session, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    now = datetime.now(UTC)
    memory.remember(session, "RT10", "trade", "paper open", symbol="EURUSD", source_ref="t1",
                    content={"event": "open", "trade_id": "t1", "direction": "BUY"})
    ctx = RiskContext(equity=1000, daily_pnl_pct=-9.0, kill_switch=True, source="test")
    assert agent_notify.cycle(session, now=now, risk_ctx=ctx)["configured"] is False
    sent = []
    out = agent_notify.cycle(session, now=now, risk_ctx=ctx, send=lambda t: sent.append(t) or True)
    assert out["sent"] == 3 and any("Kill switch" in t for t in sent)
    assert agent_notify.cycle(session, now=now, risk_ctx=ctx, send=lambda t: True)["sent"] == 0
    assert agent_notify.telegram_send("x") is False


def test_nightly_report_once_per_day(session):
    late = datetime(2026, 11, 14, 20, 0, tzinfo=UTC)  # 23:30 Tehran
    early = datetime(2026, 11, 14, 10, 0, tzinfo=UTC)
    assert agent_report.maybe_run(session, now=early) is None
    sent = []
    r = agent_report.maybe_run(session, now=late, send=lambda t: sent.append(t) or True)
    assert r["date"] == "2026-11-14" and r["delivered"] and "nightly report" in sent[0]
    assert agent_report.maybe_run(session, now=late) is None
    assert agent_report.latest(session)[0]["date"] == "2026-11-14"


def test_ops_cycle_isolates_steps(session, monkeypatch):
    monkeypatch.setattr(agent_backtest_gate, "run_strategy_gate",
                        lambda s: (_ for _ in ()).throw(RuntimeError("x")))
    out = agent_ops.cycle(session)
    assert out["backtest_gate"].startswith("error") and "notify" in out


def test_ops_endpoints(client):  # noqa: F811
    assert client.get("/api/v1/agents/brain-shadow").status_code == 200
    body = client.get("/api/v1/agents/ops").json()
    assert set(body) == {"backtest_gate", "notify", "reports"}


def test_timeframe_enum_untouched():
    assert Timeframe.H1.value == "H1"
