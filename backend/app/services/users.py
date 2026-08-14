"""Creating and managing the people who can sign in (spec §45, §52).

Three ways a user comes to exist, and they are deliberately not the same:

**Claim.** A fresh deployment has no account anybody can sign in with, so the
first visitor claims it and becomes the owner. That window is open only while
no account has a password, and it closes permanently the moment one does. It
exists because the alternative is a password set by whoever installed the
system - written into a config file, pasted into a chat, and never changed.

**Register.** Anyone may sign themselves up, and lands as a viewer. A viewer
reads and does nothing else: no broker connected, no order simulated, no order
sent. Self-registration that granted anything more would make the door to the
money the same door as the door to the marketing page.

**Create.** An owner or admin adds somebody at a chosen role. This is the only
path that hands out a role above viewer, and the only one that requires already
being trusted.

No function here accepts, returns, stores or logs a plaintext password. It goes
from the request body into `hash_password` and nowhere else.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import UserRole
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.core.security import hash_password, verify_password
from app.models.tenancy import ApiKey, Tenant, User
from app.services.sessions_auth import SESSION_LABEL

#: Long enough to matter, short enough that nobody writes it on paper. This
#: guards a system that can connect a live broker account, so the floor is not
#: the eight characters a login form usually asks for.
PASSWORD_MIN_LENGTH = 12

#: The roles an owner or admin may hand out. OWNER is absent on purpose: it
#: comes from claiming an unclaimed deployment, not from an existing user
#: creating a second one.
ASSIGNABLE_ROLES: frozenset[UserRole] = frozenset(
    {UserRole.ADMIN, UserRole.TRADER, UserRole.ANALYST, UserRole.VIEWER}
)

#: What a self-registered account gets. Read, and nothing that touches money.
SELF_REGISTERED_ROLE = UserRole.VIEWER

DEFAULT_TENANT_SLUG = "molido"


@dataclass(frozen=True)
class Created:
    """A user that now exists. Carries no password and no hash."""

    id: uuid.UUID
    email: str
    display_name: str
    role: UserRole
    claimed_deployment: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "email": self.email,
            "display_name": self.display_name,
            "role": self.role.value,
            "claimed_deployment": self.claimed_deployment,
        }


def normalise_email(email: str) -> str:
    return email.strip().lower()


def check_password(password: str) -> None:
    """Refuse a password before it is hashed, with the reason.

    Length only. A rule demanding a symbol and a digit pushes people towards
    one obvious pattern and teaches them the form is an obstacle rather than a
    lock; length is the property that actually costs an attacker time.
    """
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValidationFailedError(
            f"A password needs at least {PASSWORD_MIN_LENGTH} characters. "
            "Length is what makes it hard to guess - a long ordinary phrase "
            "beats a short complicated one.",
            minimum=PASSWORD_MIN_LENGTH,
        )


def is_claimed(session: Session) -> bool:
    """Whether anybody can already sign in to this deployment.

    A user row with no password cannot sign in - the seeded key-holder is one -
    so its presence must not close the claim window. Counting rows instead of
    counting passwords is the mistake that would lock a deployment out of
    itself permanently.
    """
    count = session.scalar(
        select(func.count())
        .select_from(User)
        .where(User.password_hash.is_not(None), User.is_active.is_(True))
    )
    return bool(count)


def _tenant(session: Session) -> Tenant:
    tenant = session.scalar(select(Tenant).order_by(Tenant.created_at).limit(1))
    if tenant is None:
        tenant = Tenant(slug=DEFAULT_TENANT_SLUG, name="Molido", is_active=True)
        session.add(tenant)
        session.flush()
    return tenant


def _place(
    session: Session,
    *,
    email: str,
    password: str,
    display_name: str,
    role: UserRole,
    now: datetime | None = None,
) -> User:
    """Write one user. The single place a password becomes a hash."""
    address = normalise_email(email)
    check_password(password)

    existing = session.scalar(select(User).where(User.email == address))
    if existing is not None and existing.password_hash is not None:
        # Privacy would prefer one message whether or not the address is real,
        # but this is a form somebody is filling in about themselves - telling
        # them it is taken is the only way they can act on it.
        raise ConflictError("That email address already has an account.")

    if existing is not None:
        # A seeded row with no password: give it one rather than colliding with
        # the unique constraint on (tenant, email).
        existing.password_hash = hash_password(password)
        existing.role = role
        existing.is_active = True
        if display_name.strip():
            existing.display_name = display_name.strip()
        existing.updated_at = now or datetime.now(UTC)
        session.flush()
        return existing

    tenant = _tenant(session)
    user = User(
        tenant_id=tenant.id,
        email=address,
        display_name=display_name.strip() or address.split("@")[0],
        password_hash=hash_password(password),
        role=role,
        is_active=True,
    )
    session.add(user)
    session.flush()
    return user


def claim(
    session: Session,
    *,
    email: str,
    password: str,
    display_name: str = "",
    now: datetime | None = None,
) -> Created:
    """Become the owner of a deployment nobody can sign in to yet.

    Checked and written inside the caller's transaction, so two people claiming
    at the same instant is settled by the database rather than by which request
    arrived first.
    """
    if is_claimed(session):
        raise ConflictError(
            "This deployment already has an account, so it cannot be claimed "
            "again. Sign in, or ask an owner to add you."
        )

    user = _place(
        session,
        email=email,
        password=password,
        display_name=display_name,
        role=UserRole.OWNER,
        now=now,
    )
    return Created(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=UserRole.OWNER,
        claimed_deployment=True,
    )


def register(
    session: Session,
    *,
    email: str,
    password: str,
    display_name: str = "",
    now: datetime | None = None,
) -> Created:
    """Sign yourself up. Always a viewer, never anything more.

    A viewer reads. It cannot connect a broker, simulate an order or send one -
    which is the only reason this form can be open to anybody at all.
    """
    if not is_claimed(session):
        raise ConflictError(
            "This deployment has no owner yet, so the first account must claim "
            "it rather than register."
        )

    user = _place(
        session,
        email=email,
        password=password,
        display_name=display_name,
        role=SELF_REGISTERED_ROLE,
        now=now,
    )
    return Created(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=SELF_REGISTERED_ROLE,
        claimed_deployment=False,
    )


def create(
    session: Session,
    *,
    email: str,
    password: str,
    role: UserRole,
    display_name: str = "",
    now: datetime | None = None,
) -> Created:
    """Add somebody at a chosen role. Owner and admin only, gated at the route."""
    if role not in ASSIGNABLE_ROLES:
        raise ValidationFailedError(
            f"{role.value} cannot be granted here. Owner comes from claiming an "
            "unclaimed deployment, not from an existing user creating another.",
            assignable=sorted(r.value for r in ASSIGNABLE_ROLES),
        )

    user = _place(
        session,
        email=email,
        password=password,
        display_name=display_name,
        role=role,
        now=now,
    )
    return Created(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=role,
        claimed_deployment=False,
    )


def listing(session: Session) -> list[dict[str, Any]]:
    """Everybody who exists. No hashes, no tokens."""
    users = session.scalars(select(User).order_by(User.created_at)).all()
    return [
        {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "role": user.role,
            "is_active": user.is_active,
            # Stated rather than left to be inferred: an account nobody has
            # ever signed in to and one that was switched off look identical
            # from the outside otherwise.
            "can_sign_in": user.password_hash is not None and user.is_active,
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        }
        for user in users
    ]


def set_active(
    session: Session,
    user_id: uuid.UUID,
    *,
    active: bool,
    actor_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Switch an account on or off.

    Deactivating rather than deleting: a deleted user takes their audit trail
    with them, and that trail is the record of who connected which broker.
    """
    if actor_id is not None and actor_id == user_id and not active:
        raise ValidationFailedError(
            "You cannot deactivate your own account - that is how a deployment "
            "ends up with nobody who can sign in."
        )

    user = session.get(User, user_id)
    if user is None:
        raise NotFoundError("No such user.")

    if not active and user.role == UserRole.OWNER:
        remaining = session.scalar(
            select(func.count())
            .select_from(User)
            .where(
                User.role == UserRole.OWNER,
                User.is_active.is_(True),
                User.id != user_id,
                User.password_hash.is_not(None),
            )
        )
        if not remaining:
            raise ValidationFailedError(
                "This is the last owner who can sign in. Deactivating it would "
                "leave the deployment with no way back in."
            )

    user.is_active = active
    session.flush()
    return {"id": str(user.id), "email": user.email, "is_active": user.is_active}


def change_password(
    session: Session,
    user_id: uuid.UUID,
    *,
    current: str,
    replacement: str,
    keep_token_prefix: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Change your own password, and end every other session.

    The current password is required even though the caller already holds a
    valid session. A session can be stolen; the password is the thing only the
    owner knows, and without this check a stolen cookie is enough to lock the
    real owner out of their own deployment permanently.

    Every other session is then revoked. That is the entire point of changing a
    password after a suspected compromise - leaving the other sessions alive
    changes the lock and hands the intruder a key that still works. The caller's
    own session survives, so changing a password does not sign you out of the
    page you are standing on.
    """
    user = session.get(User, user_id)
    if user is None:
        raise NotFoundError("No such user.")

    if not verify_password(current, user.password_hash):
        # Same wording as a failed sign-in. Confirming that the current
        # password was right while the new one was rejected would turn this
        # form into an oracle for guessing it.
        raise ValidationFailedError("Those details do not match an account.")

    check_password(replacement)

    if verify_password(replacement, user.password_hash):
        raise ValidationFailedError(
            "That is the password you already have, so nothing would change. "
            "If you are changing it because it may be known, it needs to be "
            "different."
        )

    moment = now or datetime.now(UTC)
    user.password_hash = hash_password(replacement)
    user.updated_at = moment

    revoked = 0
    sessions = session.scalars(
        select(ApiKey).where(
            ApiKey.user_id == user_id,
            ApiKey.label == SESSION_LABEL,
            ApiKey.revoked_at.is_(None),
        )
    ).all()
    for row in sessions:
        if keep_token_prefix and row.key_prefix == keep_token_prefix:
            continue
        row.revoked_at = moment
        revoked += 1

    session.flush()
    return {
        "changed": True,
        "other_sessions_ended": revoked,
        "note": (
            "every other signed-in browser has been signed out. Changing a "
            "password while leaving the old sessions alive changes the lock "
            "and hands out a key that still works"
        ),
    }
