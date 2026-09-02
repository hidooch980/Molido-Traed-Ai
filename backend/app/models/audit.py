"""Structured audit / observability events (spec §66).

Append-only. Payloads are metadata about what happened - never secrets, never
credentials, never raw broker responses containing account identifiers.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import Severity
from app.db.base import Base, UUIDPrimaryKeyMixin, utcnow
from app.db.types import JSONType, TimestampType, UUIDType


class AuditEvent(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_time", "occurred_at"),
        Index("ix_audit_events_type", "event_type", "occurred_at"),
        Index("ix_audit_events_tenant", "tenant_id", "occurred_at"),
    )

    occurred_at: Mapped[datetime] = mapped_column(
        TimestampType, nullable=False, default=utcnow
    )
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True)
    account_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True)

    service: Mapped[str] = mapped_column(String(64), nullable=False, default="backend")
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[Severity] = mapped_column(String(16), default=Severity.INFO, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # The chain (migration 0021). NULL on rows written before it existed;
    # those are counted as pre-chain and never rewritten.
    sequence: Mapped[int | None] = mapped_column(BigInteger, nullable=True, unique=True)
    previous_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entry_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AuditChainHead(Base):
    """The one row every append locks: the last sequence and its hash.

    A chain with three writers and no serialisation forks, and a forked chain
    verifies as broken through nobody's fault. Locking this row inside the
    writer's transaction is what keeps the sequence a sequence.
    """

    __tablename__ = "audit_chain_head"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False)
