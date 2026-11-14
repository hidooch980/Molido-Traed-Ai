"""BRAIN-01: evaluates the other agents' messages. Recommends no direction.

Checks: abstention rate, directional conflict, direction without evidence,
high confidence with thin evidence (overconfidence), duplicate messages, and -
when a credibility book is given - members voting against their own measured
record. Output is a WAIT message plus a structured report.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.agents.messages import AgentMessage, Recommendation

OVERCONFIDENT = 0.8


def evaluate(messages: list[AgentMessage],
             credibility: dict[str, float] | None = None) -> dict[str, Any]:
    if not messages:
        return {"messages": 0, "findings": ["no messages to evaluate"], "health": 0.0}
    findings: list[str] = []
    abstained = sum(1 for m in messages if m.recommendation is Recommendation.ABSTAIN)
    buys = [m.agent_id for m in messages if m.recommendation is Recommendation.BUY]
    sells = [m.agent_id for m in messages if m.recommendation is Recommendation.SELL]
    if buys and sells:
        findings.append(f"conflict: BUY {buys} vs SELL {sells}")
    for m in messages:
        if m.confidence >= OVERCONFIDENT and len(m.evidence) < 2:
            findings.append(f"{m.agent_id} overconfident: {m.confidence:.2f} on "
                            f"{len(m.evidence)} evidence item(s)")
    dups = [k for k, n in Counter(m.dedup_key for m in messages).items() if n > 1]
    if dups:
        findings.append(f"{len(dups)} duplicate message(s)")
    if credibility:
        weak = [m.agent_id for m in messages if credibility.get(m.agent_id, 0.5) < 0.45
                and m.recommendation in (Recommendation.BUY, Recommendation.SELL)]
        if weak:
            findings.append(f"directional calls from low-credibility agents: {weak}")
    abstain_rate = abstained / len(messages)
    if abstain_rate > 0.5:
        findings.append(f"abstention rate {abstain_rate:.0%}: data coverage is thin")
    health = max(0.0, 1.0 - 0.15 * len(findings) - 0.5 * abstain_rate)
    return {"messages": len(messages), "abstain_rate": round(abstain_rate, 3),
            "buy": buys, "sell": sells, "findings": findings, "health": round(health, 3)}


def brain01_message(messages: list[AgentMessage], ref: AgentMessage,
                    credibility: dict[str, float] | None = None) -> AgentMessage:
    report = evaluate(messages, credibility)
    return AgentMessage(
        agent_id="BRAIN-01", timestamp=ref.timestamp, market=ref.market, symbol=ref.symbol,
        timeframe=ref.timeframe, analysis=f"collective health {report['health']:.2f}",
        evidence=report["findings"][:50], confidence=0.0,
        risk_assessment="evaluation only; no trading opinion",
        recommendation=Recommendation.WAIT, data_source="agent-messages",
        model_version="deterministic-v1",
    )
