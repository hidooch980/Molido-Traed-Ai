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

#: Which price series a decision was taken on.
#:
#: Both run in parallel. The broker's prices and the public feed's differ by
#: 33-39% of the stop distance on every major pair - measured over 490 shared
#: hourly bars - and the edge being looked for is 0.021 R. A measurement on one
#: series alone answers half the question: Yahoo has the universe the rule was
#: tested on and is a market nobody can trade in; the broker has the prices that
#: actually fill and three weeks of history.
#:
#: A column rather than a suffix on `arm`, because encoding two facts in one
#: string is how a filter meaning "the control arm" quietly starts matching
#: "control on broker prices" too.
SOURCE_PUBLIC = "yfinance"
SOURCE_BROKER = "metatrader"


class JournalEntry(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A decision, its reasoning, and how it turned out."""

    __tablename__ = "journal_entries"
    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "opened_at",
            "arm",
            "price_source",
            # Part of the key, and it has to be. Every hour the hourly,
            # fifteen, five and one minute bars close on the same timestamp;
            # without this, three of the four collide on one key at those
            # instants and are discarded as duplicates - a measurement that
            # looks like it is recording four timeframes while recording one.
            "timeframe",
            name="uq_journal_symbol_bar_arm_source_tf",
        ),
        Index("ix_journal_arm_time", "arm", "opened_at"),
        Index("ix_journal_source_arm_time", "price_source", "arm", "opened_at"),
        Index("ix_journal_timeframe_time", "timeframe", "opened_at"),
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

    #: Which timeframe the decision was taken on.
    #:
    #: Separating them is what makes measuring the fast ones safe. Spread is
    #: constant while bar range falls with the square root of time, so the same
    #: cost is a small share of an hourly bar and a large share of a one-minute
    #: one - and "no edge at one minute" is only a usable answer if it cannot
    #: leak into the hourly result.
    timeframe: Mapped[str] = mapped_column(
        String(8), default="H1", server_default="H1", nullable=False, index=True
    )
    price_source: Mapped[str] = mapped_column(
        String(24), default=SOURCE_PUBLIC, nullable=False
    )

    #: Written at different times by different events - a thesis at the open,
    #: observations while it runs, an outcome at the close. Separate columns so
    #: adding one observation does not rewrite the whole record.
    before: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    during: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
