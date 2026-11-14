"""The standard message every agent will speak (stage 1: schema only).

Each message carries its own unique id and a deterministic `dedup_key`, so a
consumer can drop a repeat of the same reading without trusting delivery to be
exactly-once. Timestamps must be timezone-aware and are normalised to UTC; a
naive time is refused rather than guessed.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agents import registry
from app.core.enums import Timeframe


class Market(StrEnum):
    FOREX = "forex"
    GOLD = "gold"
    CRYPTO = "crypto"


class Recommendation(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    WAIT = "WAIT"
    ABSTAIN = "ABSTAIN"
    #: Only a role at L4 (CONTROL) may say BLOCK.
    BLOCK = "BLOCK"


class AgentMessage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    message_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    agent_id: str
    timestamp: datetime
    market: Market
    symbol: str = Field(min_length=1, max_length=32)
    timeframe: Timeframe | None = None
    analysis: str = Field(min_length=1, max_length=4000)
    evidence: list[str] = Field(default_factory=list, max_length=50)
    confidence: float = Field(ge=0.0, le=1.0)
    risk_assessment: str = Field(min_length=1, max_length=2000)
    recommendation: Recommendation
    data_source: str = Field(min_length=1, max_length=200)
    model_version: str = Field(min_length=1, max_length=100)
    in_reply_to: uuid.UUID | None = None

    @field_validator("agent_id")
    @classmethod
    def _known_agent(cls, value: str) -> str:
        if registry.get(value) is None:
            raise ValueError(f"unknown agent id {value!r}")
        return value

    @field_validator("timestamp")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _rules(self) -> AgentMessage:
        role = registry.get(self.agent_id)
        assert role is not None  # checked by the field validator
        directional = self.recommendation in (Recommendation.BUY, Recommendation.SELL)
        if directional and not self.evidence:
            raise ValueError("a BUY or SELL recommendation must carry evidence")
        if self.recommendation is Recommendation.BLOCK and int(role.permission_level) < 4:
            raise ValueError(f"{role.id} is not a CONTROL role and cannot BLOCK")
        return self

    @property
    def dedup_key(self) -> str:
        """Same agent, symbol, timeframe, instant and call -> same key."""
        parts = (
            self.agent_id,
            self.market.value,
            self.symbol.upper(),
            self.timeframe.value if self.timeframe else "-",
            self.timestamp.isoformat(),
            self.recommendation.value,
            self.model_version,
        )
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
