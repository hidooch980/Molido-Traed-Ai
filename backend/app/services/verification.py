"""Single-use, expiring links that prove somebody controls an address.

The token is generated here, handed to a transport, and never stored in the
clear. What lands in the database is a hash and a non-secret prefix - the same
shape the session tokens already use, for the same reason: this is the table an
email address is joined to, which makes it the first one an attacker reads, and
a leaked database must not hand out working links.

`purpose` is checked on redemption rather than assumed from the route. A
verification token that also resets a password is a verification link that
takes over an account.

Nothing here sends anything. The transport is passed in, so this module is the
same whether the link goes out over SMTP, over Telegram, or is read off the
screen by an operator - and a deployment with no transport configured produces
a token and says plainly that it could not deliver it, rather than reporting
success for a message nobody will ever receive.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationFailedError
from app.models.tenancy import AccountToken, User

VERIFY_EMAIL = "verify_email"

#: Long enough that guessing is hopeless, short enough to survive being pasted
#: into a mail client that wraps long lines.
TOKEN_BYTES = 32

#: A verification link that never expires is a permanent key sitting in an
#: inbox somebody may lose access to. A day is long enough for a person to get
#: to their mail and short enough that an old message is not a way in.
LIFETIME = timedelta(hours=24)

PREFIX_LENGTH = 12


def _digest(token: str) -> str:
    """SHA-256, not a password hash.

    A password hash is deliberately slow to make guessing expensive, which is
    the right trade for a secret a person chose and might reuse. This token is
    256 bits of randomness that exists for a day: it cannot be guessed, cannot
    be reused elsewhere, and making every verification click take 200ms of CPU
    buys nothing.
    """
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class Issued:
    """A token that now exists. The clear value appears here and nowhere else."""

    token: str
    expires_at: datetime
    user_id: uuid.UUID
    email: str

    def as_dict(self) -> dict[str, Any]:
        """Deliberately without the token.

        The clear value is for the transport alone. Anything that serialises
        this - a log line, an API response, an error report - must not carry a
        working link.
        """
        return {
            "issued": True,
            "expires_at": self.expires_at.isoformat(),
            "email": self.email,
        }


def issue(
    session: Session,
    user: User,
    *,
    purpose: str = VERIFY_EMAIL,
    now: datetime | None = None,
) -> Issued:
    """Create a token, invalidating any earlier unused one for the same purpose.

    Earlier tokens are burned rather than left alive. Somebody who asks for a
    second link almost always does so because the first did not arrive or was
    seen by the wrong person, and leaving five working links in five inboxes is
    the opposite of what they were asking for.
    """
    moment = now or datetime.now(UTC)

    outstanding = session.scalars(
        select(AccountToken).where(
            AccountToken.user_id == user.id,
            AccountToken.purpose == purpose,
            AccountToken.used_at.is_(None),
        )
    ).all()
    for row in outstanding:
        row.used_at = moment

    token = secrets.token_urlsafe(TOKEN_BYTES)
    session.add(
        AccountToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=_digest(token),
            token_prefix=token[:PREFIX_LENGTH],
            expires_at=moment + LIFETIME,
        )
    )
    session.flush()

    return Issued(
        token=token, expires_at=moment + LIFETIME, user_id=user.id, email=user.email
    )


def redeem(
    session: Session,
    token: str,
    *,
    purpose: str = VERIFY_EMAIL,
    now: datetime | None = None,
) -> User:
    """Spend a token once, and return whose it was.

    Expiry, reuse and the wrong purpose are all refused with the same message.
    Telling somebody holding a token whether it merely expired or was already
    spent describes the state of an account they may not own.
    """
    moment = now or datetime.now(UTC)
    refusal = ValidationFailedError(
        "That link is not valid. It may have expired, or already been used - "
        "ask for a new one."
    )

    if not token:
        raise refusal

    row = session.scalar(
        select(AccountToken).where(
            AccountToken.token_prefix == token[:PREFIX_LENGTH],
            AccountToken.purpose == purpose,
        )
    )
    if row is None:
        raise refusal
    # Constant-time, because the prefix narrows the search to one row and a
    # timing difference on the remaining comparison is the only signal left.
    if not secrets.compare_digest(row.token_hash, _digest(token)):
        raise refusal
    if row.used_at is not None or row.expires_at <= moment:
        raise refusal

    user = session.get(User, row.user_id)
    if user is None:
        raise NotFoundError("That link belongs to an account that no longer exists.")

    row.used_at = moment
    session.flush()
    return user


def mark_verified(
    session: Session, user: User, *, now: datetime | None = None
) -> dict[str, Any]:
    """Stamp the address as verified. Idempotent."""
    if user.email_verified_at is not None:
        return {"verified": True, "already": True}
    user.email_verified_at = now or datetime.now(UTC)
    session.flush()
    return {"verified": True, "already": False}
