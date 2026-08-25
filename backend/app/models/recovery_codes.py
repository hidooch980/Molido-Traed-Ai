"""The way back in when the phone is gone (spec §52).

A second factor that cannot be recovered is a way to lose an account, and on
this system losing the account means losing the dashboard the kill switch is
reached from. A dropped phone must not be able to strand somebody outside their
own halt button.

So enrolment issues ten single-use codes, shown once and stored only as hashes.
Three properties, each of which is the whole point of one design choice:

**Hashed, like passwords.** A recovery code is a password that bypasses the
second factor. Storing them in plaintext would mean a database dump hands over
every account's 2FA - the thing 2FA exists to survive.

**Single use, enforced by a row.** `used_at` is stamped on the code that was
spent rather than a counter being decremented, so "which codes are left" and
"when was each one used" are both answerable, and a replayed code meets a row
that already has a timestamp.

**Deleted and reissued together.** Codes are never topped up one at a time. A
set is issued whole and replaced whole, because a user who has three left and
is handed seven more cannot tell which of the ten on their screen still work.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin, utcnow
from app.db.types import TimestampType, UUIDType


class RecoveryCode(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "recovery_codes"
    __table_args__ = (Index("ix_recovery_codes_user", "user_id", "used_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    issued_at: Mapped[datetime] = mapped_column(
        TimestampType, nullable=False, default=utcnow
    )

    #: PBKDF2, the same hash the passwords use. A recovery code is a password
    #: that skips the second factor; storing it in plaintext would mean a
    #: database dump hands over every account's 2FA.
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    #: Stamped on the code that was spent, rather than decrementing a counter.
    #: "Which are left" and "when was each used" are then both answerable, and
    #: a replayed code meets a row that already carries a time.
    used_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
