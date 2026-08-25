"""One issued proof-of-work challenge, and whether it has been spent.

The table exists for one property that cannot be had without it: **a solution
may be used once**. A stateless signed challenge would be cheaper and would
fail at exactly the thing this is for - an attacker solves one, then replays
the same solution on every request until it expires, and a two-minute expiry
becomes two minutes of unimpeded guessing.

So each challenge is a row, and verifying deletes it. Rows are small,
short-lived and pruned by age.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin, utcnow
from app.db.types import TimestampType


class HumanChallenge(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "human_challenges"
    __table_args__ = (Index("ix_human_challenges_expiry", "expires_at"),)

    issued_at: Mapped[datetime] = mapped_column(
        TimestampType, nullable=False, default=utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(TimestampType, nullable=False)

    #: The random string the client hashes against. Not secret - the client
    #: needs it - and not reusable, because the row is deleted on the first
    #: successful verification.
    salt: Mapped[str] = mapped_column(String(64), nullable=False)

    #: Leading zero bits required of the digest. Stored per challenge rather
    #: than read from configuration at verify time: a challenge issued at one
    #: difficulty must be checked at that difficulty, or raising the setting
    #: would invalidate every challenge already in flight.
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False)

    #: What this challenge was issued for, so a proof solved for the sign-in
    #: form cannot be spent on the registration form. Free text rather than an
    #: enum: the binding only has to be consistent between issue and verify.
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
