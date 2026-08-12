"""Market holidays and closures (spec phase 6).

Holidays are attached to a **market code** (`FX`, `XNYS`, `CME`, `CRYPTO`, …)
rather than to individual instruments: Christmas closes every US equity, and
recording it 500 times would guarantee the copies drift apart. An instrument
resolves its market through `Instrument.market_code`, and a row may still
target one instrument when a closure genuinely is instrument-specific.

Holidays are global, not tenant-scoped — a public exchange closure is the same
fact for every tenant.
"""

from __future__ import annotations

import uuid
from datetime import date, time

from sqlalchemy import Boolean, Date, ForeignKey, Index, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import HolidayKind
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UUIDType


class MarketHoliday(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "market_holidays"
    __table_args__ = (
        UniqueConstraint(
            "market_code", "instrument_id", "holiday_date", name="uq_market_holiday_day"
        ),
        Index("ix_market_holidays_lookup", "market_code", "holiday_date"),
    )

    market_code: Mapped[str] = mapped_column(String(16), nullable=False)
    # Set only when the closure applies to one instrument rather than the market.
    instrument_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("instruments.id", ondelete="CASCADE"), nullable=True
    )

    holiday_date: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[HolidayKind] = mapped_column(
        String(16), nullable=False, default=HolidayKind.CLOSED
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="")

    # Local-time bounds for a shortened or delayed session. Both null for a
    # full closure; interpreted in the instrument's timezone.
    opens_at: Mapped[time | None] = mapped_column(Time, nullable=True)
    closes_at: Mapped[time | None] = mapped_column(Time, nullable=True)

    is_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
