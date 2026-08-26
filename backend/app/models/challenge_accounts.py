"""An account the holder trades, and the rules it is measured against (spec §30).

Every transcribed rulebook carries `confirmed_by_holder: false`, and that flag
is not decoration. The numbers were read off a published page on a stated date;
a marketing page and one account's contract are not guaranteed to be the same
document, and providers change terms without reissuing the page. Only the
person who signed up can close that gap, and this table is where they close it.

An unconfirmed row is stored rather than refused. Somebody part-way through
setup has a real account with rules nobody has checked yet, and that is a state
worth recording honestly - the alternative is a row that claims confirmation it
never received.

Three kinds of account live here and they differ in who imposes the limits.
A challenge and a funded account are measured against a rulebook somebody else
wrote; a live account is the holder's own money, where nothing external ends it
and there is no rulebook to point at. That is why `rulebook_key` is nullable -
not because it is optional on a prop account, but because requiring one on a
live account would have forced every holder of an ordinary broker account to
name a prop programme they are not on.

No credentials here. An account is a set of rules and a balance; the broker
login that trades it lives in MetaTrader's own config and nowhere else.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import AccountKind
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

    #: Which of the three this is: a challenge being sat, a funded prop
    #: account, or the holder's own live account. Stored as text rather than a
    #: database enum so that adding a fourth kind is a migration of one column
    #: default instead of an ALTER TYPE that locks the table.
    kind: Mapped[str] = mapped_column(
        String(16), default=AccountKind.CHALLENGE.value, nullable=False, index=True
    )

    #: Which transcribed rulebook this account is measured against, by key.
    #: A key rather than a copy of the numbers: a rulebook that drifts from the
    #: one the risk layer enforces would produce verdicts about a document
    #: nobody is trading under.
    #:
    #: Null on a live account and only on a live account. The service refuses a
    #: prop account without one, so a null here is a statement that nobody
    #: outside this deployment sets the account's limits - never a missing
    #: entry somebody forgot.
    rulebook_key: Mapped[str | None] = mapped_column(
        String(80), nullable=True, index=True
    )

    #: The account's own figures. Numeric rather than float: a balance is money,
    #: and money that rounds differently on two machines is money that fails a
    #: drawdown check on one of them.
    #:
    #: Annotated `Decimal` to match, which it was not - the column has always
    #: handed back a Decimal and the annotation said float, so the one thing
    #: this comment insists on was the one thing the type did not say.
    starting_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)

    #: What one R is worth in account currency. Without it a drawdown allowance
    #: in money cannot become a risk figure, and every verdict blocks - which is
    #: correct, and useless.
    currency_per_r: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)

    #: The whole point of the row. False means the rules were transcribed from
    #: a public page and nobody has checked them against this contract.
    rules_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)

    #: Free text from the holder: which clause differs, what the provider said
    #: on the phone, why a number was overridden. Recorded rather than argued
    #: with, because the contract wins over the transcription every time.
    notes: Mapped[str] = mapped_column(String(2000), default="", nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
