"""Stage 10: read-only account context from the MT5 bridge and the paper path."""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta

from app.agents import paper
from app.agents.analyzers.bars import Candle
from app.agents.risk_gate import RiskContext
from app.providers.metatrader import MetaTraderBridge
from app.services import agent_account, agent_paper
from tests.conftest import insert_bar
from tests.test_metatrader_bridge import STAMP, write_account, write_heartbeat

NOW = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


def bridge(tmp_path, deals=None, positions=None, **acct):
    logs = tmp_path / "logs"
    logs.mkdir(exist_ok=True)
    write_heartbeat(tmp_path)
    write_account(tmp_path, **acct)
    (tmp_path / "molido_positions.json").write_text(json.dumps(
        {"published_at": STAMP, "positions": positions or []}), encoding="utf-8")
    (tmp_path / "molido_deals.json").write_text(json.dumps(
        {"published_at": STAMP, "deals": deals or []}), encoding="utf-8")
    return MetaTraderBridge(tmp_path, log_directory=logs)


def test_context_from_bridge(tmp_path):
    b = bridge(tmp_path, equity=9_900.0, positions=[{"symbol": "xauusd"}],
               deals=[{"closed_at": "2026.08.14 09:00:00", "net": -100.0},
                      {"closed_at": "2026.08.13 09:00:00", "net": 500.0}])
    snap = agent_account.snapshot(provider=b, now=NOW)
    assert snap["read_only"] and snap["open_symbols"] == ["XAUUSD"]
    assert snap["daily_pnl_pct"] == -2.0
    ctx = agent_account.risk_context(provider=b, now=NOW)
    assert ctx.equity == 9_900.0 and ctx.data_fresh and "read-only" in ctx.source


def test_unreadable_deal_time_makes_daily_pnl_unknown(tmp_path):
    b = bridge(tmp_path, deals=[{"closed_at": "yesterday-ish", "net": -1.0}])
    assert agent_account.risk_context(provider=b, now=NOW).daily_pnl_pct is None


def test_missing_bridge_is_not_usable(tmp_path):
    ctx = agent_account.risk_context(provider=MetaTraderBridge(tmp_path / "none"), now=NOW)
    assert ctx.equity is None and "unavailable" in ctx.source


def test_adapter_never_writes(tmp_path):
    b = bridge(tmp_path)
    before = sorted(p.name for p in tmp_path.iterdir())
    agent_account.snapshot(provider=b, now=NOW)
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_paper_open_only_on_approve_or_reduce():
    sig = {"symbol": "EURUSD", "direction": "BUY", "timeframe": "H1",
           "signal_timestamp": "2026-08-14T11:00:00+00:00", "entry_zone": [1.1, 1.1],
           "stop_loss": 1.09, "take_profit": 1.13, "rocket_rank": "R4"}
    assert paper.open_trade(sig, {"verdict": "BLOCK"}) is None
    t = paper.open_trade(sig, {"verdict": "REDUCE", "risk_pct": 0.25})
    assert t is not None and t.mode == "paper" and t.risk_pct == 0.25
    assert t.trade_id == paper.open_trade(sig, {"verdict": "APPROVE"}).trade_id


def test_paper_resolution_is_conservative():
    t = {"entry": 1.0, "stop_loss": 0.99, "take_profit": 1.02, "direction": "BUY"}
    both = [Candle(NOW, 1.0, 1.03, 0.98, 1.0)]
    assert paper.resolve(t, both)["result"] == "stop"
    assert paper.resolve(t, [Candle(NOW, 1.0, 1.021, 0.995, 1.02)])["r"] == 2.0
    assert paper.resolve(t, [Candle(NOW, 1.0, 1.005, 0.995, 1.005)])["result"] == "open"


def test_cycle_records_paper_trades_and_resolves(session, instrument, provider, monkeypatch):
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    rnd, price = random.Random(3), 1.10
    for i in range(300, 1, -1):
        t = now - timedelta(hours=i)
        nxt = price + rnd.gauss(0, 0.0005)
        insert_bar(session, instrument.id, provider.id, event_time=t,
                   ingested_at=t + timedelta(hours=1), close=nxt, open_=price)
        price = nxt
    t = now - timedelta(hours=1)
    insert_bar(session, instrument.id, provider.id, event_time=t, ingested_at=now,
               close=price + 0.006, open_=price)
    ctx = RiskContext(equity=10_000, daily_pnl_pct=0.0, open_symbols=(), data_fresh=True,
                      source="test")
    first = agent_paper.run_cycle(session, risk_ctx=ctx, now=now)
    assert first["signals"] >= 1 and first["opened"] == 1
    again = agent_paper.run_cycle(session, risk_ctx=ctx, now=now)
    assert again["opened"] == 0  # idempotent: same signal is not reopened
    book = agent_paper.book(session)
    assert book["mode"] == "paper" and book["open"] == first["opened"]
    if first["opened"]:
        trade = book["trades"][0]
        insert_bar(session, instrument.id, provider.id, event_time=now, ingested_at=now +
                   timedelta(hours=1), close=trade["take_profit"] + 0.01, open_=price + 0.006)
        later = agent_paper.run_cycle(session, risk_ctx=ctx, now=now + timedelta(hours=1))
        assert later["closed"] == 1
        assert agent_paper.book(session)["closed"] == 1


def test_cycle_blocks_without_account(session):
    out = agent_paper.run_cycle(session, risk_ctx=RiskContext(source="none"))
    assert out["opened"] == 0


def test_flag_is_off_by_default(monkeypatch, capsys):
    monkeypatch.delenv(agent_paper.FLAG, raising=False)
    assert agent_paper.main() == 0 and "off" in capsys.readouterr().out
