"""Materialized feature values (spec phase 7).

The same point-in-time discipline as market data, for the same reason: a
feature recomputed after a bar revision must not overwrite the value a past
decision actually saw. `event_time` is the bar the feature describes,
`computed_at` is when we produced it, and `feature_version` pins the maths.

Not tenant-scoped — a feature of a public bar is the same number for everyone.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import Timeframe
from app.db.base import Base, utcnow
from app.db.types import TimestampType, UUIDType


class FeatureValue(Base):
    """One feature, one instrument, one bar. Hypertable on `event_time`."""

    __tablename__ = "feature_values"
    __table_args__ = (
        Index("ix_feature_values_lookup", "instrument_id", "timeframe", "name", "event_time"),
        Index("ix_feature_values_computed", "computed_at"),
    )

    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("instruments.id", ondelete="CASCADE"), primary_key=True
    )
    timeframe: Mapped[Timeframe] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    feature_version: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    event_time: Mapped[datetime] = mapped_column(TimestampType, primary_key=True)

    computed_at: Mapped[datetime] = mapped_column(
        TimestampType, nullable=False, default=utcnow
    )
    value: Mapped[float | None] = mapped_column(Numeric(28, 12), nullable=True)

    # The bar revision the value was derived from. When a provider revises a
    # bar, the stale feature is detectable by comparison instead of silently
    # surviving as a number nobody can trace back to its input.
    source_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    quality_score: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, default=1.0)
