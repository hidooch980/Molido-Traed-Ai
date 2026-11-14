"""Everything the agent layer knows about one symbol, for the symbol page (read-only)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import memory, selfheal
from app.core.enums import Timeframe
from app.models.instruments import Instrument
from app.services import (
    agent_account,
    agent_events,
    agent_health,
    agent_learning,
    agent_paper,
    agent_run,
    agent_scan,
)


def view(session: Session, symbol: str, timeframe: Timeframe = Timeframe.H1, *,
         bridge: Any = None, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    symbol = symbol.upper()
    inst = session.scalars(select(Instrument).where(Instrument.symbol == symbol)).first()
    if inst is None:
        return {"symbol": symbol, "status": "unknown_symbol"}
    events = agent_events.high_impact()
    run = agent_run.run_symbol(session, symbol, timeframe, as_of=now, bridge=bridge,
                               events=events)
    explained = agent_health.explain(run)
    weights = agent_learning.current(session)
    calls = {m["agent_id"]: m["recommendation"] for m in run.get("messages", [])
             if m["recommendation"] in ("BUY", "SELL") and m["agent_id"] != "BRAIN-01"}
    risk_ctx = agent_account.risk_context(session=session, now=now)
    scan = agent_scan.scan(session, timeframe, risk_ctx=risk_ctx, as_of=now, symbols=[symbol],
                           events=events)
    paper = [t for t in agent_paper.book(session, limit=5000)["trades"]
             if t.get("symbol") == symbol][:50]
    last_run = next((r for r in memory.recall(session, kind="agent", symbol=symbol, limit=5)
                     if (r.content or {}).get("event") == "run"), None)
    ccys = agent_events.currencies(symbol)
    return {
        "symbol": symbol, "instrument_id": str(inst.id), "timeframe": timeframe.value,
        "as_of": now.isoformat(), "status": run.get("status"), "mode": "shadow_only",
        "inputs": run.get("inputs", {}),
        "explain": explained,
        "ensemble": {"decision": selfheal.ensemble(calls, weights["weights"]) if calls
                     else "WAIT", "weights_version": weights["version"],
                     "directional_votes": len(calls)},
        "rocket": {"signals": scan["signals"], "scanned": scan["scanned"]},
        "risk": {"source": risk_ctx.source, "equity": risk_ctx.equity,
                 "daily_pnl_pct": risk_ctx.daily_pnl_pct, "kill_switch": risk_ctx.kill_switch,
                 "data_fresh": risk_ctx.data_fresh},
        "paper_trades": paper,
        "health": {"last_run_at": last_run.created_at.isoformat() if last_run else None,
                   "agents": (last_run.content.get("agents") if last_run else {}) or {}},
        "calendar": None if events is None else
        [e | {"time": e["time"].isoformat()} for e in events if e["currency"] in ccys][:20],
        "learning": {"version": weights["version"], "quarantined":
                     sorted(agent_learning.quarantined(session))},
    }
