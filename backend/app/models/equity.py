"""One row per equity snapshot, so a trailing floor has a series to trail."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import TimestampType


class EquitySample(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """What the account was worth at one instant, as the terminal reported it.

    Both equity and balance are kept. FTMO's floor trails "the highest account
    balance achieved at 00:00 CE(S)T of any preceding trading day", while the
    live picture needs equity - and neither derives from the other after the
    fact. Keeping one would mean re-reading the provider's terms later and
    discovering the wrong column was stored.
    """

    __tablename__ = "equity_samples"
    __table_args__ = (
        UniqueConstraint(
            "account_key", "recorded_at", name="uq_equity_samples_account_instant"
        ),
        Index("ix_equity_samples_account_time", "account_key", "recorded_at"),
    )

    #: The broker login as a string. Deliberately not a foreign key: an account
    #: publishes long before anybody registers it as a challenge, and losing
    #: those samples would leave a gap exactly where the account was newest.
    account_key: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    #: When the snapshot was taken, not when it was written. Those diverge when
    #: the writer falls behind, and a peak attributed to the wrong minute puts
    #: the floor in the wrong place on the day it matters.
    recorded_at: Mapped[datetime] = mapped_column(TimestampType, index=True, nullable=False)
    equity: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    balance: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    margin: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    open_positions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
