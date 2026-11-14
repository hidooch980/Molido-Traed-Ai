"""BRAIN-01 version testing and AI03 weight proposals over stored council decisions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import memory
from app.agents.council.versions import compare, propose
from app.agents.council.weights import WeightStore, WeightVersion
from app.models.agent_memory import CouncilDecisionRecord


def decisions(session: Session, limit: int = 2000) -> list[dict[str, Any]]:
    rows = session.scalars(select(CouncilDecisionRecord)
                           .where(CouncilDecisionRecord.resolved_at.is_not(None))
                           .order_by(CouncilDecisionRecord.created_at.desc()).limit(limit))
    return [{"opinions": r.opinions or [], "direction": r.direction, "outcome_r": r.outcome_r}
            for r in rows]


def versions(session: Session, store: WeightStore | None = None, *,
             min_trades: int = 30) -> dict[str, Any]:
    store = store or WeightStore()
    current = store.current()
    book = memory.credibility_from_decisions(session)
    proposal = propose(current, book)
    stored = decisions(session)
    result: dict[str, Any] = {"current_version": current.version, "resolved_decisions": len(stored),
                              "proposal": proposal, "comparison": None, "mode": "shadow_only"}
    if proposal:
        candidate = WeightVersion(current.version + 1, proposal["weights"],
                                  "AI03 credibility proposal (not applied)", "AI03",
                                  datetime.now(UTC).isoformat())
        result["comparison"] = compare(stored, current, candidate, min_trades=min_trades)
    return result


def file_proposal(session: Session, store: WeightStore | None = None) -> Any:
    """Record the AI03 proposal as a PROPOSED learning record; a human decides."""
    report = versions(session, store)
    if not report["proposal"]:
        return None
    return memory.propose_learning(session, "AI03", {"council_weights": report["proposal"],
                                                     "replay": report["comparison"]},
                                   note="adaptive weights from out-of-sample credibility")
