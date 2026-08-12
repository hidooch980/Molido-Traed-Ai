"""Market data: bars and ticks.

Market data is **not** tenant-scoped. A EURUSD H1 bar from a given provider is
the same fact for every tenant, and duplicating it per tenant would multiply
storage for no isolation benefit - what is tenant-private is the *decision*
made from it, not the public price. Tenant-private broker feeds, when they
arrive in a later phase, are distinguished by `provider_id`.

Revisions are append-only. A corrected bar is inserted with `revision = n + 1`
and a later `ingested_at`; the earlier revision stays, which is what lets an
as-of read reproduce exactly what was knowable at a past timestamp.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import Timeframe
from app.db.base import Base, utcnow
from app.db.types import TimestampType, UUIDType


class Bar(Base):
    """OHLCV bar. Backed by a TimescaleDB hypertable on `event_time`."""

    __tablename__ = "ohlcv"
    __table_args__ = (
        Index("ix_ohlcv_lookup", "instrument_id", "timeframe", "event_time"),
        Index("ix_ohlcv_ingested", "ingested_at"),
    )

    # Composite key: Timescale requires the partitioning column in the key.
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("instruments.id", ondelete="CASCADE"), primary_key=True
    )
    timeframe: Mapped[Timeframe] = mapped_column(String(8), primary_key=True)
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("providers.id", ondelete="RESTRICT"), primary_key=True
    )
    event_time: Mapped[datetime] = mapped_column(TimestampType, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    ingested_at: Mapped[datetime] = mapped_column(
        TimestampType, nullable=False, default=utcnow
    )

    open: Mapped[float] = mapped_column(Numeric(20, 10), nullable=False)
    high: Mapped[float] = mapped_column(Numeric(20, 10), nullable=False)
    low: Mapped[float] = mapped_column(Numeric(20, 10), nullable=False)
    close: Mapped[float] = mapped_column(Numeric(20, 10), nullable=False)
    volume: Mapped[float | None] = mapped_column(Numeric(24, 8), nullable=True)
    tick_volume: Mapped[float | None] = mapped_column(Numeric(24, 8), nullable=True)
    spread: Mapped[float | None] = mapped_column(Numeric(20, 10), nullable=True)

    # 0..1. Written by the data-quality engine; reads below the configured
    # threshold are excluded from training datasets rather than silently used.
    quality_score: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, default=1.0)
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)


class Tick(Base):
    """Bid/ask tick. Hypertable; retained for a shorter window than bars."""

    __tablename__ = "ticks"
    __table_args__ = (Index("ix_ticks_lookup", "instrument_id", "event_time"),)

    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("instruments.id", ondelete="CASCADE"), primary_key=True
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("providers.id", ondelete="RESTRICT"), primary_key=True
    )
    event_time: Mapped[datetime] = mapped_column(TimestampType, primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, default=0)

    ingested_at: Mapped[datetime] = mapped_column(
        TimestampType, nullable=False, default=utcnow
    )
    bid: Mapped[float | None] = mapped_column(Numeric(20, 10), nullable=True)
    ask: Mapped[float | None] = mapped_column(Numeric(20, 10), nullable=True)
    last: Mapped[float | None] = mapped_column(Numeric(20, 10), nullable=True)
    volume: Mapped[float | None] = mapped_column(Numeric(24, 8), nullable=True)
    quality_score: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, default=1.0)
