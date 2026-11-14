"""Nightly report (t57u): paper P/L per account, per-agent performance and the
learning changes of the day. Stored in agent memory (kind "strategy",
source_ref "nightly_report:<date>"), shown on the dashboard, and sent by
Telegram when that is configured. Built once per Tehran day after REPORT_HOUR.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
    wr = p["win_rate"]
    wr_s = f"{wr:.0%}" if wr is not None else "نامشخص"
    lines = [f"📊 گزارش شبانه مولیدو {r['date']} (پیپر/سایه)",
             f"پیپر: مجموع {p['total_r']}R، بسته‌شده {p['closed']}، باز {p['open']}، "
             f"نرخ برد {wr_s}"]
    lines += [f"  {acc}: {a['total_r']}R (بسته‌شده {a['closed']}، امروز {a['opened_today']} باز شد)"
              for acc, a in sorted(p["accounts"].items())]
    top = "، ".join(f"{a['id']} {a['hit_rate']:.0%}" for a in r["agents"]["top"]
                    if a["hit_rate"] is not None)
    lines.append(f"برترین ایجنت‌ها: {top or '—'}")
    lr = r["learning"]
    quarantined = "، ".join(lr["quarantined"]) or "—"
    lines.append(f"یادگیری: وزن‌ها نسخه {lr['weights']}، "
                 f"{len(lr['changes_today'])} تغییر امروز، قرنطینه {quarantined}")
    if lr["brain_shadow"]:
        lines.append(f"سایه مغز و ایجنت‌ها: {lr['brain_shadow']['status']}")
    lines.append(f"دروازه بک‌تست: {r['backtest_gate'] or '—'}")
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


def _week_id(local: datetime) -> str:
    year, week, _ = local.isocalendar()
    return f"{year}-W{week:02d}"


def _week_ref(week: str) -> str:
    return f"weekly_report:{week}"


def weekly_stress(session: Session, *, now: datetime | None = None,
                  symbols: tuple[str, ...] = ("EURUSD", "XAUUSD", "GBPUSD"),
                  top_days: int = 5) -> dict[str, Any]:
    """Replay shadow runs on the most volatile recent days. No orders."""
    from sqlalchemy import select as sel

    from app.core.enums import Timeframe
    from app.models.instruments import Instrument
    from app.services import agent_run, agent_scan

    now = now or datetime.now(UTC)
    ranges: dict[Any, float] = {}
    for name in symbols:
        inst = session.scalars(sel(Instrument).where(Instrument.symbol == name)).first()
        if inst is None:
            continue
        _, bars = agent_scan.candles(session, inst, Timeframe.H1, now, lookback=24 * 70)
        for bar in bars:
            day = bar.open_time.astimezone(UTC).date()
            ranges[day] = ranges.get(day, 0.0) + float(bar.high - bar.low)
    ranked = sorted(ranges, key=lambda d: ranges[d], reverse=True)[:top_days]
    results = []
    for day in ranked:
        as_of = datetime(day.year, day.month, day.day, 21, 0, tzinfo=UTC)
        day_rows: list[dict[str, Any]] = []
        for name in symbols:
            try:
                out = agent_run.run_symbol(session, name, Timeframe.H1, as_of=as_of,
                                           record=False)
            except Exception as exc:  # noqa: BLE001
                day_rows.append({"symbol": name, "status": "error",
                                 "reason": type(exc).__name__})
                continue
            vote = out.get("vote") or {}
            day_rows.append({"symbol": name, "status": str(out.get("status") or ""),
                             "regime": (out.get("regime") or {}).get("regime"),
                             "vote": vote.get("recommendation"),
                             "withheld": vote.get("withheld")})
        results.append({"day": day.isoformat(), "range_score": round(ranges[day], 5),
                        "symbols": day_rows})
    return {"as_of": now.isoformat(), "volatile_days": [d.isoformat() for d in ranked],
            "results": results, "note": "shadow replay only; not a live test"}


def build_weekly(session: Session, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    local = now.astimezone(TEHRAN)
    start = (local - timedelta(days=7)).astimezone(UTC)
    daily = build(session, now=now)
    from app.services import agent_paper, agent_voting

    book = agent_paper.book(session, limit=5000)
    week_closed = [t for t in book["trades"]
                   if t.get("r") is not None and t.get("opened_at")
                   and datetime.fromisoformat(t["opened_at"]) >= start]
    rs = [float(t["r"]) for t in week_closed]
    return {
        "week": _week_id(local), "date": local.date().isoformat(),
        "as_of": now.isoformat(), "mode": "paper/shadow",
        "paper_week": {"trades": len(rs), "total_r": round(sum(rs), 4) if rs else 0.0,
                       "win_rate": round(sum(1 for r in rs if r > 0) / len(rs), 4) if rs else None},
        "agents": daily["agents"],
        "underperformers": (agent_voting.latest_report(session) or {}).get("flagged") or [],
        "stress": weekly_stress(session, now=now),
        "backtest_gate": daily["backtest_gate"],
    }


def text_weekly(r: dict[str, Any]) -> str:
    p = r["paper_week"]
    wr = p["win_rate"]
    wr_s = f"{wr:.0%}" if wr is not None else "نامشخص"
    lines = [f"📅 گزارش هفتگی مولیدو {r['week']} (پیپر/سایه)",
             f"پیپر این هفته: {p['trades']} معامله، مجموع {p['total_r']}R، نرخ برد {wr_s}"]
    top = "، ".join(f"{a['id']} {a['hit_rate']:.0%}" for a in r["agents"]["top"]
                    if a.get("hit_rate") is not None)
    lines.append(f"برترین ایجنت‌ها: {top or '—'}")
    flagged = r.get("underperformers") or []
    if flagged:
        names = "، ".join(f"{f['id']} ({f.get('proposal')})" for f in flagged[:8])
        lines.append(f"کم‌بازده‌ها (فقط پیشنهاد): {names}")
    stress = r.get("stress") or {}
    days = "، ".join(stress.get("volatile_days") or []) or "—"
    lines.append(f"تست فشار روی روزهای پرنوسان: {days}")
    lines.append(f"دروازه بک‌تست: {r.get('backtest_gate') or '—'}")
    return "\n".join(lines)


def maybe_weekly(session: Session, *, now: datetime | None = None, send: Any = None,
                 force: bool = False) -> dict[str, Any] | None:
    now = now or datetime.now(UTC)
    local = now.astimezone(TEHRAN)
    if not force and (local.isoweekday() != 5 or local.hour < REPORT_HOUR):
        return None
    week = _week_id(local)
    exists = session.scalar(select(AgentMemoryEntry.id).where(
        AgentMemoryEntry.kind == "strategy",
        AgentMemoryEntry.source_ref == _week_ref(week)).limit(1))
    if exists is not None and not force:
        return None
    report = build_weekly(session, now=now)
    from app.services import agent_notify

    sender = send or (agent_notify.telegram_send if agent_notify.configured() else None)
    body = text_weekly(report)
    report["delivered"] = bool(sender(body)) if sender else False
    memory.remember(session, "BRAIN-01", "strategy", f"weekly report {week}", content=report,
                    source_ref=_week_ref(week))
    return report
