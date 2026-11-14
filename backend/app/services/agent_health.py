"""Agent health, forward performance, decision traces and alerts (stage 16, read-only).

Health and performance come from the run records `agent_run.run_symbol(record=True)`
stores (memory kind "agent", event "run"). Alerts are computed on request and
returned; nothing is sent anywhere (no email, chat or push).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import memory, registry
from app.agents.analyzers.runner import ANALYZERS
from app.agents.risk_gate import RiskContext, RiskLimits
from app.agents.selfheal import Sample
from app.core.enums import Timeframe
from app.models.instruments import Instrument
from app.services import agent_scan

STALE_AFTER = timedelta(hours=24)
DEGRADED_ERROR_RATE = 0.2


def _runs(session: Session, limit: int) -> list[Any]:
    return [r for r in memory.recall(session, kind="agent", limit=limit)
            if (r.content or {}).get("event") == "run"]


def _when(row: Any) -> datetime:
    at = row.created_at
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def health(session: Session, *, now: datetime | None = None, limit: int = 500) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    stats: dict[str, dict[str, Any]] = {}
    for row in sorted(_runs(session, limit), key=_when):
        for agent_id, h in (row.content.get("agents") or {}).items():
            s = stats.setdefault(agent_id, {"runs": 0, "errors": 0, "ms": 0.0,
                                            "last_error": None})
            s["runs"] += 1
            s["ms"] += float(h.get("ms") or 0.0)
            if not h.get("ok", True):
                s["errors"] += 1
                s["last_error"] = h.get("error")
            s["last_run_at"] = _when(row).isoformat()
            s["last_symbol"] = row.symbol
            s["last_recommendation"] = h.get("recommendation")
    agents = []
    for role in registry.all_roles():
        if role.id not in ANALYZERS:
            agents.append({"id": role.id, "status": "not_an_analyzer",
                           "note": "checked by its own module and tests, not by agent runs"})
            continue
        if role.id not in stats:
            agents.append({"id": role.id, "status": "never_run"})
            continue
        s = stats[role.id]
        rate = s["errors"] / s["runs"]
        last = datetime.fromisoformat(s["last_run_at"])
        status = ("degraded" if rate > DEGRADED_ERROR_RATE
                  else "stale" if now - last > STALE_AFTER else "ok")
        agents.append({"id": role.id, "status": status, "runs": s["runs"],
                       "error_rate": round(rate, 4), "avg_ms": round(s["ms"] / s["runs"], 2),
                       "last_run_at": s["last_run_at"], "last_symbol": s["last_symbol"],
                       "last_recommendation": s["last_recommendation"],
                       "last_error": s["last_error"]})
    counts = Counter(a["status"] for a in agents)
    return {"as_of": now.isoformat(), "agents": agents, "counts": dict(counts)}


def resolved_samples(session: Session, *, horizon_bars: int = 4, limit: int = 500,
                     now: datetime | None = None) -> tuple[list[Sample], dict[str, int]]:
    """Each recorded run with BUY/SELL calls whose horizon has passed, with the
    close-to-close move after it (point-in-time). Also: pending calls per agent."""
    now = now or datetime.now(UTC)
    samples: list[Sample] = []
    pending: dict[str, int] = defaultdict(int)
    inst_cache: dict[str, Instrument | None] = {}
    for row in _runs(session, limit):
        c = row.content
        try:
            tf = Timeframe(c.get("timeframe"))
            as_of = datetime.fromisoformat(c["as_of"])
        except (KeyError, TypeError, ValueError):
            continue
        calls = {a: h["recommendation"] for a, h in (c.get("agents") or {}).items()
                 if h.get("recommendation") in ("BUY", "SELL") and not h.get("skipped")}
        if not calls:
            continue
        end = as_of + tf.delta * horizon_bars
        if end > now:
            for a in calls:
                pending[a] += 1
            continue
        if row.symbol not in inst_cache:
            inst_cache[row.symbol] = session.scalars(
                select(Instrument).where(Instrument.symbol == row.symbol)).first()
        inst = inst_cache[row.symbol]
        if inst is None:
            continue
        _, before = agent_scan.candles(session, inst, tf, as_of, lookback=3)
        _, after = agent_scan.candles(session, inst, tf, end, lookback=3)
        if not before or not after or after[-1].open_time <= before[-1].open_time:
            for a in calls:
                pending[a] += 1
            continue
        move = (after[-1].close - before[-1].close) / before[-1].close
        samples.append(Sample(as_of, calls, move))
    return samples, dict(pending)


def performance(session: Session, *, horizon_bars: int = 4, limit: int = 500,
                now: datetime | None = None) -> dict[str, Any]:
    """Forward hit rate of each agent's BUY/SELL calls from stored run records.

    The move is close-to-close over `horizon_bars` closed bars after the run,
    read point-in-time; spread and costs are not included, so this is a
    direction check, not a P&L."""
    samples, pending = resolved_samples(session, horizon_bars=horizon_bars, limit=limit,
                                        now=now)
    per: dict[str, dict[str, Any]] = defaultdict(lambda: {"calls": 0, "hits": 0, "move": 0.0})
    for s in samples:
        for a, rec in s.calls.items():
            signed = s.move if rec == "BUY" else -s.move
            p = per[a]
            p["calls"] += 1
            p["hits"] += 1 if signed > 0 else 0
            p["move"] += signed
    rows = []
    for a in sorted(set(per) | set(pending)):
        p = per[a]
        n = p["calls"]
        rows.append({"id": a, "calls": n, "pending": pending.get(a, 0),
                     "hit_rate": round(p["hits"] / n, 4) if n else None,
                     "avg_signed_move_pct": round(100 * p["move"] / n, 4) if n else None,
                     "enough_data": n >= 30})
    return {"horizon_bars": horizon_bars, "agents": rows,
            "note": "direction only, before spread and costs; under 30 calls is not evidence"}


def explain(run: dict[str, Any]) -> dict[str, Any]:
    """A readable trace of one agent run: who said what, on what evidence, and why
    the system's answer is still 'no order'."""
    if run.get("status") != "ran":
        return {"status": run.get("status"), "trace": [], "summary": run.get("reason")}
    msgs = run["messages"]
    votes = Counter(m["recommendation"] for m in msgs if m["agent_id"] != "BRAIN-01")
    directional = {k: v for k, v in votes.items() if k in ("BUY", "SELL")}
    lean = max(directional, key=lambda k: directional[k]) if directional else "WAIT"
    trace = [{"agent": m["agent_id"], "says": m["recommendation"],
              "confidence": m["confidence"], "because": m["analysis"],
              "evidence": m["evidence"][:4]} for m in msgs if m["agent_id"] != "BRAIN-01"]
    trace.sort(key=lambda t: (t["says"] == "WAIT", -t["confidence"]))
    brain = next((m for m in msgs if m["agent_id"] == "BRAIN-01"), None)
    missing = [k for k, v in run.get("inputs", {}).items() if v in (None, False, 0)]
    return {"symbol": run["symbol"], "timeframe": run["timeframe"], "as_of": run["as_of"],
            "votes": dict(votes), "lean": lean,
            "dissent": [t["agent"] for t in trace if t["says"] in ("BUY", "SELL")
                        and t["says"] != lean],
            "missing_inputs": missing,
            "brain01": brain["evidence"] if brain else [],
            "decision": "NO ORDER - analyzers advise only; Risk Brain is the final authority "
                        "and live execution is not connected to agents",
            "trace": trace}


def alerts(session: Session, *, risk_ctx: RiskContext | None = None,
           ftmo: dict[str, Any] | None = None, now: datetime | None = None,
           limits: RiskLimits | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    limits = limits or RiskLimits()
    out: list[dict[str, Any]] = []

    def add(level: str, source: str, text: str) -> None:
        out.append({"level": level, "source": source, "message": text})

    for a in health(session, now=now)["agents"]:
        if a["status"] == "degraded":
            add("warning", a["id"], f"error rate {a['error_rate']:.0%}: {a['last_error']}")
        elif a["status"] == "stale":
            add("info", a["id"], f"no run since {a['last_run_at']}")
    if risk_ctx is not None:
        if risk_ctx.kill_switch:
            add("critical", "RK01", "kill switch is engaged")
        if risk_ctx.data_fresh is False:
            add("warning", "RK01", "account data from the bridge is stale")
        if risk_ctx.equity is None:
            add("warning", "RK01", f"account unknown ({risk_ctx.source}); all signals BLOCK")
        d = risk_ctx.daily_pnl_pct
        if d is not None and d <= -limits.max_daily_loss_pct:
            add("critical", "RK01", f"daily loss {d:.2f}% at or beyond the "
                                    f"{limits.max_daily_loss_pct}% limit")
        elif d is not None and d <= -limits.max_daily_loss_pct * \
                limits.reduce_at_daily_loss_fraction:
            add("warning", "RK01", f"daily loss {d:.2f}%: past half the limit, sizes halve")
    for row in (ftmo or {}).get("accounts", []):
        label = row.get("account", {}).get("label", "?")
        v = (row.get("verdict") or {}).get("verdict")
        if v == "block":
            add("critical", "RK05", f"{label}: challenge rules say block")
        elif v == "reduce":
            add("warning", "RK05", f"{label}: close to a challenge limit")
        elif row.get("status") not in (None, "monitored"):
            add("info", "RK05", f"{label}: {row.get('status')}")
    rank = {"critical": 0, "warning": 1, "info": 2}
    out.sort(key=lambda a: rank[a["level"]])
    return {"as_of": now.isoformat(), "alerts": out, "counts": dict(Counter(a["level"]
                                                                          for a in out)),
            "delivery": "shown here only; nothing is sent"}
