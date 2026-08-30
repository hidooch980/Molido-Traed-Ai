"""Sign in once, instead of carrying a key to every button (spec §45, §52).

The broker form shipped with an "API key" field whose value could only be found
by opening an SSH session and running `cat`. That is a step the person who owns
this system will not take, and a feature nobody uses is indistinguishable from
one nobody built.

So: the owner sets a password once, signs in, and the browser holds a session
cookie. Every state-changing button then works with no key, no terminal and no
copied secret. The permission model underneath does not change at all - the
session resolves to the same `Principal` an API key would, carrying the same
role and the same permissions, so nothing above this line has to know which one
a request arrived with.

Three things this deliberately does not do.

It does not weaken the gate. A session is one more way to *become*
authenticated; it grants nothing an API key would not, and `require()` still
refuses every permission above READ for a caller who is neither.

It does not store a password anywhere in reach. Only a bcrypt hash is written,
by a command the owner runs themselves, and this module never sees a plaintext
password except to compare it.

It does not remember forever. A session expires, because a browser left open on
a shared machine is the most ordinary way a credential leaks, and "signed in
until something happens" is not an expiry.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthenticationError
from app.core.enums import UserRole
from app.core.security import verify_password
from app.models.tenancy import ApiKey, User

#: How long a signed-in browser stays signed in. Twelve hours covers a working
#: day without covering the night somebody left the tab open in a café.
SESSION_LIFETIME = timedelta(hours=12)

#: The cookie name. Prefixed so it cannot be confused with anything the app
#: might set later, and read only from the cookie header - never from a query
#: string, where it would end up in access logs and browser history.
COOKIE_NAME = "molido_session"

#: Sessions are stored as `ApiKey` rows with this label. Reusing that table
#: rather than adding one means revocation, expiry and last-used tracking are
#: the mechanisms that already exist and are already tested, instead of a
#: second implementation that has to be kept in step with the first.
SESSION_LABEL = "browser session"


@dataclass(frozen=True)
class SignIn:
    """A successful sign-in, and the token the browser will carry."""

    token: str
    expires_at: datetime
    role: UserRole
    tenant_id: uuid.UUID
    #: Who signed in. Carried so the attempt record can say which account
    #: succeeded - a log of successes that cannot name one answers none of the
    #: questions asked after a scare.
    user_id: uuid.UUID


def _digest(token: str) -> str:
    """A session token is high-entropy already, so a fast hash is the right
    one. bcrypt exists to make guessing a human-chosen password slow; applying
    it to 256 bits of randomness costs milliseconds per request and buys
    nothing."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def sign_in(
    session: Session, *, email: str, password: str, now: datetime | None = None
) -> SignIn:
    """Check a password and issue a session token.

    The failure message is identical for an unknown address, a wrong password
    and a disabled account. Telling them apart tells an attacker which half of
    the guess was right.
    """
    moment = now or datetime.now(UTC)
    user = session.scalar(select(User).where(User.email == email.strip().lower()))

    if user is None or not verify_password(password, user.password_hash):
        raise AuthenticationError("Those details do not match an account.")
    if not user.is_active:
        raise AuthenticationError("Those details do not match an account.")

    token = secrets.token_urlsafe(32)
    expires = moment + SESSION_LIFETIME

    session.add(
        ApiKey(
            tenant_id=user.tenant_id,
            user_id=user.id,
            label=SESSION_LABEL,
            # The prefix is the lookup key and is not secret; the digest is what
            # actually authenticates. Same shape the API-key path uses, so one
            # resolver serves both.
            key_prefix=token[:12],
            key_hash=_digest(token),
            scopes=user.role,
            expires_at=expires,
        )
    )
    user.last_login_at = moment
    session.flush()

    return SignIn(
        token=token,
        expires_at=expires,
        role=UserRole(user.role),
        tenant_id=user.tenant_id,
        user_id=user.id,
    )


def resolve(session: Session, token: str, *, now: datetime | None = None) -> ApiKey | None:
    """The session row behind a cookie, if it is live.

    Expired and revoked both return nothing rather than raising. A stale cookie
    is the ordinary end of a session, not an incident, and treating it as one
    trains people to ignore the alarm.
    """
    moment = now or datetime.now(UTC)
    digest = _digest(token)

    for row in session.scalars(
        select(ApiKey).where(
            ApiKey.key_prefix == token[:12], ApiKey.label == SESSION_LABEL
        )
    ):
        if not secrets.compare_digest(row.key_hash, digest):
            continue
        if row.revoked_at is not None:
            return None
        if row.expires_at is not None and row.expires_at <= moment:
            return None
        row.last_used_at = moment
        return row
    return None


def sign_out(session: Session, token: str, *, now: datetime | None = None) -> bool:
    """Revoke one session. Signing out must actually end it, not just drop the
    cookie - a token the browser forgot is still a token that works."""
    row = resolve(session, token, now=now)
    if row is None:
        return False
    row.revoked_at = now or datetime.now(UTC)
    return True


def prune(session: Session, *, now: datetime | None = None) -> int:
    """Delete sessions that expired. Kept small on purpose: the row is only
    useful while it can authenticate, and an unbounded table of dead tokens is
    a slow leak of storage and of anyone's ability to read the live ones."""
    moment = now or datetime.now(UTC)
    dead = list(
        session.scalars(
            select(ApiKey).where(
                ApiKey.label == SESSION_LABEL, ApiKey.expires_at <= moment
            )
        )
    )
    for row in dead:
        session.delete(row)
    return len(dead)
