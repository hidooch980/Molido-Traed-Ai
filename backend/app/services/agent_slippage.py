"""Record and recall requested-vs-filled slippage for EX02 (shadow/paper only).

Fills are stored in agent memory (kind=trade, event=slippage_fill) so no new
table is required. Incomplete fills (missing requested or filled price) are
dropped, never stored as zero slippage.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.agents import memory
from app.agents.slippage import DEFAULT_CAP_POINTS, parse_fill

EVENT = "slippage_fill"


def record_fill(session: Session, raw: dict[str, Any]) -> dict[str, Any] | None:
    parsed = parse_fill(raw)
    if parsed is None:
        return None
    memory.remember(
        session, "EX02", "trade",
        f"slippage {parsed['symbol']} {parsed['side']} "
        f"{parsed['requested_price']} -> {parsed['filled_price']}",
        symbol=parsed["symbol"],
        source_ref=parsed.get("client_order_id") or "",
        content={"mode": "shadow", "event": EVENT, **parsed},
    )
    return parsed


def fills_for(session: Session, symbol: str | None = None, *, limit: int = 2000,
              ) -> list[dict[str, Any]]:
    rows = memory.recall(session, agent_id="EX02", kind="trade",
                           symbol=symbol, limit=min(500, limit))
    out = []
    for row in rows:
        content = row.content or {}
        if content.get("event") != EVENT:
            continue
        parsed = parse_fill(content)
        if parsed is not None:
            out.append(parsed)
    return out


def cycle_context(session: Session, *, bridge: Any = None,
                  now: datetime | None = None) -> dict[str, Any]:
    """Shared extras for one agent_run cycle. Failures become missing inputs."""
    now = now or datetime.now(UTC)
    extras: dict[str, Any] = {
        "slippage_fills": fills_for(session),
        "slippage_cap_points": DEFAULT_CAP_POINTS,
    }
    try:
        from app.services import agent_account

        ctx = agent_account.risk_context(session=session, now=now)
        extras["risk_context"] = {
            "equity": ctx.equity,
            "daily_pnl_pct": ctx.daily_pnl_pct,
            "open_symbols": list(ctx.open_symbols) if ctx.open_symbols is not None else None,
            "data_fresh": ctx.data_fresh,
            "kill_switch": ctx.kill_switch,
            "source": ctx.source,
        }
        extras["open_symbols"] = extras["risk_context"]["open_symbols"]
    except Exception:  # noqa: BLE001 - missing snapshot is WAIT, not a crash
        extras.setdefault("risk_context", {})
    try:
        from app.providers.metatrader import bridge_dirs

        keys = sorted(bridge_dirs(session=session)) if session is not None else []
        accounts = []
        if keys:
            from app.services import agent_account

            for key in keys:
                try:
                    snap = agent_account.snapshot(key, session=session, now=now)
                    accounts.append({"account": key, **{k: snap.get(k) for k in
                                    ("available", "equity", "daily_pnl_pct",
                                     "open_symbols", "is_real_money")}})
                except Exception:  # noqa: BLE001
                    accounts.append({"account": key, "available": False})
        extras["accounts"] = accounts
    except Exception:  # noqa: BLE001
        extras["accounts"] = []
    return extras
