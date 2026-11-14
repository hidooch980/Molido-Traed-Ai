"""Paper-trading cycle for agent signals. No order, no command file, no broker call.

Off unless `MOLIDO_AGENT_PAPER=1`. Run by hand: `python -m app.services.agent_paper`.
Each cycle scans RT10, reviews every signal with the read-only account context,
records an APPROVE/REDUCE as a paper trade in agent memory, and resolves open
paper trades on closed bars.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import memory
from app.agents.paper import open_trade, resolve
from app.agents.risk_gate import RiskContext
from app.core.enums import Timeframe
from app.models.instruments import Instrument
from app.services import agent_account, agent_scan, agent_walkforward

FLAG = "MOLIDO_AGENT_PAPER"


def enabled() -> bool:
    return os.environ.get(FLAG, "").strip().lower() in ("1", "true", "yes", "on")


def _events(session: Session, limit: int = 500) -> list[dict[str, Any]]:
    rows = memory.recall(session, kind="trade", limit=limit)
    return [r.content | {"_at": r.created_at.isoformat()} for r in rows
            if r.content.get("mode") == "paper"]


def book(session: Session, *, limit: int = 100) -> dict[str, Any]:
    events = _events(session)
    closed = {e["trade_id"]: e for e in events if e.get("event") == "close"}
    trades = []
    for e in events:
        if e.get("event") != "open":
            continue
        out = closed.get(e["trade_id"])
        trades.append({**e, "status": "closed" if out else "open",
                       "result": out.get("result") if out else None,
                       "r": out.get("r") if out else None})
    rs = [t["r"] for t in trades if t["r"] is not None]
    return {
        "mode": "paper",
        "enabled": enabled(),
        "trades": trades[:limit],
        "closed": len(rs),
        "open": sum(1 for t in trades if t["status"] == "open"),
        "total_r": round(sum(rs), 4) if rs else 0.0,
        "win_rate": round(sum(1 for r in rs if r > 0) / len(rs), 4) if rs else None,
        "note": "Paper only. Not a measured edge; small samples mean nothing.",
    }


def run_cycle(session: Session, timeframe: Timeframe = Timeframe.H1, *,
              account_key: str | None = None, now: datetime | None = None,
              risk_ctx: RiskContext | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    state = book(session, limit=500)
    open_trades = [t for t in state["trades"] if t["status"] == "open"]
    ctx = risk_ctx or agent_account.risk_context(account_key, session=session, now=now)
    if ctx.open_symbols is not None:
        paper_syms = tuple(t["symbol"] for t in open_trades)
        ctx = RiskContext(**{**ctx.__dict__, "open_symbols": ctx.open_symbols + paper_syms})
    closed = 0
    for trade in open_trades:
        inst = session.scalar(select(Instrument).where(Instrument.symbol == trade["symbol"]))
        if inst is None:
            continue
        tf = Timeframe(trade["timeframe"])
        _, bars = agent_scan.candles(session, inst, tf, now)
        opened = datetime.fromisoformat(trade["opened_at"])
        later = [b for b in bars if b.open_time >= opened and b.open_time + tf.delta <= now]
        outcome = resolve(trade, later)
        if outcome["result"] in ("stop", "target"):
            memory.remember(session, "RT09", "trade", f"paper close {trade['symbol']} "
                            f"{outcome['result']}", symbol=trade["symbol"],
                            source_ref=trade["trade_id"],
                            content={"mode": "paper", "event": "close",
                                     "trade_id": trade["trade_id"], **outcome})
            closed += 1
    scan = agent_scan.scan(session, timeframe, risk_ctx=ctx, as_of=now)
    recorded = agent_walkforward.record_signals(session, scan)
    resolved = agent_walkforward.resolve_recorded(session, now=now)
    known = {t["trade_id"] for t in state["trades"]}
    opened_n = 0
    for sig in scan["signals"]:
        trade = open_trade(sig, sig["risk_review"])
        if trade is None or trade.trade_id in known:
            continue
        memory.remember(session, "RT10", "trade", f"paper open {trade.symbol} {trade.direction} "
                        f"{trade.verdict}", symbol=trade.symbol, source_ref=trade.trade_id,
                        content={**trade.as_dict(), "event": "open"})
        opened_n += 1
    return {"opened": opened_n, "closed": closed, "signals": len(scan["signals"]),
            "recorded": recorded, "resolved": resolved,
            "risk_context_source": ctx.source}


def main() -> int:
    if not enabled():
        print(f"{FLAG} is off; nothing done.")
        return 0
    from app.db.session import session_scope

    with session_scope() as session:
        result = run_cycle(session)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
