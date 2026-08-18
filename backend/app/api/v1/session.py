"""Sign in, sign out, and say who you are (spec §45, §52).

Sign-in is a POST that changes state, so it carries a permission like every
other mutating route — READ, because signing in is what an anonymous caller
does and requiring more would be a door that needs its own key. The execution
gate is satisfied by the marker being present at all; what it refuses is a
mutating route with no permission on it, not a mutating route reachable by the
public.

The cookie is HttpOnly, SameSite=Lax and set for the whole site. HttpOnly keeps
it out of reach of any script on the page, which matters because a stolen
session here is a session that can connect a broker account. SameSite=Lax stops
another site posting to these routes with the browser's cookie attached.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Cookie, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import AuthenticationError, Principal, require
from app.api.guard import public_mutation
from app.core.enums import Permission
from app.db.session import get_db
from app.services import sessions_auth, signin_throttle

router = APIRouter(prefix="/session", tags=["session"])

READ = Depends(require(Permission.READ))


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    # Never echoed, never logged, never returned in an error.
    password: str = Field(min_length=1, max_length=256, repr=False)


@router.post("/sign-in")
@public_mutation(
    "creates the session a caller needs; requiring one to reach it would be a "
    "door that needs a key to reach the key"
)
def sign_in(
    credentials: Credentials,
    response: Response,
    _: Principal = READ,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Exchange a password for a session cookie.

    The failure is identical for an unknown address, a wrong password and a
    disabled account, and it is raised by the service rather than shaped here -
    telling them apart tells an attacker which half of the guess was right.
    """
    # Checked before the password is hashed, not after the verdict. PBKDF2 at
    # 480,000 iterations is expensive by design, and that cost is paid by this
    # server on its four cores before it can answer - so a throttled attempt
    # that still paid for the hash would be the attack rather than the defence.
    refusal = signin_throttle.throttle.check(credentials.email)
    if refusal:
        raise AuthenticationError(refusal)

    try:
        result = sessions_auth.sign_in(
            session, email=credentials.email, password=credentials.password
        )
    except AuthenticationError:
        # Counted here rather than inside the service, so the service keeps
        # being a pure question about one credential and this route stays the
        # only place that knows about volume.
        signin_throttle.throttle.failed(credentials.email)
        raise

    # Someone who mistyped twice and then got it right is not an attacker.
    signin_throttle.throttle.succeeded(credentials.email)

    response.set_cookie(
        key=sessions_auth.COOKIE_NAME,
        value=result.token,
        httponly=True,
        samesite="lax",
        # Not Secure, because this deployment has no TLS - it is reachable by
        # IP and has no certificate. Marking a cookie Secure over plain HTTP
        # makes the browser drop it in silence: sign-in returns 200 and nothing
        # is signed in, which is the most confusing failure available. This
        # flips the day a domain and a certificate exist, and the comment is
        # here so the reason travels with the line.
        secure=False,
        max_age=int(sessions_auth.SESSION_LIFETIME.total_seconds()),
        path="/",
    )

    return {
        "signed_in": True,
        "role": result.role.value,
        "expires_at": result.expires_at.isoformat(),
        "note": (
            "the cookie is HttpOnly, so nothing on the page can read it. It "
            "grants exactly what an API key with the same role would"
        ),
    }


@router.post("/sign-out")
@public_mutation(
    "ends a session; a caller whose cookie already expired must still be able "
    "to press it, and it revokes only the token presented"
)
def sign_out(
    response: Response,
    molido_session: str | None = Cookie(default=None, alias=sessions_auth.COOKIE_NAME),
    _: Principal = READ,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """End the session and clear the cookie.

    The row is revoked before the cookie is dropped. Clearing only the cookie
    would leave a token that still authenticates anybody who kept a copy, which
    is the opposite of what pressing sign-out means.
    """
    ended = sessions_auth.sign_out(session, molido_session) if molido_session else False
    response.delete_cookie(sessions_auth.COOKIE_NAME, path="/")
    return {
        "signed_out": True,
        "session_revoked": ended,
        "note": "the session was revoked on the server, not only forgotten by the browser",
    }


@router.get("/me")
def read_me(principal: Principal = READ) -> dict[str, Any]:
    """Who this request is, and what the page may therefore offer.

    The frontend reads this to decide whether to show a button at all. Hiding a
    button the API would refuse is a courtesy; the refusal is still the thing
    that enforces it, and both are needed - a hidden button anybody can still
    POST to is theatre.
    """
    return {
        "authenticated": principal.authenticated,
        "role": principal.role.value if principal.role else None,
        "permissions": sorted(p.value for p in principal.permissions),
        "can_change_state": any(p is not Permission.READ for p in principal.permissions),
        "note": (
            "an anonymous caller holds read and nothing else. Every button that "
            "changes something is refused by the API regardless of what the "
            "page chooses to display"
        ),
    }
