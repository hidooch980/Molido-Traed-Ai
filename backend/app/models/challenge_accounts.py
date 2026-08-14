"""A challenge account the holder has confirmed the rules for (spec §30).

Every transcribed rulebook carries `confirmed_by_holder: false`, and that flag
is not decoration. The numbers were read off a published page on a stated date;
a marketing page and one account's contract are not guaranteed to be the same
document, and providers change terms without reissuing the page. Only the
person who signed up can close that gap, and this table is where they close it.

An unconfirmed row is stored rather than refused. Somebody part-way through
setup has a real account with rules nobody has checked yet, and that is a state
worth recording honestly - the alternative is a row that claims confirmation it
never received.

No credentials here. A challenge account is a set of rules and a balance; the
broker login that trades it lives in MetaTrader's own config and nowhere else.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import TimestampType, UUIDType


class ChallengeAccount(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "challenge_accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "label", name="uq_challenge_accounts_tenant_label"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )

    #: What the holder calls it. Theirs to choose, because "FundedNext 100k #2"
    #: is the only name that distinguishes two accounts on the same program.
    label: Mapped[str] = mapped_column(String(120), nullable=False)

    #: Which transcribed rulebook this account is measured against, by key.
    #: A key rather than a copy of the numbers: a rulebook that drifts from the
    #: one the risk layer enforces would produce verdicts about a document
    #: nobody is trading under.
    rulebook_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)

    #: The account's own figures. Numeric rather than float: a balance is money,
    #: and money that rounds differently on two machines is money that fails a
    #: drawdown check on one of them.
    starting_balance: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)

    #: What one R is worth in account currency. Without it a drawdown allowance
    #: in money cannot become a risk figure, and every verdict blocks - which is
    #: correct, and useless.
    currency_per_r: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)

    #: The whole point of the row. False means the rules were transcribed from
    #: a public page and nobody has checked them against this contract.
    rules_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)

    #: Free text from the holder: which clause differs, what the provider said
    #: on the phone, why a number was overridden. Recorded rather than argued
    #: with, because the contract wins over the transcription every time.
    notes: Mapped[str] = mapped_column(String(2000), default="", nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
