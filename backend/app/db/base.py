"""Declarative base and shared column mixins."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db.types import TimestampType, UUIDType


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        TimestampType, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TimestampType, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TenantScopedMixin:
    """Every business row belongs to exactly one tenant.

    Isolation is enforced in the repository layer (`app.db.repository`), not
    only in request handlers, so background workers cannot leak across tenants.
    """

    @property
    def _tenant_fk(self) -> str:  # pragma: no cover - documentation helper
        return "tenants.id"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class ProvenanceMixin:
    """Point-in-time and provenance columns (spec §5, §6).

    `event_time`  - when the fact was true in the market.
    `ingested_at` - when we learned it. A revision backfilled later keeps its
                    original `event_time` but a newer `ingested_at`, which is
                    what makes honest as-of queries possible.
    """

    event_time: Mapped[datetime] = mapped_column(TimestampType, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        TimestampType, nullable=False, default=utcnow
    )
    revision: Mapped[int] = mapped_column(nullable=False, default=1)
