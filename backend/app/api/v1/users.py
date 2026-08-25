"""Claiming a deployment, registering, and managing who can sign in (spec §45).

Two of these routes are reachable without a session, and each one needs its own
justification because "public" and "mutating" together is where the holes are:

`GET  /users/setup`   - says whether this deployment has been claimed. Public
                        because the sign-in page has to know which form to show
                        before anybody can sign in. It reports one boolean and
                        no addresses, so it tells an attacker nothing they could
                        not learn by loading the page.

`POST /users/claim`   - creates the first owner. Public only while no account
                        has a password, and permanently closed afterwards. The
                        alternative is an installer-chosen password living in a
                        config file, which is worse.

`POST /users/register`- self sign-up, always as a viewer. A viewer reads and
                        touches nothing that moves money, so this door does not
                        open onto the broker connection.

Everything else needs an authenticated session, and the two that hand out roles
or switch accounts off need an owner or admin - checked here rather than by
permission tier, because trader and admin share EXECUTE but only one of them
should be able to create accounts.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Cookie, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.api.guard import public_mutation
from app.core.config import get_settings
from app.core.enums import Permission, UserRole
from app.core.errors import ValidationFailedError
from app.db.session import get_db
from app.integrations import email
from app.models.tenancy import User
from app.services import referrals, sessions_auth, verification
from app.services import users as user_service

router = APIRouter(prefix="/users", tags=["users"])

READ = Depends(require(Permission.READ))

#: Acting on your own account: changing your password, asking for a fresh
#: verification link. A mutation, so above READ, but not account management -
#: needing the permission that mints admins in order to change your own
#: password would give every user the power to mint one.
#:
#: This was SIMULATE, which a viewer does not hold - so the role with the least
#: to lose was the one role that could not change its own password. `READ` is
#: not an option either: an anonymous caller holds it, and these mutate.
SELF_MANAGE = Depends(require(Permission.SELF_MANAGE))

#: Creating accounts, switching them off, and reading the roster.
#:
#: This used to be SIMULATE plus a hand-written owner-or-admin check, and the
#: comment above it explained why: the three tiers could not express "manages
#: accounts" at all, because trader and admin both held EXECUTE and a trader
#: must not be able to mint an admin. The permission now says exactly that, so
#: the second check is gone rather than kept alongside it. Two places deciding
#: one question is how they come to disagree, and then neither is the answer.
USERS_MANAGE = Depends(require(Permission.USERS_MANAGE))


class Signup(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    #: Optional. A code that does not exist fails the registration rather than
    #: being dropped - see `referrals.resolve_code` for why silence is worse.
    referral_code: str = Field(default="", max_length=32)
    # Never echoed, never logged, never returned in an error. `repr=False` so
    # it cannot arrive in a traceback either.
    password: str = Field(min_length=1, max_length=256, repr=False)
    display_name: str = Field(default="", max_length=200)

    @field_validator("email")
    @classmethod
    def _looks_like_an_address(cls, value: str) -> str:
        """Enough to catch a typo, and deliberately not more.

        Full RFC validation needs a dependency and still accepts addresses that
        do not receive mail, so it buys less than it looks like it does. What
        this stops is the empty-domain and no-at-sign mistakes somebody makes
        in a hurry, which is the failure this form actually sees.
        """
        address = value.strip()
        local, separator, domain = address.partition("@")
        if not separator or not local or "." not in domain or domain.endswith("."):
            raise ValueError("that does not look like an email address")
        return address


class NewUser(Signup):
    role: UserRole


class ActiveFlag(BaseModel):
    active: bool


class VerificationToken(BaseModel):
    token: str = Field(min_length=8, max_length=256, repr=False)


class PasswordChange(BaseModel):
    current: str = Field(min_length=1, max_length=256, repr=False)
    replacement: str = Field(min_length=1, max_length=256, repr=False)


@router.get("/setup")
def read_setup(
    _: Principal = READ,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Whether this deployment has an account anybody can sign in with.

    One boolean, no addresses and no names. The sign-in page needs it to decide
    between "claim this deployment" and "sign in", and that decision cannot
    wait until after somebody has signed in.
    """
    claimed = user_service.is_claimed(session)
    return {
        "claimed": claimed,
        "password_min_length": user_service.PASSWORD_MIN_LENGTH,
        "self_registration_role": user_service.SELF_REGISTERED_ROLE.value,
        "note": (
            "an unclaimed deployment has no account with a password, so the "
            "first person to arrive becomes its owner. That window closes for "
            "good once one account has a password"
            if not claimed
            else "this deployment is claimed; new accounts register as viewers "
            "or are created by an owner or admin"
        ),
    }


@router.post("/claim", status_code=201)
@public_mutation(
    "creates the first owner of a deployment nobody can sign in to yet; "
    "requiring a session to reach it would need a session that cannot exist"
)
def claim_deployment(
    body: Signup,
    _: Principal = READ,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Become the owner. Refused with 409 once anybody has a password."""
    created = user_service.claim(
        session,
        email=body.email,
        password=body.password,
        display_name=body.display_name,
    )
    session.commit()
    return created.as_dict()


@router.post("/register", status_code=201)
@public_mutation(
    "self sign-up, which lands as a viewer and can reach nothing that moves "
    "money; requiring a session would mean nobody could ever create one"
)
def register_user(
    body: Signup,
    _: Principal = READ,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Sign yourself up as a viewer."""
    created = user_service.register(
        session,
        email=body.email,
        password=body.password,
        display_name=body.display_name,
        referral_code=body.referral_code or None,
    )

    # Issued and attempted in the same request, and the outcome of the attempt
    # is reported. A registration that says "check your email" on a deployment
    # with no relay configured is a dead end the person cannot diagnose.
    user = session.get(User, created.id)
    delivery = _send_verification(session, user) if user else {"sent": False}

    session.commit()
    return {**created.as_dict(), "verification": delivery}


@router.get("")
def list_users(
    _: Principal = USERS_MANAGE,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Everybody who exists, for whoever manages accounts. No hashes, no tokens."""
    people = user_service.listing(session)
    return {
        "count": len(people),
        "users": people,
        "assignable_roles": sorted(r.value for r in user_service.ASSIGNABLE_ROLES),
    }


@router.post("", status_code=201)
def create_user(
    body: NewUser,
    _: Principal = USERS_MANAGE,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Add somebody at a chosen role. Owner and admin only."""
    created = user_service.create(
        session,
        email=body.email,
        password=body.password,
        role=body.role,
        display_name=body.display_name,
    )
    session.commit()
    return created.as_dict()


@router.post("/{user_id}/active")
def set_user_active(
    user_id: uuid.UUID,
    body: ActiveFlag,
    principal: Principal = USERS_MANAGE,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Switch an account on or off. Never deletes - the audit trail stays."""
    result = user_service.set_active(
        session, user_id, active=body.active, actor_id=principal.user_id
    )
    session.commit()
    return result


@router.post("/me/password")
def change_own_password(
    body: PasswordChange,
    principal: Principal = SELF_MANAGE,
    session: Session = Depends(get_db),
    molido_session: str | None = Cookie(
        default=None, alias=sessions_auth.COOKIE_NAME
    ),
) -> dict[str, Any]:
    """Change your own password and end every other session.

    SIMULATE rather than READ because it mutates, and the execution gate is
    right to insist: an anonymous caller must not reach it. Which account it
    changes comes from the session, never from the body - a `user_id` field
    here would let anybody with a viewer account rewrite the owner's password.

    The current session is spared by matching the prefix of the cookie the
    browser sent, so changing a password does not sign you out of the page you
    are standing on.
    """
    if principal.user_id is None:
        raise ValidationFailedError(
            "This changes the password of the account you are signed in as, "
            "and an API key is not signed in as anybody."
        )

    result = user_service.change_password(
        session,
        principal.user_id,
        current=body.current,
        replacement=body.replacement,
        # The prefix is the non-secret lookup half of the token. Comparing it
        # identifies this browser's session without the request handling the
        # secret half at all.
        keep_token_prefix=molido_session[:12] if molido_session else None,
    )
    session.commit()
    return result


def _send_verification(session: Session, user: User) -> dict[str, Any]:
    """Issue a link and try to deliver it, reporting what actually happened.

    The token is created either way. A deployment with no relay still has a
    working verification path - an owner can read the link from the admin list
    and pass it on - and refusing to issue one because the mail cannot go out
    would make the two failures the same failure.
    """
    issued = verification.issue(session, user)
    link = f"{get_settings().public_base_url.rstrip('/')}/verify?token={issued.token}"

    delivery = email.send(
        to=user.email,
        subject="Verify your MolidoTrade account",
        body=(
            "Open this link to verify your account:\n\n"
            f"{link}\n\n"
            "It works once and expires in 24 hours. If you did not create an "
            "account, ignore this message - nothing happens until the link is "
            "opened."
        ),
    )
    return {
        "issued": True,
        "expires_at": issued.expires_at.isoformat(),
        "sent": delivery.sent,
        # The reason travels, so "no relay configured" reaches the person who
        # can fix it instead of dying in a log nobody reads.
        "reason": delivery.reason,
    }


@router.post("/verify")
@public_mutation(
    "spends a verification link, which is held by somebody who by definition "
    "has no session yet; the token is the credential"
)
def verify_account(
    body: VerificationToken,
    _: Principal = READ,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Spend a verification link.

    Public because the person holding it has no session - that is the whole
    point of the link. The token is the credential, it is single-use, it
    expires, and it is stored only as a hash.
    """
    user = verification.redeem(session, body.token)
    marked = verification.mark_verified(session, user)
    # Verifying is what confirms a referral, and nothing else does. Registering
    # proves nothing and costs nothing, which is exactly what makes it worth
    # faking a hundred times.
    credited = referrals.confirm(session, user)
    session.commit()
    return {
        "verified": True,
        "already_verified": marked["already"],
        "points_awarded": credited.get("awarded", 0),
        "referrer_awarded": credited.get("awarded_to_referrer", 0),
    }


@router.post("/me/verification")
def resend_verification(
    principal: Principal = SELF_MANAGE,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Ask for a new link. The previous unused one stops working."""
    if principal.user_id is None:
        raise ValidationFailedError("This needs a signed-in account.")

    user = session.get(User, principal.user_id)
    if user is None:
        raise ValidationFailedError("This needs a signed-in account.")
    if user.email_verified_at is not None:
        return {"issued": False, "reason": "this address is already verified"}

    result = _send_verification(session, user)
    session.commit()
    return result


@router.get("/me/referrals")
def read_own_standing(
    principal: Principal = READ,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Your code, your points, and how your invitations are going."""
    if principal.user_id is None:
        raise ValidationFailedError("This needs a signed-in account.")

    standing = referrals.standing(session, principal.user_id)
    session.commit()
    return standing.as_dict()
