"""Agent memory (agents stage 5): per-agent notes, council decisions,
failures, and learning records that can only be promoted by a human."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Float, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin, utcnow
from app.db.types import JSONType, TimestampType


class AgentMemoryEntry(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "agent_memory"
    __table_args__ = (Index("ix_agent_memory_agent_kind_time", "agent_id", "kind", "created_at"),)

    created_at: Mapped[datetime] = mapped_column(TimestampType, nullable=False, default=utcnow)
    agent_id: Mapped[str] = mapped_column(String(16), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    source_ref: Mapped[str] = mapped_column(String(128), nullable=False, default="")


class CouncilDecisionRecord(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "agent_council_decisions"
    __table_args__ = (Index("ix_agent_council_decisions_symbol_time", "symbol", "created_at"),)

    created_at: Mapped[datetime] = mapped_column(TimestampType, nullable=False, default=utcnow)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="shadow")
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    weights_version: Mapped[int] = mapped_column(nullable=False, default=1)
    verdict: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    opinions: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    outcome_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)


class FailureRecord(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "agent_failures"
    __table_args__ = (Index("ix_agent_failures_category_time", "category", "created_at"),)

    created_at: Mapped[datetime] = mapped_column(TimestampType, nullable=False, default=utcnow)
    agent_id: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    ref: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    details: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)


class LearningRecord(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "agent_learning_records"
    __table_args__ = (Index("ix_agent_learning_records_status", "status"),)

    created_at: Mapped[datetime] = mapped_column(TimestampType, nullable=False, default=utcnow)
    agent_id: Mapped[str] = mapped_column(String(16), nullable=False)
    change: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    evidence: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PROPOSED")
    decided_by: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    decided_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
