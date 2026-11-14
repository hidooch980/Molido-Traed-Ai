"""The agent layer, read-only: registry, and the gateway's state and spend.

Nothing here changes anything or reaches anything that trades.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.agents import registry
from app.agents.gateway import config as gateway_config
from app.agents.gateway.budget import Budget
from app.agents.gateway.ledger import since_days, today_totals, usage_summary
from app.api.deps import Principal, require
from app.core.enums import Permission
from app.db.session import get_db

router = APIRouter(prefix="/agents", tags=["agents"])

READ = Depends(require(Permission.READ))


@router.get("/registry")
def read_registry(_: Principal = READ) -> dict[str, Any]:
    return registry.snapshot()


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
