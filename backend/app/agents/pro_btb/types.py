"""Shared value types for the Pro BTB engine. Pure data, no I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.agents.analyzers.bars import Candle
from app.agents.pro_btb.status import RuleStatus


class Direction(StrEnum):
    BULL = "bull"
    BEAR = "bear"
    NONE = "none"


class CycleLabel(StrEnum):
    SPIKE = "SP"
    CHANNEL = "CH"
    TRADING_RANGE = "TR"
    UNKNOWN = "UNKNOWN"


class BreakEvenKind(StrEnum):
    LEG1_START = "leg1_start"
    LEG2_START = "leg2_start"
    SPIKE_TOP = "spike_top"
    CHANNEL_TOP = "channel_top"


class PipelineDecision(StrEnum):
    STOP = "STOP"
    WAIT = "WAIT"
    CONTINUE = "CONTINUE"


@dataclass(frozen=True)
class PriceRange:
    """A BTB (or any) zone stored as a closed price interval."""

    low: float
    high: float
    rule_id: str
    rule_status: RuleStatus

    def __post_init__(self) -> None:
        if self.high < self.low:
            raise ValueError("PriceRange high must be >= low")

    def contains(self, price: float) -> bool:
        return self.low <= price <= self.high

    def intersects(self, low: float, high: float) -> bool:
        return not (high < self.low or low > self.high)

    def width(self) -> float:
        return self.high - self.low

    def as_dict(self) -> dict[str, Any]:
        return {
            "low": self.low,
            "high": self.high,
            "rule_id": self.rule_id,
            "rule_status": self.rule_status.value,
        }


@dataclass(frozen=True)
class BreakEvenZone:
    kind: BreakEvenKind
    present: bool
    price: float | None
    bar_index: int | None
    reasons: tuple[str, ...]
    rule_id: str
    rule_status: RuleStatus

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "present": self.present,
            "price": self.price,
            "bar_index": self.bar_index,
            "reasons": list(self.reasons),
            "rule_id": self.rule_id,
            "rule_status": self.rule_status.value,
        }


@dataclass(frozen=True)
class ZoneComparison:
    left: BreakEvenKind
    right: BreakEvenKind
    delta: float  # right.price - left.price

    def as_dict(self) -> dict[str, Any]:
        return {"left": self.left.value, "right": self.right.value, "delta": self.delta}


@dataclass(frozen=True)
class StageSnapshot:
    stage: str
    valid: bool
    decision: PipelineDecision
    reasons: tuple[str, ...]
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "valid": self.valid,
            "decision": self.decision.value,
            "reasons": list(self.reasons),
            "details": self.details,
        }


@dataclass(frozen=True)
class DecisionTrace:
    """Auditable record of one Pro BTB run. Safe to log; no secrets."""

    symbol: str
    timeframe: str
    as_of: datetime
    direction: Direction
    decision: PipelineDecision
    stages: tuple[StageSnapshot, ...]
    btb_zone: PriceRange | None
    break_even_zones: tuple[BreakEvenZone, ...]
    zone_comparisons: tuple[ZoneComparison, ...]
    confirmation_accepted: bool
    confirmation_reason: str
    entry_action: str
    entry_reason: str
    risk_reward: float | None
    invalidation: float | None
    risk_flags: tuple[str, ...]
    rule_statuses: dict[str, str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "as_of": self.as_of.isoformat(),
            "direction": self.direction.value,
            "decision": self.decision.value,
            "stages": [s.as_dict() for s in self.stages],
            "btb_zone": None if self.btb_zone is None else self.btb_zone.as_dict(),
            "break_even_zones": [z.as_dict() for z in self.break_even_zones],
            "zone_comparisons": [c.as_dict() for c in self.zone_comparisons],
            "confirmation_accepted": self.confirmation_accepted,
            "confirmation_reason": self.confirmation_reason,
            "entry_action": self.entry_action,
            "entry_reason": self.entry_reason,
            "risk_reward": self.risk_reward,
            "invalidation": self.invalidation,
            "risk_flags": list(self.risk_flags),
            "rule_statuses": dict(self.rule_statuses),
        }


# Re-export so stage modules can type against one place.
Bar = Candle
__all__ = [
    "Bar",
    "BreakEvenKind",
    "BreakEvenZone",
    "CycleLabel",
    "DecisionTrace",
    "Direction",
    "PipelineDecision",
    "PriceRange",
    "StageSnapshot",
    "ZoneComparison",
]
