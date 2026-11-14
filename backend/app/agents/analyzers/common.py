"""Shared helpers to build messages consistently."""

from __future__ import annotations

from app.agents.analyzers.bars import AnalysisContext
from app.agents.messages import AgentMessage, Recommendation
from app.core.enums import Timeframe

MODEL_VERSION = "deterministic-v1"


def message(agent_id: str, ctx: AnalysisContext, rec: Recommendation, confidence: float,
            analysis: str, evidence: list[str], risk: str = "not assessed here; risk brain decides",
            ) -> AgentMessage:
    if rec in (Recommendation.BUY, Recommendation.SELL) and not evidence:
        rec = Recommendation.WAIT
    return AgentMessage(
        agent_id=agent_id, timestamp=ctx.as_of, market=ctx.market, symbol=ctx.symbol,
        timeframe=Timeframe(ctx.timeframe) if ctx.timeframe in _TF else None, analysis=analysis,
        evidence=evidence, confidence=max(0.0, min(1.0, confidence)), risk_assessment=risk,
        recommendation=rec, data_source=ctx.source, model_version=MODEL_VERSION,
    )


def abstain(agent_id: str, ctx: AnalysisContext, why: str) -> AgentMessage:
    return message(agent_id, ctx, Recommendation.ABSTAIN, 0.0, why, [])


def direction(score: float, band: float = 0.15) -> Recommendation:
    if abs(score) < band:
        return Recommendation.WAIT
    return Recommendation.BUY if score > 0 else Recommendation.SELL


_TF = frozenset(t.value for t in Timeframe)
