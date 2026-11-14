"""Isolated testing of council weight versions (BRAIN-01) and adaptive proposals (AI03).

`compare` replays stored, resolved council decisions under two weight versions,
in memory only: the store is never written and nothing changes live. `propose`
derives a weight change from out-of-sample member credibility and returns it as
a proposal; applying it needs a human through the learning-record flow.
"""

from __future__ import annotations

from typing import Any

from app.agents.council.analysts import Opinion
from app.agents.council.credibility import CredibilityBook, Record
from app.agents.council.meta import aggregate
from app.agents.council.weights import WeightVersion


def _opinions(raw: list[dict[str, Any]]) -> list[Opinion]:
    return [Opinion(member=o["member"], abstained=bool(o.get("abstained")),
                    score=float(o.get("score", 0.0)), confidence=float(o.get("confidence", 0.0)),
                    evidence=tuple(o.get("evidence", ())), objection=bool(o.get("objection")))
            for o in raw]


def long_r(decision: dict[str, Any]) -> float | None:
    """Recorded outcome_r is on the council's own side (memory.resolve_council); turn it
    into the R of a long. A recorded WAIT carries no side, so it cannot be replayed."""
    r = decision.get("outcome_r")
    side = decision.get("direction")
    if r is None or side not in ("BUY", "SELL"):
        return None
    return float(r) if side == "BUY" else -float(r)


def replay(decisions: list[dict[str, Any]], weights: WeightVersion) -> dict[str, Any]:
    """decisions: stored council records {"opinions", "direction", "outcome_r"}."""
    taken = []
    for d in decisions:
        r = long_r(d)
        if r is None:
            continue
        verdict = aggregate(_opinions(d["opinions"]), weights)
        if verdict.direction == "WAIT":
            continue
        taken.append(r if verdict.direction == "BUY" else -r)
    n = len(taken)
    return {"version": weights.version, "trades": n,
            "total_r": round(sum(taken), 4),
            "avg_r": round(sum(taken) / n, 4) if n else None,
            "hit_rate": round(sum(1 for r in taken if r > 0) / n, 4) if n else None}


def compare(decisions: list[dict[str, Any]], a: WeightVersion, b: WeightVersion,
            *, min_trades: int = 30) -> dict[str, Any]:
    ra, rb = replay(decisions, a), replay(decisions, b)
    enough = min(ra["trades"], rb["trades"]) >= min_trades
    better = None
    if enough and ra["avg_r"] is not None and rb["avg_r"] is not None:
        better = b.version if rb["avg_r"] > ra["avg_r"] else a.version
    return {"a": ra, "b": rb, "enough_data": enough, "better_version": better,
            "deployed": False,
            "note": "Replay on stored decisions only. Same decisions, different weights; "
                    "nothing is written or switched."}


def propose(current: WeightVersion, book: CredibilityBook, *, step: float = 0.25,
            min_n: int = 30) -> dict[str, Any] | None:
    """Move each member's weight toward its credibility factor (bounded step)."""
    stats = book.stats()
    new = dict(current.weights)
    changed = {}
    for member, w in current.weights.items():
        s = stats.get(member)
        if not s or s["n"] < min_n or w == 0:
            continue
        target = w * book.factor(member)
        proposed = round(w + step * (target - w), 4)
        if abs(proposed - w) >= 0.01:
            new[member] = proposed
            changed[member] = {"from": w, "to": proposed, "n": s["n"],
                               "avg_r": round(s["avg_r"], 4)}
    if not changed:
        return None
    return {"weights": new, "changes": changed, "based_on_version": current.version,
            "requires": "human approval via /agents/learning; replay with compare() first"}


__all__ = ["Record", "compare", "long_r", "propose", "replay"]
