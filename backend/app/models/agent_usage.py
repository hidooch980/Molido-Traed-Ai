"""Per-agent language-model usage: one row per gateway outcome (agents stage 3)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin, utcnow
from app.db.types import TimestampType


class AgentLlmUsage(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "agent_llm_usage"
    __table_args__ = (Index("ix_agent_llm_usage_agent_time", "agent_id", "created_at"),)

    created_at: Mapped[datetime] = mapped_column(TimestampType, nullable=False, default=utcnow)
    agent_id: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reasoning_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Null when no price is configured for the model - unknown, not zero.
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
