"""Read-only signal adapter. Off by default. Never overrides Risk Brain.

Existing components may call `read_only_input` and treat the snapshot as one
more input. This module does not import or call the risk gate, does not mutate
a RiskDecision, and does not register a new analyzer in the 51-agent runner.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.agents.analyzers.bars import Candle
from app.agents.pro_btb.engine import ProBtbEngine
from app.agents.pro_btb.params import ProBtbParams
from app.agents.pro_btb.types import DecisionTrace

# Canonical consumer ids for the components named in the specification.
CONSUMERS: frozenset[str] = frozenset({
    "rocket_trade_hunter",
    "hybrid_ai_brain",
    "market_key_levels",
    "sp2l",
    "spike_and_imbalance",
    "multi_timeframe",
    "ai_validation_scoring",
    "adaptive_risk",
})

ENV_FLAG = "MOLIDO_PRO_BTB_ENABLED"
# Keys that belong to Risk Brain / the agent risk gate. The merge helper
# copies them through unchanged and never writes them.
_RISK_KEYS = frozenset({
    "risk_decision", "risk_verdict", "risk_brain", "risk_approval_status",
    "risk_gate", "verdict",
})


def is_enabled(getenv=os.getenv) -> bool:
    raw = (getenv(ENV_FLAG) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ProBtbInput:
    """Frozen, read-only payload a consumer may attach to its extras."""

    enabled: bool
    consumer: str
    trace: DecisionTrace | None
    may_override_risk_brain: bool = False  # always False; part of the contract

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "consumer": self.consumer,
            "trace": None if self.trace is None else self.trace.as_dict(),
            "may_override_risk_brain": False,
            "source": "pro_btb.read_only",
        }


def read_only_input(
    consumer: str,
    bars: Sequence[Candle],
    *,
    as_of: datetime,
    symbol: str = "UNKNOWN",
    timeframe: str = "H1",
    enabled: bool | None = None,
    params: ProBtbParams | None = None,
) -> ProBtbInput:
    if consumer not in CONSUMERS:
        raise ValueError(f"unknown Pro BTB consumer: {consumer}")
    if enabled is None:
        enabled = is_enabled()
    if not enabled:
        return ProBtbInput(
            enabled=False, consumer=consumer, trace=None, may_override_risk_brain=False,
        )
    trace = ProBtbEngine(params).run(bars, as_of=as_of, symbol=symbol, timeframe=timeframe)
    return ProBtbInput(enabled=True, consumer=consumer, trace=trace, may_override_risk_brain=False)


def merge_into_extras(extras: Mapping[str, Any] | None, payload: ProBtbInput) -> dict[str, Any]:
    """Return a new extras dict. Risk-related keys are copied, never rewritten."""
    out = dict(extras or {})
    reserved = {k: out[k] for k in _RISK_KEYS if k in out}
    if payload.enabled:
        out["pro_btb"] = payload.as_dict()
    else:
        out["pro_btb"] = {"enabled": False, "consumer": payload.consumer,
                          "trace": None, "may_override_risk_brain": False,
                          "source": "pro_btb.read_only"}
    out.update(reserved)
    return out
