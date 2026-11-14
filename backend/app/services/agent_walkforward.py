"""Rocket signals kept in agent memory, and their forward outcomes."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import memory
from app.agents.analyzers.rocket import RocketSignal, evaluate_outcome
from app.agents.walkforward import stats, walk_forward
from app.core.enums import Timeframe
from app.models.instruments import Instrument
from app.services import agent_scan


def _ref(sig: dict[str, Any]) -> str:
    key = f"{sig['symbol']}|{sig['timeframe']}|{sig['signal_timestamp']}"
    return "rocket:" + hashlib.sha256(key.encode()).hexdigest()[:24]


def record_signals(session: Session, scan: dict[str, Any]) -> int:
    """Store each proposed signal once (memory kind=rocket)."""
    known = {r.source_ref for r in memory.recall(session, kind="rocket", limit=500)}
    added = 0
    for sig in scan.get("signals", []):
        ref = _ref(sig)
        if ref in known:
            continue
        memory.remember(session, "RT10", "rocket",
                        f"{sig['rocket_rank']} {sig['direction']} {sig['symbol']} "
                        f"{sig['timeframe']} (PROPOSED)", symbol=sig["symbol"],
                        source_ref=ref, content={"event": "signal", **sig})
        added += 1
    return added


def resolve_recorded(session: Session, *, now: datetime | None = None) -> int:
    """Resolve stored signals on bars that closed after them; each is resolved once."""
    now = now or datetime.now(UTC)
    rows = memory.recall(session, kind="rocket", limit=500)
    done = {r.source_ref for r in rows if r.content.get("event") == "outcome"}
    resolved = 0
    for row in rows:
        sig = row.content
        if sig.get("event") != "signal" or row.source_ref in done:
            continue
        inst = session.scalar(select(Instrument).where(Instrument.symbol == sig["symbol"]))
        if inst is None:
            continue
        tf = Timeframe(sig["timeframe"])
        _, bars = agent_scan.candles(session, inst, tf, now)
        at = datetime.fromisoformat(sig["signal_timestamp"])
        later = [b for b in bars if b.open_time >= at and b.open_time + tf.delta <= now]
        fields = {k: sig[k] for k in RocketSignal.__dataclass_fields__ if k in sig}
        fields["entry_zone"] = tuple(fields["entry_zone"])
        out = evaluate_outcome(RocketSignal(**fields), later)
        if out["result"] in ("stop", "target"):
            memory.remember(session, "RT10", "rocket", f"outcome {sig['symbol']} {out['result']}",
                            symbol=sig["symbol"], source_ref=row.source_ref,
                            content={"event": "outcome", "rank": sig.get("rocket_rank"), **out})
            resolved += 1
    return resolved


def forward_summary(session: Session) -> dict[str, Any]:
    rows = memory.recall(session, kind="rocket", limit=500)
    outcomes = [r.content for r in rows if r.content.get("event") == "outcome"]
    signals = [r for r in rows if r.content.get("event") == "signal"]
    rs = [float(o["r"]) for o in outcomes if "r" in o]
    return {
        "recorded": len(signals), "resolved": len(outcomes), "overall": stats(rs),
        "by_rank": {k: stats([float(o["r"]) for o in outcomes if o.get("rank") == k and "r" in o])
                    for k in ("R1", "R2", "R3", "R4", "R5")},
        "signals": [memory.as_dict(r) for r in signals[:100]],
    }


def historical(session: Session, symbol: str, timeframe: Timeframe, *, folds: int = 4,
               lookback: int = 2000) -> dict[str, Any]:
    inst = session.scalar(select(Instrument).where(Instrument.symbol == symbol.upper()))
    if inst is None:
        return {"symbol": symbol, "error": "unknown instrument"}
    market = agent_scan.market_of(inst)
    if market is None:
        return {"symbol": symbol, "error": "market not covered"}
    provider, bars = agent_scan.candles(session, inst, timeframe, datetime.now(UTC),
                                        lookback=lookback)
    out = walk_forward(bars, inst.symbol, market, timeframe.value, timeframe.delta, folds=folds)
    out["provider_id"] = provider
    return out
