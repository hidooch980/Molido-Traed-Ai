"""Historical central-bank policy rates, point-in-time.

The live reader in `services.policy_rates` answers "what is the rate now" and
deliberately refuses `as_of` - a replay that quietly knows next month's rate
decision produces a strategy that cannot exist. This table is the other half:
the same BIS series stored with its observation dates, so a historical
measurement can read the rate that was actually in force at the instant being
decided on, and nothing newer.

Global, not tenant-scoped - the Federal Reserve's rate is the same fact for
every tenant.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Float, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PolicyRateObservation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One central bank's policy rate on one day, as the BIS recorded it."""

    __tablename__ = "policy_rate_observations"
    __table_args__ = (
        UniqueConstraint("currency", "observed", name="uq_policy_rate_ccy_day"),
        Index("ix_policy_rate_ccy_observed", "currency", "observed"),
    )

    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    observed: Mapped[date] = mapped_column(Date, nullable=False)
    #: Per cent per year, as published. 3.625 means 3.625% - the same unit
    #: the live reader and the carry cost model already use.
    rate: Mapped[float] = mapped_column(Float, nullable=False)
