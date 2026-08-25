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

from app.api.deps import AuthenticationError, Principal, require
from app.api.guard import public_mutation
from app.api.net import client_address, user_agent
from app.core.enums import AuditEventType, Permission
from app.core.errors import MolidoError
from app.db.session import get_db
from app.models.tenancy import User
from app.services import (
    human_check,
    login_guard,
    security_log,
    sessions_auth,
    two_factor,
)

router = APIRouter(prefix="/session", tags=["session"])

READ = Depends(require(Permission.READ))
#: Acting on your own account. Every role holds it, no anonymous caller
#: does - which is the distinction these routes actually need.
SELF_MANAGE = Depends(require(Permission.SELF_MANAGE))


class TwoFactorRequiredError(MolidoError):
    """The password was right and it is not enough.

    Its own status and code rather than a plain 401, because the page has to
    tell these two apart: a wrong password means try again, and this means show
    the code field. A client that cannot distinguish them shows "those details
    do not match" to somebody whose details matched perfectly.

    401 rather than 403: the request is not authenticated yet. Nothing was
    issued, and there is no session behind this response.
    """

    code = "two_factor_required"
    http_status = 401




class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    # Never echoed, never logged, never returned in an error.
    password: str = Field(min_length=1, max_length=256, repr=False)

    #: The proof of work, when one is being asked for. Optional in the schema
    #: and mandatory in the handler when `login_guard` says so - a required
    #: field would refuse the first sign-in anybody ever makes, which is the
    #: one that has no failures behind it and needs no proof.
    #: The six digits from the authenticator app, or a recovery code. Absent
    #: on the first request by design: the caller cannot know whether this
    #: account has a second factor until the password has been checked, and
    #: telling them before it has been is an account-enumeration oracle.
    code: str | None = None

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

    try:
        verdict = login_guard.enforce(session, email=credentials.email, address=address)
    except login_guard.TooManyAttemptsError:
        # Its own event type rather than a failure with a flag. A throttled
        # attempt says nothing about whether the password was right, and
        # counting it among the failures overstates how close anybody got.
        security_log.record(
            session,
            AuditEventType.SIGN_IN_THROTTLED,
            summary="sign-in refused by the rate limiter before the password was read",
            subject=login_guard.normalise(credentials.email),
            address=address,
            user_agent=agent,
        )
        session.commit()
        raise

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
            security_log.record(
                session,
                AuditEventType.HUMAN_CHECK_FAILED,
                summary="sign-in attempted without a valid proof of work",
                subject=login_guard.normalise(credentials.email),
                address=address,
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
        security_log.record(
            session,
            AuditEventType.SIGN_IN_FAILED,
            summary="sign-in refused: the details did not match an account",
            subject=login_guard.normalise(credentials.email),
            address=address,
            user_agent=agent,
        )
        session.commit()
        raise

    # The password was right. Whether that is enough depends on the account.
    person = session.get(User, result.user_id)
    factor = two_factor.status(session, person) if person is not None else None

    if person is not None and factor is not None and factor.enrolled:
        if not credentials.code:
            # Deliberately *after* the password check and deliberately not a
            # sign-in. Asking for a code before the password would tell an
            # unauthenticated caller which addresses have accounts, and the
            # whole point of the identical-failure rule is that they cannot
            # learn that.
            #
            # The session is not issued and the cookie is not set, so this
            # branch leaves nothing behind for a caller who guessed a password
            # and cannot produce a code.
            sessions_auth.sign_out(session, result.token)
            session.commit()
            raise TwoFactorRequiredError(
                "This account needs a code from its authenticator app."
            )

        try:
            how = two_factor.check(session, person, credentials.code)
        except MolidoError:
            sessions_auth.sign_out(session, result.token)
            login_guard.record(
                session,
                email=credentials.email,
                address=address,
                succeeded=False,
                reason="second factor rejected",
                user_agent=agent,
            )
            security_log.record(
                session,
                AuditEventType.SIGN_IN_FAILED,
                summary="password accepted, second factor refused",
                subject=login_guard.normalise(credentials.email),
                user_id=person.id,
                address=address,
                user_agent=agent,
                detail={"stage": "second_factor"},
            )
            session.commit()
            raise

        if how == "recovery":
            # Worth seeing. It usually means somebody lost a phone, and
            # occasionally means somebody else has the codes.
            security_log.record(
                session,
                AuditEventType.RECOVERY_CODE_USED,
                summary="signed in with a recovery code rather than the app",
                subject=login_guard.normalise(credentials.email),
                user_id=person.id,
                address=address,
                user_agent=agent,
                detail={"codes_left": two_factor.status(session, person).recovery_codes_left},
            )

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
    cleared = login_guard.clear(session, email=credentials.email)
    security_log.record(
        session,
        AuditEventType.SIGN_IN_SUCCEEDED,
        summary=f"signed in as {result.role.value}",
        subject=login_guard.normalise(credentials.email),
        user_id=result.user_id,
        tenant_id=result.tenant_id,
        role=result.role.value,
        address=address,
        user_agent=agent,
        # The count that was standing when it worked. A success after five
        # failures is a different line in the log from a success after none,
        # and it is the one worth looking at twice.
        detail={"failures_cleared": cleared},
    )
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
        # Present so the page knows to put the enrolment step in front of
        # everything else. The session is real - the password was correct - and
        # the account can reach no more than it could before this feature
        # existed; what it cannot do is go on ignoring the requirement.
        "two_factor": factor.as_dict() if factor else None,
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


class TwoFactorCode(BaseModel):
    """Six digits from the app, or a recovery code off a piece of paper."""

    code: str = Field(min_length=1, max_length=64)


def _me(principal: Principal, session: Session) -> User:
    """The signed-in account, or a refusal.

    Every route below acts on the caller's own second factor and never on
    anybody else's. An endpoint that took a user id would be one an
    administrator could point at the owner - and removing somebody else's
    second factor is not administration.
    """
    if principal.user_id is None:
        raise AuthenticationError("Sign in first.")
    person = session.get(User, principal.user_id)
    if person is None:
        raise AuthenticationError("That session no longer belongs to an account.")
    return person


@router.get("/two-factor")
def read_two_factor(
    principal: Principal = READ,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Where this account stands: required, started, finished, codes left."""
    return two_factor.status(session, _me(principal, session)).as_dict()


@router.post("/two-factor/begin")
def begin_two_factor(
    principal: Principal = SELF_MANAGE,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Issue a secret and the URI an authenticator app scans.

    READ, not something higher: this is an account acting on itself, and a
    viewer who wants a second factor should not be refused one. The route is
    still unreachable without a session, which is what matters - `_me` has
    nothing to return for an anonymous caller.

    Nothing is protected by this call. The account has no second factor until
    a code from the app has been confirmed.
    """
    enrolment = two_factor.begin(session, _me(principal, session))
    session.commit()
    return enrolment.as_dict()


@router.post("/two-factor/confirm")
def confirm_two_factor(
    body: TwoFactorCode,
    request: Request,
    principal: Principal = SELF_MANAGE,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Finish enrolment. Returns the recovery codes, once and never again.

    They are shown here because they are stored only as hashes - the server
    cannot produce them a second time. A page that does not put them in front
    of the user has cost them their way back in.
    """
    person = _me(principal, session)
    codes = two_factor.confirm(session, person, body.code)

    security_log.record(
        session,
        AuditEventType.TWO_FACTOR_ENROLLED,
        summary="second factor enabled",
        subject=person.email,
        user_id=person.id,
        role=str(person.role),
        address=client_address(request),
        user_agent=user_agent(request),
    )
    session.commit()

    return {
        "enrolled": True,
        "recovery_codes": codes,
        "status": two_factor.status(session, person).as_dict(),
        "note": (
            "write these down now. They are stored only as hashes, so this is "
            "the one time they can be shown - each works once, and any one of "
            "them gets you in without the phone"
        ),
    }


@router.post("/two-factor/disable")
def disable_two_factor(
    body: TwoFactorCode,
    request: Request,
    principal: Principal = SELF_MANAGE,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Remove the second factor, having proved it is held.

    The proof is the whole point. A stolen session is exactly what a second
    factor exists to survive, and one that could remove the factor would
    survive nothing.
    """
    person = _me(principal, session)
    two_factor.disable(session, person, body.code)

    security_log.record(
        session,
        AuditEventType.TWO_FACTOR_DISABLED,
        summary="second factor removed",
        subject=person.email,
        user_id=person.id,
        role=str(person.role),
        address=client_address(request),
        user_agent=user_agent(request),
    )
    session.commit()
    return {"enrolled": False, "status": two_factor.status(session, person).as_dict()}


@router.post("/two-factor/recovery-codes")
def reissue_recovery_codes(
    body: TwoFactorCode,
    principal: Principal = SELF_MANAGE,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """A fresh set, replacing every old one.

    Whole sets only. Somebody with three left who is handed seven more cannot
    tell which of the ten on their screen still work.
    """
    person = _me(principal, session)
    codes = two_factor.reissue_recovery_codes(session, person, body.code)
    session.commit()
    return {
        "recovery_codes": codes,
        "status": two_factor.status(session, person).as_dict(),
        "note": "every code issued before this one has stopped working",
    }
