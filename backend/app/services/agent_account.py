"""Read-only account state for the agent risk gate, from the existing MT5 file bridge.

Nothing here writes to the bridge or queues a command. Any value that cannot be
read is returned as None, which the risk gate turns into a BLOCK.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.agents.risk_gate import RiskContext
from app.providers.metatrader import MetaTraderBridge, bridge_dirs

_FORMATS = ("%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M", "%Y-%m-%d %H:%M:%S")


def _when(raw: Any) -> datetime | None:
    if not raw:
        return None
    text = str(raw)
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        stamp = None
        for fmt in _FORMATS:
            try:
                stamp = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if stamp is None:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


def _provider(account_key: str | None, session: Any = None) -> MetaTraderBridge:
    dirs = bridge_dirs(session=session) if session is not None else bridge_dirs()
    if account_key and account_key in dirs:
        return MetaTraderBridge(dirs[account_key])
    return MetaTraderBridge()


def snapshot(account_key: str | None = None, *, session: Any = None,
             now: datetime | None = None,
             provider: MetaTraderBridge | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    prov = provider or _provider(account_key, session)
    account = prov.account(now=now)
    if not account.get("available"):
        return {"available": False, "reason": account.get("reason"), "read_only": True}
    positions = prov.positions(now=now)
    deals = prov.deals(now=now)
    balance = float(account.get("balance") or 0.0)
    equity = float(account.get("equity") or 0.0)
    daily_pnl_pct: float | None = None
    unparsed = 0
    days: set[Any] = set()
    if balance > 0 and deals.get("available"):
        realised = 0.0
        for row in deals.get("deals", []):
            when = _when(row.get("closed_at"))
            if when is None:
                unparsed += 1
                continue
            days.add(when.date())
            if when.date() == now.date():
                realised += float(row.get("net") or row.get("profit") or 0.0)
        if unparsed == 0:
            daily_pnl_pct = round((realised + equity - balance) / balance * 100, 4)
    symbols = None
    if positions.get("available"):
        symbols = sorted({str(p.get("symbol", "")).upper() for p in positions["positions"]})
    return {
        "available": True,
        "read_only": True,
        "login": account.get("login"),
        "server": account.get("server"),
        "currency": account.get("currency"),
        "trade_mode": account.get("trade_mode"),
        "is_real_money": account.get("is_real_money"),
        "balance": balance,
        "equity": equity,
        "daily_pnl_pct": daily_pnl_pct,
        "deals_with_unreadable_time": unparsed,
        "days_traded": len(days),
        "open_symbols": symbols,
    }


def risk_context(account_key: str | None = None, *, session: Any = None,
                 now: datetime | None = None,
                 provider: MetaTraderBridge | None = None) -> RiskContext:
    snap = snapshot(account_key, session=session, now=now, provider=provider)
    if not snap["available"]:
        return RiskContext(source=f"mt5 bridge unavailable: {snap.get('reason')}")
    symbols = snap["open_symbols"]
    return RiskContext(
        equity=snap["equity"] or None,
        daily_pnl_pct=snap["daily_pnl_pct"],
        open_symbols=tuple(symbols) if symbols is not None else None,
        data_fresh=True,
        source=f"mt5 bridge read-only (login {snap.get('login')})",
    )
