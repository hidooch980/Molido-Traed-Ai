"""Every attempt to sign in, successful or not (spec §52).

Append-only, and separate from `audit_events` on purpose. The two answer
different questions and are queried differently.

`audit_events` is the record: what happened, in order, readable by a person
looking into an incident. Its payload is JSON, which is right for a record and
wrong for a decision - counting failures by address would mean filtering inside
a JSON column on the hot path of every sign-in, which no index this project can
carry portably would help with.

This table is the *decision*: three indexed columns, one count each. It is what
the guard reads before it lets a password be checked, and it is prunable -
attempts older than the longest window it consults have no effect on any
answer, so they can be deleted without losing the record, which stays in
`audit_events`.

**No password ever reaches this table, correct or not.** Not hashed, not
truncated, not its length. What is stored is the address that was tried, which
is not a secret to the person who typed it and is the only thing a lockout can
be keyed on.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin, utcnow
from app.db.types import TimestampType, UUIDType


class LoginAttempt(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "login_attempts"
    __table_args__ = (
        # The two queries the guard makes, and nothing else. Both are
        # "how many failures for this key since this instant", so both are
        # covered by a composite ending in the timestamp.
        Index("ix_login_attempts_subject", "subject", "attempted_at"),
        Index("ix_login_attempts_address", "address", "attempted_at"),
        Index("ix_login_attempts_time", "attempted_at"),
    )

    attempted_at: Mapped[datetime] = mapped_column(
        TimestampType, nullable=False, default=utcnow
    )

    #: The address that was typed, lowercased and stripped. Not a foreign key
    #: to `users`: most failed attempts name an account that does not exist,
    #: and a guard that could only count attempts against real accounts would
    #: be blind to exactly the enumeration it is there to slow down.
    subject: Mapped[str] = mapped_column(String(320), nullable=False)

    #: The caller's address as the application saw it. Nullable because a
    #: deployment behind a proxy that does not forward one leaves this empty,
    #: and an empty address must not become a shared bucket every caller in
    #: the world falls into - `login_guard` skips the address rule when it is
    #: missing rather than counting them all together.
    address: Mapped[str | None] = mapped_column(String(64), nullable=True)

    succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    #: Set only on success. What the attempt turned out to be, for the log.
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True)

    #: Why it failed, in the guard's own words - never in the user's. "wrong
    #: password" is recorded here and never returned to the caller, who is
    #: told the same thing for every kind of failure.
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)
