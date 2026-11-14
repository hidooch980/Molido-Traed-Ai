"""Run every deterministic analyzer on one context (shadow use)."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from app.agents.analyzers import ai02, extra, rocket, scalping, smc
from app.agents.analyzers.bars import AnalysisContext
from app.agents.analyzers.brain01 import brain01_message
from app.agents.analyzers.common import abstain
from app.agents.messages import AgentMessage

ANALYZERS: dict[str, Callable[[AnalysisContext], AgentMessage]] = {
    **scalping.ANALYZERS, **smc.ANALYZERS, **rocket.ANALYZERS, **extra.ANALYZERS,
    "AI02": ai02.ai02_forecast,
}


def run_timed(ctx: AnalysisContext) -> tuple[list[AgentMessage], dict[str, dict[str, Any]]]:
    """Like run_all, plus per-agent health: latency and errors.

    One analyzer raising does not stop the others; it becomes an abstention whose
    evidence names the error, and its health row says ok=False."""
    messages: list[AgentMessage] = []
    health: dict[str, dict[str, Any]] = {}
    for agent_id, fn in ANALYZERS.items():
        started = time.perf_counter()
        try:
            msg = fn(ctx)
            error = None
        except Exception as exc:  # noqa: BLE001 - isolate one agent's failure
            error = f"{type(exc).__name__}: {exc}"[:200]
            msg = abstain(agent_id, ctx, f"analyzer error: {error}")
        messages.append(msg)
        health[agent_id] = {"ok": error is None, "error": error,
                            "ms": round((time.perf_counter() - started) * 1000, 2),
                            "recommendation": msg.recommendation.value,
                            "confidence": msg.confidence}
    messages.append(brain01_message(messages, messages[0]))
    return messages, health


def run_all(ctx: AnalysisContext) -> list[AgentMessage]:
    return run_timed(ctx)[0]
