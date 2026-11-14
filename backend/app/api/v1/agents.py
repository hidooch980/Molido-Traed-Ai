"""The agent layer, read-only: registry, and the gateway's state and spend.

Nothing here changes anything or reaches anything that trades.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import memory, registry
from app.agents.analyzers.bars import Candle, make_context
from app.agents.analyzers.rocket import rt10_evaluate
from app.agents.gateway import config as gateway_config
from app.agents.gateway.budget import Budget
from app.agents.gateway.ledger import since_days, today_totals, usage_summary
from app.agents.messages import Market
from app.agents.risk_gate import RiskContext, review_signal
from app.api.deps import Principal, require
from app.core.enums import AssetClass, Permission, Timeframe
from app.core.timeframes import catalogue
from app.db.session import get_db
from app.models.agent_memory import CouncilDecisionRecord, FailureRecord, LearningRecord
from app.models.instruments import Instrument
from app.services.point_in_time import get_bars

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


def _market(inst: Instrument) -> Market | None:
    if inst.asset_class == AssetClass.FOREX:
        return Market.FOREX
    if inst.asset_class == AssetClass.CRYPTO:
        return Market.CRYPTO
    if inst.asset_class == AssetClass.METAL and inst.symbol.upper().startswith("XAU"):
        return Market.GOLD
    return None


@router.get("/rocket/scan")
def rocket_scan(
    timeframe: Timeframe = Timeframe.H1,
    max_symbols: int = Query(default=30, ge=1, le=100),
    session: Session = Depends(get_db),
    _: Principal = READ,
) -> dict[str, Any]:
    """RT10 over stored bars, read at now. Every signal is PROPOSED; nothing is sent anywhere.

    Several providers can cover one instrument; the one with the most visible
    bars is used and named in the row, so the choice is visible rather than hidden.
    """
    as_of = datetime.now(UTC)
    risk_ctx = RiskContext(source="none: account state not wired (stage 9)")
    instruments = session.scalars(
        select(Instrument).where(Instrument.is_active.is_(True)).order_by(Instrument.symbol)
    ).all()
    signals: list[dict[str, Any]] = []
    scanned: list[dict[str, Any]] = []
    for inst in instruments[:max_symbols]:
        market = _market(inst)
        if market is None:
            scanned.append({"symbol": inst.symbol, "status": "skipped",
                            "reason": "market not covered (forex, gold, crypto only)"})
            continue
        bars = get_bars(session, inst.id, timeframe, as_of, lookback=600)
        by_provider: dict[Any, list[Any]] = defaultdict(list)
        for bar in bars:
            by_provider[bar.provider_id].append(bar)
        if not by_provider:
            scanned.append({"symbol": inst.symbol, "status": "no_data", "reason": "no bars"})
            continue
        provider, rows = max(by_provider.items(), key=lambda kv: len(kv[1]))
        candles = [Candle(b.event_time, b.open, b.high, b.low, b.close, b.volume) for b in rows]
        ctx = make_context(inst.symbol, market, timeframe.value, timeframe.delta, candles, as_of)
        msg, sig = rt10_evaluate(ctx)
        scanned.append({"symbol": inst.symbol, "status": "scanned", "provider_id": str(provider),
                        "bars": len(ctx.bars), "recommendation": msg.recommendation.value,
                        "reason": msg.analysis})
        if sig is not None:
            row = sig.as_dict()
            row["risk_review"] = review_signal(row, risk_ctx).as_dict()
            signals.append(row)
    signals.sort(key=lambda s: s.get("score", 0), reverse=True)
    return {
        "as_of": as_of.isoformat(),
        "timeframe": timeframe.value,
        "mode": "shadow_only",
        "signals": signals,
        "scanned": scanned,
        "note": "Deterministic, unvalidated. PROPOSED only; never submitted to risk or execution.",
    }
