"""RT10 over stored bars at one instant, reviewed by the agent risk gate (shadow)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.analyzers.bars import Candle, make_context
from app.agents.analyzers.rocket import rt10_evaluate
from app.agents.messages import Market
from app.agents.risk_gate import RiskContext, review_signal
from app.core.enums import AssetClass, Timeframe
from app.models.instruments import Instrument
from app.services.agent_events import news_soon
from app.services.point_in_time import get_bars


def market_of(inst: Instrument) -> Market | None:
    if inst.asset_class == AssetClass.FOREX:
        return Market.FOREX
    if inst.asset_class == AssetClass.CRYPTO:
        return Market.CRYPTO
    if inst.asset_class == AssetClass.METAL and inst.symbol.upper().startswith("XAU"):
        return Market.GOLD
    return None


def candles(session: Session, inst: Instrument, timeframe: Timeframe, as_of: datetime,
            lookback: int = 600) -> tuple[str | None, list[Candle]]:
    """Bars from the provider with the most visible bars; the choice is returned."""
    by_provider: dict[Any, list[Any]] = defaultdict(list)
    for bar in get_bars(session, inst.id, timeframe, as_of, lookback=lookback):
        by_provider[bar.provider_id].append(bar)
    if not by_provider:
        return None, []
    provider, rows = max(by_provider.items(), key=lambda kv: len(kv[1]))
    return str(provider), [Candle(b.event_time, b.open, b.high, b.low, b.close, b.volume)
                           for b in rows]


def scan(session: Session, timeframe: Timeframe, *, max_symbols: int = 30,
         risk_ctx: RiskContext | None = None, as_of: datetime | None = None,
         symbols: list[str] | None = None,
         events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """`events` None means the calendar is unknown: RT06 abstains, no news penalty."""
    as_of = as_of or datetime.now(UTC)
    risk_ctx = risk_ctx or RiskContext(source="none")
    instruments = session.scalars(
        select(Instrument).where(Instrument.is_active.is_(True)).order_by(Instrument.symbol)
    ).all()
    if symbols is not None:
        wanted = set(symbols)
        instruments = [i for i in instruments if i.symbol in wanted]
    signals: list[dict[str, Any]] = []
    scanned: list[dict[str, Any]] = []
    for inst in instruments[:max_symbols]:
        market = market_of(inst)
        if market is None:
            scanned.append({"symbol": inst.symbol, "status": "skipped",
                            "reason": "market not covered (forex, gold, crypto only)"})
            continue
        provider, bars = candles(session, inst, timeframe, as_of)
        if not bars:
            scanned.append({"symbol": inst.symbol, "status": "no_data", "reason": "no bars"})
            continue
        extras: dict[str, Any] = {} if events is None else {"events": events}
        ctx = make_context(inst.symbol, market, timeframe.value, timeframe.delta, bars, as_of,
                           extras=extras)
        msg, sig = rt10_evaluate(ctx)
        scanned.append({"symbol": inst.symbol, "status": "scanned", "provider_id": provider,
                        "bars": len(ctx.bars), "recommendation": msg.recommendation.value,
                        "reason": msg.analysis})
        if sig is not None:
            row = sig.as_dict()
            soon = bool(news_soon(events, inst.symbol, as_of)) or risk_ctx.high_impact_news_soon
            sym_ctx = replace(risk_ctx, high_impact_news_soon=soon)
            row["risk_review"] = review_signal(row, sym_ctx).as_dict()
            signals.append(row)
    signals.sort(key=lambda s: s.get("score", 0), reverse=True)
    return {
        "as_of": as_of.isoformat(),
        "timeframe": timeframe.value,
        "mode": "shadow_only",
        "risk_context_source": risk_ctx.source,
        "calendar": "unknown (feed off or failed)" if events is None else f"{len(events)} events",
        "signals": signals,
        "scanned": scanned,
        "note": "Deterministic, unvalidated. PROPOSED only; never submitted to risk or execution.",
    }
