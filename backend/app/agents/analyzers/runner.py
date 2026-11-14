"""Run every deterministic analyzer on one context (shadow use)."""

from __future__ import annotations

from collections.abc import Callable

from app.agents.analyzers import ai02, rocket, scalping, smc
from app.agents.analyzers.bars import AnalysisContext
from app.agents.analyzers.brain01 import brain01_message
from app.agents.messages import AgentMessage

ANALYZERS: dict[str, Callable[[AnalysisContext], AgentMessage]] = {
    **scalping.ANALYZERS, **smc.ANALYZERS, **rocket.ANALYZERS, "AI02": ai02.ai02_forecast,
}


def run_all(ctx: AnalysisContext) -> list[AgentMessage]:
    messages = [fn(ctx) for fn in ANALYZERS.values()]
    return [*messages, brain01_message(messages, messages[0])]
