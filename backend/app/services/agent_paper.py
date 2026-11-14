"""Paper-trading cycle for agent signals. No order, no command file, no broker call.

Off unless `MOLIDO_AGENT_PAPER=1`. Run by hand: `python -m app.services.agent_paper`.
Each cycle scans RT10, reviews every signal with the read-only account context,
records an APPROVE/REDUCE as a paper trade in agent memory, and resolves open
paper trades on closed bars.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import memory
from app.agents.paper import open_trade, resolve
from app.agents.risk_gate import RiskContext
from app.core.enums import Timeframe
from app.models.agent_memory import AgentMemoryEntry
from app.models.instruments import Instrument
from app.providers.metatrader import bridge_dirs
from app.services import agent_account, agent_events, agent_scan, agent_symbols, agent_walkforward

FLAG = "MOLIDO_AGENT_PAPER"


def enabled() -> bool:
    return os.environ.get(FLAG, "").strip().lower() in ("1", "true", "yes", "on")


def _events(session: Session, limit: int = 5000) -> list[dict[str, Any]]:
    rows = session.scalars(select(AgentMemoryEntry).where(AgentMemoryEntry.kind == "trade")
                           .order_by(AgentMemoryEntry.created_at.desc()).limit(limit))
    return [r.content | {"_at": r.created_at.isoformat()} for r in rows
            if r.content.get("mode") == "paper"]


def book(session: Session, *, limit: int = 100,
         account: str | None = None) -> dict[str, Any]:
    """`account` None = every account; "" = the trades recorded without one."""
    events = [e for e in _events(session)
              if account is None or e.get("account", "") == account]
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
        "accounts": sorted({str(t.get("account", "")) for t in trades}),
        "note": "Paper only. Not a measured edge; small samples mean nothing.",
    }


def _symbol_point(session: Session, symbol: Any) -> float | None:
    if not symbol:
        return None
    inst = session.scalar(select(Instrument).where(Instrument.symbol == str(symbol)))
    if inst is None:
        return None
    for value in (getattr(inst, "point", None), getattr(inst, "tick_size", None)):
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return None


def _loss_setups(session: Session, limit: int = 500) -> list[dict]:
    rows = memory.recall(session, kind="pattern", limit=limit)
    return [r.content | {"at": r.content.get("at") or r.created_at.isoformat()}
            for r in rows if (r.content or {}).get("event") == "loss_setup"]


def run_cycle(session: Session, timeframe: Timeframe = Timeframe.H1, *,
              account_key: str | None = None, now: datetime | None = None,
              risk_ctx: RiskContext | None = None, record: bool = True) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    account = account_key or ""
    state = book(session, limit=5000, account=account)
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
                            content={"mode": "paper", "event": "close", "account": account,
                                     "trade_id": trade["trade_id"], **outcome})
            if outcome.get("r") is not None and float(outcome["r"]) < 0:
                memory.remember(
                    session, "EX04", "pattern",
                    f"loss setup {trade['symbol']} {trade.get('direction')}",
                    symbol=trade["symbol"], source_ref=trade["trade_id"],
                    content={"event": "loss_setup", "account": account,
                             "symbol": trade["symbol"],
                             "direction": trade.get("direction"),
                             "regime": trade.get("regime") or "",
                             "r": outcome.get("r"), "at": now.isoformat()},
                )
            closed += 1
    scan = agent_scan.scan(session, timeframe, risk_ctx=ctx, as_of=now,
                           symbols=agent_symbols.universe(session)["symbols"],
                           events=agent_events.high_impact())
    recorded = agent_walkforward.record_signals(session, scan) if record else 0
    resolved = agent_walkforward.resolve_recorded(session, now=now) if record else 0
    known = {t["trade_id"] for t in state["trades"]}
    opened_n = 0
    from app.services import agent_backtest_gate

    allowed, gate_why = agent_backtest_gate.paper_allowed(session)
    from app.agents.slippage import decide as slippage_decide
    from app.services import agent_slippage

    slip_fills = agent_slippage.fills_for(session)
    from app.agents.guards import correlated, loss_factor
    open_syms = list(ctx.open_symbols or ()) + [t["symbol"] for t in open_trades]
    losses = _loss_setups(session)
    for sig in scan["signals"] if allowed else []:
        slip = slippage_decide(slip_fills, symbol=str(sig.get("symbol") or ""),
                               default_point=_symbol_point(session, sig.get("symbol")))
        if slip.blocks:
            continue
        why = correlated(str(sig.get("symbol") or ""), open_syms)
        if why:
            continue
        setup = {"symbol": sig.get("symbol"), "direction": sig.get("direction"),
                 "regime": (sig.get("regime") or "")}
        if loss_factor(setup, losses, now=now) <= 0.5:
            continue
        trade = open_trade(sig, sig["risk_review"])
        if trade is None:
            continue
        if account:
            trade = replace(trade, trade_id=hashlib.sha256(
                f"{trade.trade_id}:{account}".encode()).hexdigest()[:24])
        if trade.trade_id in known:
            continue
        memory.remember(session, "RT10", "trade", f"paper open {trade.symbol} {trade.direction} "
                        f"{trade.verdict}", symbol=trade.symbol, source_ref=trade.trade_id,
                        content={**trade.as_dict(), "event": "open", "account": account})
        opened_n += 1
    return {"opened": opened_n, "closed": closed, "signals": len(scan["signals"]),
            "recorded": recorded, "resolved": resolved,
            "risk_context_source": ctx.source, "account": account, "backtest_gate": gate_why}


def run_all_accounts(session: Session, timeframe: Timeframe = Timeframe.H1, *,
                     now: datetime | None = None) -> dict[str, Any]:
    """One paper book per MT5 account, each reviewed against that account's own
    read-only risk context. Signals are recorded once per cycle."""
    keys = sorted(bridge_dirs(session=session))
    out = {}
    for i, key in enumerate(keys):
        try:
            out[key] = run_cycle(session, timeframe, account_key=key, now=now, record=i == 0)
        except Exception as exc:  # noqa: BLE001 - one account must not stop the rest
            out[key] = {"error": f"{type(exc).__name__}: {exc}"[:200]}
    return {"accounts": out, "mode": "paper"}


def main() -> int:
    if not enabled():
        print(f"{FLAG} is off; nothing done.")
        return 0
    from app.db.session import session_scope

    with session_scope() as session:
        result = run_all_accounts(session)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
