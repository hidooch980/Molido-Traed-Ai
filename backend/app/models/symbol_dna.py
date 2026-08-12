"""Symbol DNA — the stored behavioural profile of an instrument (spec §7).

One row per (instrument, timeframe, profile kind, version), holding the
computed profile as JSON plus the provenance needed to trust it: the knowledge
cutoff it was computed at, how many samples went into it, and when it was
produced.

The sample count is not decoration. A volatility percentile from 80 bars and
one from 80,000 are different claims, and a consumer that cannot tell them
apart will treat a guess as a measurement.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import Timeframe
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow
from app.db.types import JSONType, TimestampType, UUIDType


class SymbolProfile(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "symbol_profiles"
    __table_args__ = (
        Index("ix_symbol_profiles_lookup", "instrument_id", "timeframe", "kind", "as_of"),
    )

    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    timeframe: Mapped[Timeframe] = mapped_column(String(8), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Knowledge cutoff the profile describes. Two profiles for the same
    # instrument at different as_of values are both correct and both kept —
    # that is how a regime shift becomes visible instead of being overwritten.
    as_of: Mapped[datetime] = mapped_column(TimestampType, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        TimestampType, nullable=False, default=utcnow
    )

    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coverage_start: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    coverage_end: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)

    data: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
