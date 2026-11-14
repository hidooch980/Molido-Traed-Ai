"""Telegram alerts (t57u). Off until TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID exist.

Events: paper trade open/close, kill switch engaged, a streak of Risk Brain
BLOCK verdicts, daily loss cap, xAI daily budget reached. Each event is sent
once (deduplicated by a key stored in agent memory, kind "risk",
source_ref "notify:<key>"). The token is read per call and never logged.
Sending is the only side effect; it cannot place or change anything.
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents import memory
from app.models.agent_memory import AgentMemoryEntry

BLOCK_STREAK = 5
Sender = Callable[[str], bool]


def configured() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
                and os.getenv("TELEGRAM_CHAT_ID", "").strip())


def telegram_send(text: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        return False
    body = json.dumps({"chat_id": chat, "text": text[:4000],
                       "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 - fixed host
            return bool(resp.status == 200)
    except Exception:  # noqa: BLE001 - never surface the URL (it holds the token)
        return False


def _sent(session: Session, key: str) -> bool:
    n = session.scalar(select(func.count()).select_from(AgentMemoryEntry)
                       .where(AgentMemoryEntry.kind == "risk",
                              AgentMemoryEntry.source_ref == f"notify:{key}"[:128]))
    return (n or 0) > 0


def _mark(session: Session, key: str, text: str, delivered: bool) -> None:
    memory.remember(session, "RK01", "risk", f"alert: {text}"[:4000],
                    content={"event": "notify", "key": key, "delivered": delivered},
                    source_ref=f"notify:{key}"[:128])


def pending_events(session: Session, *, now: datetime, risk_ctx: Any = None,
                   since: timedelta = timedelta(hours=6)) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    day = now.date().isoformat()
    trades = session.scalars(select(AgentMemoryEntry)
                             .where(AgentMemoryEntry.kind == "trade",
                                    AgentMemoryEntry.created_at >= now - since)
                             .order_by(AgentMemoryEntry.created_at))
    for t in trades:
        c = t.content or {}
        ev, tid = c.get("event"), c.get("trade_id")
        if ev == "open":
            side = {"BUY": "خرید", "SELL": "فروش", "long": "خرید", "short": "فروش"}.get(
                str(c.get("direction") or ""), str(c.get("direction") or "—"))
            acc = c.get("account") or "main"
            out.append((f"open:{tid}",
                        f"📄 معامله آزمایشی باز شد: {t.symbol} {side} [حساب {acc}] "
                        f"ورود {c.get('entry')} حدضرر {c.get('stop_loss')} "
                        f"حدسود {c.get('take_profit')}"))
        elif ev == "close":
            result = {"stop": "حدضرر", "target": "حدسود"}.get(
                str(c.get("result") or ""), str(c.get("result") or "—"))
            acc = c.get("account") or "main"
            out.append((f"close:{tid}",
                        f"📄 معامله آزمایشی بسته شد: {t.symbol} {result} "
                        f"R={c.get('r')} [حساب {acc}]"))
    if risk_ctx is not None:
        if risk_ctx.kill_switch:
            out.append((f"kill:{day}", "🛑 کلید اضطراری فعال است"))
        from app.agents.risk_gate import RiskLimits

        lim = RiskLimits().max_daily_loss_pct
        d = risk_ctx.daily_pnl_pct
        if d is not None and d <= -lim:
            out.append((f"dailycap:{day}",
                        f"⚠️ زیان روزانه {d:.2f}٪ به سقف {lim:g}٪ رسید"))
    sigs = list(session.scalars(select(AgentMemoryEntry)
                                .where(AgentMemoryEntry.kind == "rocket")
                                .order_by(AgentMemoryEntry.created_at.desc())
                                .limit(BLOCK_STREAK)))
    if len(sigs) == BLOCK_STREAK and all(
            ((s.content or {}).get("risk_review") or {}).get("verdict") == "BLOCK" for s in sigs):
        out.append((f"blockstreak:{sigs[-1].id}",
                    f"🚧 مغز ریسک آخرین {BLOCK_STREAK} سیگنال موشکی را مسدود کرد"))
    usd_limit = os.getenv("MOLIDO_XAI_DAILY_USD_LIMIT", "").strip()
    if usd_limit:
        from app.models.agent_usage import AgentLlmUsage

        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        spent = session.scalar(select(func.coalesce(func.sum(AgentLlmUsage.cost_usd), 0.0))
                               .where(AgentLlmUsage.created_at >= start)) or 0.0
        try:
            if float(spent) >= float(usd_limit):
                out.append((f"xaicap:{day}",
                            f"💸 بودجه روزانه xAI ({usd_limit} دلار) تمام شد"))
        except ValueError:
            pass
    return out


def cycle(session: Session, *, now: datetime | None = None, risk_ctx: Any = None,
          send: Sender | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    events = pending_events(session, now=now, risk_ctx=risk_ctx)
    if send is None and not configured():
        return {"configured": False, "pending": len(events), "sent": 0}
    sender = send or telegram_send
    sent = 0
    for key, text in events:
        if _sent(session, key):
            continue
        ok = sender(text)
        _mark(session, key, text, ok)
        sent += ok
    return {"configured": True, "pending": len(events), "sent": sent}


def status(session: Session, limit: int = 20) -> dict[str, Any]:
    rows = memory.recall(session, kind="risk", limit=limit * 2)
    return {"configured": configured(), "channel": "telegram",
            "recent": [{"at": r.created_at.isoformat(), "text": r.summary,
                        "delivered": (r.content or {}).get("delivered")}
                       for r in rows if (r.content or {}).get("event") == "notify"][:limit]}
