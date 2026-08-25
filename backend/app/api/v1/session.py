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

from fastapi import APIRouter, Cookie, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.api.guard import public_mutation
from app.api.net import client_address, user_agent
from app.core.enums import Permission
from app.core.errors import MolidoError
from app.db.session import get_db
from app.services import human_check, login_guard, sessions_auth

router = APIRouter(prefix="/session", tags=["session"])

READ = Depends(require(Permission.READ))


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    # Never echoed, never logged, never returned in an error.
    password: str = Field(min_length=1, max_length=256, repr=False)

    #: The proof of work, when one is being asked for. Optional in the schema
    #: and mandatory in the handler when `login_guard` says so - a required
    #: field would refuse the first sign-in anybody ever makes, which is the
    #: one that has no failures behind it and needs no proof.
    challenge_id: str | None = None
    #: Accepts a number as well as a string. A JSON client that found the nonce
    #: by counting sends a number, and pydantic does not turn one into the
    #: other - so a str-only field answered every correct solution with a
    #: validation error about a type, which reads as a broken login.
    nonce: str | int | None = None


@router.get("/challenge")
def read_challenge(
    request: Request,
    email: str = "",
    _: Principal = READ,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """A proof-of-work challenge for the sign-in form.

    Readable without signing in, which it has to be. The difficulty rises with
    how many times this account and this address have just failed, so the
    address is read the same way the limiter reads it - a challenge sized from
    a forgeable address would be a challenge an attacker sizes for themselves.

    Issued on every call rather than reused. A challenge is one row, lives five
    minutes, and is spent by the first attempt that presents it.
    """
    verdict = login_guard.check(
        session, email=email or "unknown", address=client_address(request)
    )
    challenge = human_check.issue(
        session,
        purpose=human_check.SIGN_IN,
        failures=max(verdict.subject_failures, verdict.address_failures),
    )
    session.commit()
    return {
        **challenge.as_dict(),
        "required": verdict.human_check_required,
        "note": (
            "solve it before signing in when `required` is true. Asking for it "
            "early is deliberate: it costs a person a moment and a guessing "
            "loop everything"
        ),
    }


@router.post("/sign-in")
@public_mutation(
    "creates the session a caller needs; requiring one to reach it would be a "
    "door that needs a key to reach the key"
)
def sign_in(
    credentials: Credentials,
    request: Request,
    response: Response,
    _: Principal = READ,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Exchange a password for a session cookie.

    The failure is identical for an unknown address, a wrong password and a
    disabled account, and it is raised by the service rather than shaped here -
    telling them apart tells an attacker which half of the guess was right.

    Three things happen around that check, in this order, and the order is the
    point:

    1. `login_guard.enforce` refuses before the password is read. A limiter
       consulted afterwards is not a limiter, it is a log.
    2. A proof of work is demanded when there have been enough recent failures
       to make one worth demanding.
    3. The attempt is written down and **committed** whichever way it went.

    The commit is not incidental. `get_db` rolls back on any exception, so a
    failed sign-in raising `AuthenticationError` would have rolled back its own
    failure record - and a limiter that counts rows which are deleted by the
    thing they are counting counts nothing at all, forever, silently.
    """
    address = client_address(request)
    agent = user_agent(request)

    verdict = login_guard.enforce(session, email=credentials.email, address=address)

    if verdict.human_check_required:
        try:
            human_check.verify(
                session,
                challenge_id=credentials.challenge_id,
                nonce=credentials.nonce,
                purpose=human_check.SIGN_IN,
            )
        except MolidoError:
            # Recorded as a failure. A caller that skips the proof is not
            # separated from one that fails the password: both are attempts,
            # and only counting the ones that get as far as a password check
            # would let a loop reset nothing while trying forever.
            login_guard.record(
                session,
                email=credentials.email,
                address=address,
                succeeded=False,
                reason="human check failed",
                user_agent=agent,
            )
            session.commit()
            raise

    try:
        result = sessions_auth.sign_in(
            session, email=credentials.email, password=credentials.password
        )
    except MolidoError:
        login_guard.record(
            session,
            email=credentials.email,
            address=address,
            succeeded=False,
            reason="credentials rejected",
            user_agent=agent,
        )
        session.commit()
        raise

    login_guard.record(
        session,
        email=credentials.email,
        address=address,
        succeeded=True,
        user_id=result.user_id,
        user_agent=agent,
    )
    # Five wrong attempts and then the right one must not leave the ladder
    # standing against somebody who has just proved they own the account.
    login_guard.clear(session, email=credentials.email)
    session.commit()

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
