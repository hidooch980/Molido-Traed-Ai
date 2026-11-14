"""The agent layer, read-only: registry, and the gateway's state and spend.

Nothing here changes anything or reaches anything that trades.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import memory, registry
from app.agents.gateway import config as gateway_config
from app.agents.gateway.budget import Budget
from app.agents.gateway.ledger import since_days, today_totals, usage_summary
from app.api.deps import Principal, require
from app.core.enums import Permission
from app.core.timeframes import catalogue
from app.db.session import get_db
from app.models.agent_memory import CouncilDecisionRecord, FailureRecord, LearningRecord

router = APIRouter(prefix="/agents", tags=["agents"])

READ = Depends(require(Permission.READ))


@router.get("/registry")
def read_registry(_: Principal = READ) -> dict[str, Any]:
    return registry.snapshot()


@router.get("/timeframes")
def timeframes(_: Principal = READ) -> dict[str, Any]:
    """Every period with its Native/Derived label relative to the MT5 bridge."""
    return {"timeframes": catalogue()}


@router.get("/gateway")
def read_gateway(session: Session = Depends(get_db), _: Principal = READ) -> dict[str, Any]:
    """Configuration (never the key), today's budget mode from the ledger."""
    config = gateway_config.GatewayConfig.from_env()
    budget = Budget(config.daily_token_limit, config.daily_usd_limit, config.economy_at)
    tokens, usd = today_totals(session)
    budget.seed(tokens, usd)
    return {
        "enabled": gateway_config.enabled(),
        "key_env": gateway_config.API_KEY_ENV,
        "budget": budget.snapshot(),
        "config": config.public(),
        "source": "https://docs.x.ai/docs/models (checked 2026-11-14)",
    }


@router.get("/gateway/usage")
def read_gateway_usage(
    days: int = Query(default=0, ge=0, le=90, description="0 = today (UTC)"),
    session: Session = Depends(get_db),
    _: Principal = READ,
) -> dict[str, Any]:
    return usage_summary(session, since=since_days(days) if days else None)


@router.get("/memory")
def read_memory(
    agent_id: str | None = None,
    kind: str | None = None,
    symbol: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    session: Session = Depends(get_db),
    _: Principal = READ,
) -> dict[str, Any]:
    rows = memory.recall(session, agent_id=agent_id, kind=kind, symbol=symbol, limit=limit)
    return {"entries": [memory.as_dict(r) for r in rows]}


@router.get("/council/decisions")
def read_council_decisions(
    limit: int = Query(default=50, ge=1, le=500),
    session: Session = Depends(get_db),
    _: Principal = READ,
) -> dict[str, Any]:
    rows = session.scalars(
        select(CouncilDecisionRecord).order_by(CouncilDecisionRecord.created_at.desc())
        .limit(limit)
    )
    return {"mode": "shadow", "decisions": [memory.as_dict(r) for r in rows]}


@router.get("/failures")
def read_failures(
    limit: int = Query(default=50, ge=1, le=500),
    session: Session = Depends(get_db),
    _: Principal = READ,
) -> dict[str, Any]:
    rows = session.scalars(
        select(FailureRecord).order_by(FailureRecord.created_at.desc()).limit(limit)
    )
    return {"failures": [memory.as_dict(r) for r in rows]}


@router.get("/learning")
def read_learning(
    status: str | None = None,
    session: Session = Depends(get_db),
    _: Principal = READ,
) -> dict[str, Any]:
    query = select(LearningRecord).order_by(LearningRecord.created_at.desc()).limit(200)
    if status:
        query = query.where(LearningRecord.status == status)
    return {"records": [memory.as_dict(r) for r in session.scalars(query)]}
