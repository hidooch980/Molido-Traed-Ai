"""Turn a gateway answer into an `AgentMessage`. Any doubt becomes ABSTAIN.

The model's own confidence is recorded but never trusted: the meta-brain
weighs agents by measured out-of-sample performance, not by what they say
about themselves. A language model can never say BLOCK (only CONTROL roles
can, and those are deterministic) - a BLOCK in its output is read as WAIT.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from app.agents.gateway.config import Complexity, Priority
from app.agents.gateway.gateway import AgentRequest, GatewayResult, GrokGateway
from app.agents.gateway.prompts import system_prompt
from app.agents.messages import AgentMessage, Market, Recommendation
from app.core.enums import Timeframe

ALLOWED = {"BUY", "SELL", "WAIT", "ABSTAIN"}


def _abstain(agent_id: str, market: Market, symbol: str, timeframe: Timeframe | None,
             why: str, model: str, as_of: datetime) -> AgentMessage:
    return AgentMessage(
        agent_id=agent_id, timestamp=as_of, market=market, symbol=symbol,
        timeframe=timeframe, analysis=why, evidence=[], confidence=0.0,
        risk_assessment="no model analysis available; treat as no opinion",
        recommendation=Recommendation.ABSTAIN, data_source="grok-gateway",
        model_version=model or "none",
    )


def to_message(result: GatewayResult, *, market: Market, symbol: str,
               timeframe: Timeframe | None, as_of: datetime) -> AgentMessage:
    if not result.ok:
        return _abstain(result.agent_id, market, symbol, timeframe,
                        f"gateway {result.status.value}: {result.detail}", result.model, as_of)
    try:
        data = json.loads(result.text.strip().removeprefix("```json").removesuffix("```"))
        rec = str(data.get("recommendation", "")).upper()
        if rec == "BLOCK":
            rec = "WAIT"
        if rec not in ALLOWED:
            raise ValueError("bad recommendation")
        evidence = [str(e)[:500] for e in (data.get("evidence") or [])][:20]
        if rec in {"BUY", "SELL"} and not evidence:
            rec = "WAIT"
        return AgentMessage(
            agent_id=result.agent_id, timestamp=as_of, market=market, symbol=symbol,
            timeframe=timeframe, analysis=str(data.get("analysis") or "-")[:4000],
            evidence=evidence,
            confidence=min(1.0, max(0.0, float(data.get("confidence") or 0.0))),
            risk_assessment=str(data.get("risk") or "not stated")[:2000],
            recommendation=Recommendation(rec), data_source="grok-gateway",
            model_version=result.model,
        )
    except (ValueError, TypeError, AttributeError):
        return _abstain(result.agent_id, market, symbol, timeframe,
                        "model output was not the required JSON", result.model, as_of)


async def advise(gateway: GrokGateway, agent_id: str, facts: str, *, market: Market,
                 symbol: str, timeframe: Timeframe | None = None,
                 priority: Priority = Priority.NORMAL,
                 complexity: Complexity = Complexity.STANDARD,
                 as_of: datetime | None = None) -> AgentMessage:
    request = AgentRequest(agent_id, system_prompt(agent_id), facts, priority, complexity)
    result = await gateway.ask(request)
    return to_message(result, market=market, symbol=symbol, timeframe=timeframe,
                      as_of=as_of or datetime.now(UTC))
