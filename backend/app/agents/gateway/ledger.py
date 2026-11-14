"""Write gateway outcomes to `agent_llm_usage` and read them back as totals."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.agents.gateway.config import Priority
from app.agents.gateway.gateway import AgentRequest, GatewayResult
from app.models.agent_usage import AgentLlmUsage


def db_ledger(session_factory: Callable[[], Session]) -> Callable[..., None]:
    """A ledger sink for `GrokGateway(ledger=...)`. One short transaction per row."""

    def write(request: AgentRequest, result: GatewayResult, priority: Priority) -> None:
        session = session_factory()
        try:
            session.add(row_for(result, priority))
            session.commit()
        finally:
            session.close()

    return write


def row_for(result: GatewayResult, priority: Priority) -> AgentLlmUsage:
    return AgentLlmUsage(
        agent_id=result.agent_id, model=result.model, priority=priority.name,
        status=result.status.value, input_tokens=result.input_tokens,
        cached_tokens=result.cached_tokens, output_tokens=result.output_tokens,
        reasoning_tokens=result.reasoning_tokens, cost_usd=result.cost_usd,
        latency_ms=result.latency_ms, cache_hit=result.cache_hit,
        request_hash=result.request_hash,
    )


def usage_summary(session: Session, *, since: datetime | None = None) -> dict[str, Any]:
    """Per-agent totals since `since` (default: start of today, UTC)."""
    now = datetime.now(UTC)
    start = since or now.replace(hour=0, minute=0, second=0, microsecond=0)
    tokens = AgentLlmUsage.input_tokens + AgentLlmUsage.output_tokens
    rows = session.execute(
        select(
            AgentLlmUsage.agent_id,
            func.count(),
            func.sum(case((AgentLlmUsage.status == "ok", 1), else_=0)),
            func.sum(AgentLlmUsage.input_tokens),
            func.sum(AgentLlmUsage.cached_tokens),
            func.sum(AgentLlmUsage.output_tokens),
            func.sum(tokens),
            func.sum(AgentLlmUsage.cost_usd),
            func.count(AgentLlmUsage.cost_usd),
        )
        .where(AgentLlmUsage.created_at >= start)
        .group_by(AgentLlmUsage.agent_id)
        .order_by(func.sum(tokens).desc())
    ).all()
    agents = [
        {
            "agent_id": r[0], "requests": int(r[1]), "ok": int(r[2] or 0),
            "input_tokens": int(r[3] or 0), "cached_tokens": int(r[4] or 0),
            "output_tokens": int(r[5] or 0), "total_tokens": int(r[6] or 0),
            "cost_usd": float(r[7]) if r[8] else None,
            "unpriced_requests": int(r[1]) - int(r[8] or 0),
        }
        for r in rows
    ]
    priced = [a["cost_usd"] for a in agents if a["cost_usd"] is not None]
    return {
        "since": start.isoformat(),
        "until": now.isoformat(),
        "requests": sum(a["requests"] for a in agents),
        "total_tokens": sum(a["total_tokens"] for a in agents),
        "cost_usd": round(sum(priced), 6) if priced else None,
        "agents": agents,
    }


def today_totals(session: Session) -> tuple[int, float]:
    summary = usage_summary(session)
    return summary["total_tokens"], summary["cost_usd"] or 0.0


def since_days(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=max(0, days))
