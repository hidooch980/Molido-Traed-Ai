"""Nightly report (t57u): paper P/L per account, per-agent performance and the
learning changes of the day. Stored in agent memory (kind "strategy",
source_ref "nightly_report:<date>"), shown on the dashboard, and sent by
Telegram when that is configured. Built once per Tehran day after REPORT_HOUR.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import memory
from app.models.agent_memory import AgentMemoryEntry

TEHRAN = ZoneInfo("Asia/Tehran")
REPORT_HOUR = 23


def _ref(day: str) -> str:
    return f"nightly_report:{day}"


def build(session: Session, *, now: datetime | None = None) -> dict[str, Any]:
    from app.services import (
        agent_backtest_gate,
        agent_brain_shadow,
        agent_health,
        agent_learning,
        agent_paper,
    )

    now = now or datetime.now(UTC)
    local = now.astimezone(TEHRAN)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    book = agent_paper.book(session, limit=5000)
    per_account: dict[str, dict[str, Any]] = {}
    for t in book["trades"]:
        acc = str(t.get("account") or "main")
        a = per_account.setdefault(acc, {"opened_today": 0, "closed": 0, "total_r": 0.0,
                                         "open": 0})
        opened = datetime.fromisoformat(t["opened_at"]) if t.get("opened_at") else None
        if opened and opened >= start:
            a["opened_today"] += 1
        if t["status"] == "open":
            a["open"] += 1
        if t.get("r") is not None:
            a["closed"] += 1
            a["total_r"] = round(a["total_r"] + float(t["r"]), 4)
    perf = agent_health.performance(session, now=now)
    ranked = sorted([p for p in perf["agents"] if p["calls"]],
                    key=lambda p: (p["hit_rate"] or 0), reverse=True)
    changes = [r.content for r in session.scalars(
        select(AgentMemoryEntry).where(AgentMemoryEntry.kind == "model_performance",
                                       AgentMemoryEntry.created_at >= start))]
    shadow = agent_brain_shadow.status(session)["latest_verdict"]
    return {
        "date": local.date().isoformat(), "as_of": now.isoformat(), "mode": "paper/shadow",
        "paper": {"total_r": book["total_r"], "win_rate": book["win_rate"],
                  "closed": book["closed"], "open": book["open"], "accounts": per_account},
        "agents": {"top": ranked[:5], "bottom": ranked[-5:][::-1] if len(ranked) > 5 else [],
                   "with_enough_data": sum(1 for p in ranked if p["enough_data"]),
                   "note": perf["note"]},
        "learning": {"weights": agent_learning.current(session).get("version"),
                     "changes_today": [{"version": c.get("version"), "reason": c.get("reason"),
                                        "rollback": c.get("rollback")} for c in changes
                                       if c.get("event") == "ensemble_weights"],
                     "quarantined": sorted(agent_learning.quarantined(session)),
                     "brain_shadow": shadow and {"status": shadow.get("status"),
                                                 "reason": shadow["decision"]["reason"]}},
        "backtest_gate": (agent_backtest_gate.status(session)["current"] or {}).get("verdict"),
    }


def text(r: dict[str, Any]) -> str:
    p = r["paper"]
    lines = [f"📊 Molido nightly report {r['date']} (paper/shadow)",
             f"Paper: total {p['total_r']}R, closed {p['closed']}, open {p['open']}, "
             f"win rate {p['win_rate'] if p['win_rate'] is not None else '—'}"]
    lines += [f"  {acc}: {a['total_r']}R ({a['closed']} closed, {a['opened_today']} today)"
              for acc, a in sorted(p["accounts"].items())]
    top = ", ".join(f"{a['id']} {a['hit_rate']:.0%}" for a in r["agents"]["top"]
                    if a["hit_rate"] is not None)
    lines.append(f"Top agents: {top or '—'}")
    lr = r["learning"]
    lines.append(f"Learning: weights v{lr['weights']}, {len(lr['changes_today'])} change(s) today, "
                 f"quarantined {', '.join(lr['quarantined']) or '—'}")
    if lr["brain_shadow"]:
        lines.append(f"Brain+agents shadow: {lr['brain_shadow']['status']}")
    lines.append(f"Backtest gate: {r['backtest_gate'] or '—'}")
    return "\n".join(lines)


def latest(session: Session, limit: int = 14) -> list[dict[str, Any]]:
    rows = session.scalars(select(AgentMemoryEntry)
                           .where(AgentMemoryEntry.kind == "strategy",
                                  AgentMemoryEntry.source_ref.like("nightly_report:%"))
                           .order_by(AgentMemoryEntry.created_at.desc()).limit(limit))
    return [r.content for r in rows]


def maybe_run(session: Session, *, now: datetime | None = None, send: Any = None,
              force: bool = False) -> dict[str, Any] | None:
    now = now or datetime.now(UTC)
    local = now.astimezone(TEHRAN)
    if not force and local.hour < REPORT_HOUR:
        return None
    day = local.date().isoformat()
    exists = session.scalar(select(AgentMemoryEntry.id).where(
        AgentMemoryEntry.kind == "strategy", AgentMemoryEntry.source_ref == _ref(day)).limit(1))
    if exists is not None and not force:
        return None
    report = build(session, now=now)
    from app.services import agent_notify

    sender = send or (agent_notify.telegram_send if agent_notify.configured() else None)
    report["delivered"] = bool(sender(text(report))) if sender else False
    memory.remember(session, "BRAIN-01", "strategy", f"nightly report {day}", content=report,
                    source_ref=_ref(day))
    return report


