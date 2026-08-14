"""One row per recorded decision, rule or control.

`app/brain/journal.py` decides what a decision *is*; this only stores it. The
split matters: the brain module is pure and heavily tested, and giving it a
database would have meant every test of a prediction check needed a session.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Float, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import JSONType, TimestampType

#: The two arms. Stored in one table so a comparison is a filter rather than a
#: join between two shapes that can drift apart.
ARM_RULE = "rule"
ARM_CONTROL = "control"


class JournalEntry(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A decision, its reasoning, and how it turned out."""

    __tablename__ = "journal_entries"
    __table_args__ = (
        UniqueConstraint(
            "symbol", "opened_at", "arm", name="uq_journal_symbol_bar_arm"
        ),
        Index("ix_journal_arm_time", "arm", "opened_at"),
    )

    symbol: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    account_key: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(TimestampType, index=True, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)

    #: Nullable, and never defaulted. A decision that recorded no probability
    #: stored as 0.5 invents a forecast the system never made - worse than
    #: none, because it is indistinguishable from one it did.
    probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    r_multiple: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(24), index=True, nullable=True)
    arm: Mapped[str] = mapped_column(String(16), default=ARM_RULE, nullable=False)

    #: Written at different times by different events - a thesis at the open,
    #: observations while it runs, an outcome at the close. Separate columns so
    #: adding one observation does not rewrite the whole record.
    before: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    during: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
