"""Structured agent memory. Every write is traceable; nothing self-promotes.

Learning records move PROPOSED -> VALIDATED (evidence attached, e.g. a
walk-forward result) -> APPROVED or REJECTED by a named human. Approval is a
record, not a deployment: nothing here changes a running model or weight.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import registry
from app.agents.council.credibility import CredibilityBook, Record
from app.models.agent_memory import (
    AgentMemoryEntry,
    CouncilDecisionRecord,
    FailureRecord,
    LearningRecord,
)

KINDS = frozenset({
    "market", "agent", "strategy", "trade", "failure", "pattern", "news", "regime",
    "risk", "rocket", "council", "model_performance",
})
FAILURE_CATEGORIES = frozenset({
    "wrong_signal", "false_breakout", "late_entry", "early_exit", "regime_shift",
    "data_error", "reasoning_error", "council_disagreement", "execution", "other",
})
COUNCIL_MEMBER_IDS = frozenset({"council"})


def _agent(agent_id: str) -> str:
    if agent_id in COUNCIL_MEMBER_IDS or registry.get(agent_id) is not None:
        return agent_id
    raise ValueError(f"unknown agent id {agent_id!r}")


def remember(session: Session, agent_id: str, kind: str, summary: str, *,
             content: dict[str, Any] | None = None, symbol: str = "",
             source_ref: str = "") -> AgentMemoryEntry:
    if kind not in KINDS:
        raise ValueError(f"unknown memory kind {kind!r}")
    if not summary.strip():
        raise ValueError("a memory needs a summary")
    row = AgentMemoryEntry(agent_id=_agent(agent_id), kind=kind, summary=summary[:4000],
                           content=content or {}, symbol=symbol.upper(),
                           source_ref=source_ref)
    session.add(row)
    session.flush()
    return row


def recall(session: Session, *, agent_id: str | None = None, kind: str | None = None,
           symbol: str | None = None, limit: int = 50) -> list[AgentMemoryEntry]:
    query = select(AgentMemoryEntry).order_by(AgentMemoryEntry.created_at.desc())
    if agent_id:
        query = query.where(AgentMemoryEntry.agent_id == agent_id)
    if kind:
        query = query.where(AgentMemoryEntry.kind == kind)
    if symbol:
        query = query.where(AgentMemoryEntry.symbol == symbol.upper())
    return list(session.scalars(query.limit(max(1, min(500, limit)))))


def record_council(session: Session, shadow: dict[str, Any]) -> CouncilDecisionRecord:
    verdict = shadow.get("verdict") or {}
    row = CouncilDecisionRecord(
        symbol=str(shadow.get("symbol") or ""), timeframe=str(shadow.get("timeframe") or ""),
        mode=str(shadow.get("mode") or "shadow"), direction=str(verdict.get("direction")),
        score=float(verdict.get("score") or 0.0),
        weights_version=int(verdict.get("weights_version") or 1), verdict=verdict,
        opinions=list(shadow.get("opinions") or []),
    )
    session.add(row)
    session.flush()
    return row


def resolve_council(session: Session, decision_id: uuid.UUID, outcome_r: float) -> None:
    """Attach the realised outcome (in R, after costs) once, never overwrite."""
    row = session.get(CouncilDecisionRecord, decision_id)
    if row is None:
        raise KeyError(decision_id)
    if row.resolved_at is not None:
        raise ValueError("decision already resolved")
    row.outcome_r, row.resolved_at = float(outcome_r), datetime.now(UTC)
    session.flush()


def credibility_from_decisions(session: Session) -> CredibilityBook:
    """Shadow decisions are forward-recorded, so their outcomes are out of sample."""
    book = CredibilityBook()
    rows = session.scalars(select(CouncilDecisionRecord)
                           .where(CouncilDecisionRecord.resolved_at.is_not(None)))
    for row in rows:
        for opinion in row.opinions or []:
            direction = opinion.get("direction")
            if opinion.get("abstained") or direction not in ("BUY", "SELL"):
                continue
            sign = 1.0 if direction == "BUY" else -1.0
            # outcome_r is measured on the council's own side; re-sign per member.
            council_sign = 1.0 if row.direction == "BUY" else -1.0 if row.direction == "SELL" \
                else 0.0
            if council_sign == 0.0:
                continue
            book.add(Record(str(opinion.get("member")), direction,
                            float(row.outcome_r or 0.0) * sign * council_sign, True))
    return book


def record_failure(session: Session, category: str, description: str, *,
                   agent_id: str = "", ref: str = "",
                   details: dict[str, Any] | None = None) -> FailureRecord:
    if category not in FAILURE_CATEGORIES:
        raise ValueError(f"unknown failure category {category!r}")
    row = FailureRecord(agent_id=_agent(agent_id) if agent_id else "", category=category,
                        description=description[:4000], ref=ref, details=details or {})
    session.add(row)
    session.flush()
    return row


def propose_learning(session: Session, agent_id: str, change: dict[str, Any],
                     *, note: str = "") -> LearningRecord:
    row = LearningRecord(agent_id=_agent(agent_id), change=change, evidence={},
                         status="PROPOSED", note=note)
    session.add(row)
    session.flush()
    return row


def validate_learning(session: Session, record_id: uuid.UUID,
                      evidence: dict[str, Any]) -> LearningRecord:
    row = _learning(session, record_id)
    if row.status != "PROPOSED":
        raise ValueError(f"cannot validate a {row.status} record")
    required = {"method", "out_of_sample", "result"}
    if not required <= set(evidence) or evidence.get("out_of_sample") is not True:
        raise ValueError("validation needs method, out_of_sample=True and result")
    row.evidence, row.status = evidence, "VALIDATED"
    session.flush()
    return row


def decide_learning(session: Session, record_id: uuid.UUID, *, approve: bool,
                    decided_by: str) -> LearningRecord:
    """A human decision. Approval records consent; it deploys nothing."""
    row = _learning(session, record_id)
    if not decided_by.strip():
        raise ValueError("a decision needs the name of the person making it")
    if approve and row.status != "VALIDATED":
        raise ValueError("only a VALIDATED record can be approved")
    if row.status in ("APPROVED", "REJECTED"):
        raise ValueError("already decided")
    row.status = "APPROVED" if approve else "REJECTED"
    row.decided_by, row.decided_at = decided_by.strip(), datetime.now(UTC)
    session.flush()
    return row


def _learning(session: Session, record_id: uuid.UUID) -> LearningRecord:
    row = session.get(LearningRecord, record_id)
    if row is None:
        raise KeyError(record_id)
    return row


def as_dict(row: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name)
        out[column.name] = value.isoformat() if isinstance(value, datetime) else (
            str(value) if isinstance(value, uuid.UUID) else value)
    return out
