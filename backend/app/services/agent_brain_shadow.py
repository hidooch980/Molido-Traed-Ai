"""Production brain + agents, in shadow (t51u A).

Each cycle the production pipeline (`brain.cognitive.think`: council + meta) is
asked for its decision, and next to it the decision it *would* make with the
agent ensemble as extra evidence: an opposing ensemble vetoes a directional call
to WAIT, anything else leaves it unchanged. Both are stored (agent memory,
kind "council", source_ref "brain_shadow"); nothing is returned to execution.

`evaluate` scores both on the same stored candles (close-to-close over
`HORIZON_BARS`) and judges them with the system's own champion/challenger rule,
`learning.registry.compare` (>= 60 decisions, >= 80% overlap, 2 sigma). The
registry has no persistent live promotion path, so a win is written as a
PROPOSED learning record for a human; nothing is applied to live.
"""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import memory, selfheal
from app.core.enums import Timeframe
from app.learning import registry
from app.models.agent_memory import AgentMemoryEntry
from app.models.instruments import Instrument
from app.services import agent_scan

FLAG = "MOLIDO_AGENT_BRAIN_SHADOW"
REF = "brain_shadow"
VERDICT_REF = "brain_shadow_verdict"
HORIZON_BARS = 4
MIN_GAP = timedelta(minutes=55)


def enabled() -> bool:
    return os.getenv(FLAG, "").strip().lower() in {"1", "true", "yes", "on"}


def combine(production: str, agents: str) -> str:
    """Agents as evidence: an opposing ensemble vetoes; they never open a trade alone."""
    if production in ("BUY", "SELL") and agents in ("BUY", "SELL") and agents != production:
        return "WAIT"
    return production


def _rows(session: Session, ref: str, limit: int) -> list[AgentMemoryEntry]:
    return list(session.scalars(select(AgentMemoryEntry)
                                .where(AgentMemoryEntry.kind == "council",
                                       AgentMemoryEntry.source_ref == ref)
                                .order_by(AgentMemoryEntry.created_at.desc()).limit(limit)))


def _aware(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def record(session: Session, run: dict[str, Any], weights: dict[str, float], *,
           think: Any = None, now: datetime | None = None) -> dict[str, Any] | None:
    """One shadow row for one agent run (status "ran"). Returns the row content."""
    if run.get("status") != "ran":
        return None
    now = now or datetime.now(UTC)
    symbol, tf = run["symbol"], Timeframe(run["timeframe"])
    inst = session.scalar(select(Instrument).where(Instrument.symbol == symbol))
    if inst is None:
        return None
    recent = session.scalars(select(AgentMemoryEntry)
                             .where(AgentMemoryEntry.kind == "council",
                                    AgentMemoryEntry.source_ref == REF,
                                    AgentMemoryEntry.symbol == symbol)
                             .order_by(AgentMemoryEntry.created_at.desc()).limit(5))
    stamps = [datetime.fromisoformat(r.content["as_of"]) for r in recent
              if (r.content or {}).get("as_of")]
    if any(abs(now - t) < MIN_GAP for t in stamps):
        return None
    _, bars = agent_scan.candles(session, inst, tf, now, lookback=5)
    if not bars:
        return None
    calls = {m["agent_id"]: m["recommendation"] for m in run.get("messages", [])
             if m.get("recommendation") in ("BUY", "SELL") and m.get("agent_id") != "BRAIN-01"}
    agents = selfheal.ensemble(calls, weights) if calls else "WAIT"
    if think is None:
        from app.brain.cognitive import think as think
    proposal = think(session, inst.id, tf, now)
    production = proposal.decision.value
    content = {"event": REF, "timeframe": tf.value, "as_of": now.isoformat(),
               "bar_time": bars[-1].open_time.isoformat(), "close": bars[-1].close,
               "production": production, "conviction": proposal.conviction,
               "agents": agents, "with_agents": combine(production, agents),
               "votes": {"BUY": sum(1 for v in calls.values() if v == "BUY"),
                         "SELL": sum(1 for v in calls.values() if v == "SELL")}}
    memory.remember(session, "council", "council",
                    f"shadow {symbol}: brain {production}, agents {agents}, "
                    f"with agents {content['with_agents']}", content=content, symbol=symbol,
                    source_ref=REF)
    return content


def cycle(session: Session, runs: list[dict[str, Any]], weights: dict[str, float], *,
          max_symbols: int = 12, think: Any = None, now: datetime | None = None) -> dict[str, Any]:
    done = errors = 0
    for run in runs[:max_symbols]:
        try:
            with session.begin_nested():
                done += record(session, run, weights, think=think, now=now) is not None
        except Exception:  # noqa: BLE001 - one brain failure must not stop the loop
            errors += 1
    return {"recorded": done, "errors": errors}


def _version(name: str, ev: registry.Evaluation, start: datetime,
             end: datetime) -> registry.ModelVersion:
    lineage = registry.Lineage(feature_set=("council", "meta") + (("agents",) if
                                                                  name.endswith("agents") else ()),
                               train_start=start, train_end=end, as_of=end,
                               code_version="agents-shadow-1", dataset_quality_score=1.0)
    return registry.ModelVersion(name=name, version=1, lineage=lineage,
                                 stage=registry.ModelStage.SHADOW, evaluation=ev)


def evaluate(session: Session, *, now: datetime | None = None, limit: int = 3000,
             write: bool = True) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    rows = _rows(session, REF, limit)
    by_symbol: dict[str, list[AgentMemoryEntry]] = defaultdict(list)
    for r in rows:
        by_symbol[r.symbol].append(r)
    scored: dict[str, dict[str, Any]] = {"production": {"ids": [], "hits": 0, "r": 0.0},
                                         "with_agents": {"ids": [], "hits": 0, "r": 0.0}}
    pending = 0
    for symbol, items in by_symbol.items():
        inst = session.scalar(select(Instrument).where(Instrument.symbol == symbol))
        if inst is None:
            continue
        tf = Timeframe(items[0].content.get("timeframe", "H1"))
        oldest = min(datetime.fromisoformat(i.content["bar_time"]) for i in items)
        need = int((now - oldest) / tf.delta) + HORIZON_BARS + 5
        _, bars = agent_scan.candles(session, inst, tf, now, lookback=min(5000, need))
        closed = [b for b in bars if b.open_time + tf.delta <= now]
        times = [b.open_time for b in closed]
        for item in items:
            c = item.content
            at = datetime.fromisoformat(c["bar_time"])
            later = [k for k, t in enumerate(times) if t > at]
            if len(later) < HORIZON_BARS:
                pending += 1
                continue
            move = closed[later[HORIZON_BARS - 1]].close - float(c["close"])
            if move == 0:
                continue
            for key in scored:
                d = c.get(key)
                if d not in ("BUY", "SELL"):
                    continue
                signed = move if d == "BUY" else -move
                s = scored[key]
                s["ids"].append(str(item.id))
                s["hits"] += signed > 0
                s["r"] += signed / float(c["close"])
    start = min((_aware(r.created_at) for r in rows), default=now - timedelta(days=1))
    end = max(now, start + timedelta(seconds=1))
    evs = {k: registry.Evaluation(decision_ids=tuple(v["ids"]), hits=int(v["hits"]),
                                  total_r=v["r"]) for k, v in scored.items()}
    decision = registry.compare(_version("production", evs["production"], start, end),
                                _version("production_with_agents", evs["with_agents"],
                                         start, end))
    out = {"as_of": now.isoformat(), "rows": len(rows), "pending": pending,
           "horizon_bars": HORIZON_BARS,
           "production": {"n": evs["production"].sample, "hit_rate": evs["production"].hit_rate},
           "with_agents": {"n": evs["with_agents"].sample,
                           "hit_rate": evs["with_agents"].hit_rate},
           "decision": decision.as_dict(),
           "status": "PROPOSED" if decision.promote else "SHADOW",
           "live_effect": "none: execution still uses the production brain alone"}
    if write:
        last = next(iter(_rows(session, VERDICT_REF, 1)), None)
        memory.remember(session, "council", "council",
                        f"brain shadow verdict: {out['status']} ({decision.reason})"[:4000],
                        content=out, source_ref=VERDICT_REF)
        if decision.promote and not (last and last.content.get("status") == "PROPOSED"):
            memory.propose_learning(session, "council", {
                "change": "add the agent-ensemble veto to the production brain",
                "evidence": out}, note="passed registry.compare in shadow; needs a human")
    return out


def status(session: Session) -> dict[str, Any]:
    last = next(iter(_rows(session, VERDICT_REF, 1)), None)
    recent = [r.content | {"symbol": r.symbol} for r in _rows(session, REF, 20)]
    return {"enabled": enabled(), "latest_verdict": last.content if last else None,
            "recent": recent, "mode": "shadow_only"}
