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

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.api.guard import public_mutation
from app.core.enums import Permission, UserRole
from app.core.errors import ValidationFailedError
from app.db.session import get_db
from app.services import users as user_service

router = APIRouter(prefix="/users", tags=["users"])

READ = Depends(require(Permission.READ))

#: Creating an account and switching one off are mutations, so they carry a
#: permission above READ - which is what the execution gate checks and what an
#: anonymous caller does not hold.
#:
#: SIMULATE rather than EXECUTE, for the same reason `brokers/link` gives:
#: EXECUTE is the tier that sends orders, and it refuses to boot at all unless
#: MOLIDO_REQUIRE_AUTH is on. Declaring it here would tie account management to
#: a switch about order execution. The control that actually matters is the
#: owner-or-admin check below, which no permission tier can express: trader and
#: admin both hold EXECUTE, and a trader must not be able to mint an admin.
SIMULATE = Depends(require(Permission.SIMULATE))

#: Who may create accounts and switch them off. Not a permission tier: trader
#: and admin both hold EXECUTE, and a trader must not be able to mint an admin.
MANAGING_ROLES: frozenset[UserRole] = frozenset({UserRole.OWNER, UserRole.ADMIN})


class Signup(BaseModel):
    email: str = Field(min_length=3, max_length=320)
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


def _require_manager(principal: Principal) -> None:
    if principal.role not in MANAGING_ROLES:
        raise ValidationFailedError(
            "Only an owner or an admin can manage accounts.",
            your_role=principal.role.value,
            required=sorted(r.value for r in MANAGING_ROLES),
        )


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
    )
    session.commit()
    return created.as_dict()


@router.get("")
def list_users(
    principal: Principal = READ,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Everybody who exists, for an owner or admin. No hashes, no tokens."""
    _require_manager(principal)
    people = user_service.listing(session)
    return {
        "count": len(people),
        "users": people,
        "assignable_roles": sorted(r.value for r in user_service.ASSIGNABLE_ROLES),
    }


@router.post("", status_code=201)
def create_user(
    body: NewUser,
    principal: Principal = SIMULATE,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Add somebody at a chosen role. Owner and admin only."""
    _require_manager(principal)
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
    principal: Principal = SIMULATE,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Switch an account on or off. Never deletes - the audit trail stays."""
    _require_manager(principal)
    result = user_service.set_active(
        session, user_id, active=body.active, actor_id=principal.user_id
    )
    session.commit()
    return result
