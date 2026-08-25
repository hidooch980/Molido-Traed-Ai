"""Enrolling, checking and recovering a second factor (spec §52).

`core.totp` is the arithmetic. This is the part that decides who must have one,
what happens between issuing a secret and trusting it, and how somebody gets
back in when their phone is at the bottom of a river.

**Required of the roles that can move money.** Anyone holding EXECUTE or
BROKER_MANAGE must complete enrolment; everyone else may. That is not a
courtesy to viewers - it is that a second factor forced on an account with
nothing to protect trains people to treat the whole mechanism as an obstacle,
and the accounts that matter are then guarded by somebody's irritation.

**Issuing a secret is not enrolling.** The account has no second factor until
the user has typed a code the app produced, because a QR somebody scanned into
the wrong phone and then closed would otherwise lock them out of themselves
with no way to prove it. `totp_confirmed_at` is the line.

**Confirmation is the moment recovery codes exist.** Not before: codes handed
out beside a QR that was never scanned are ten strings nobody wrote down for a
factor that was never turned on. Ten of them, shown once, stored as hashes.

**Every code is spent exactly once, and so is every TOTP step.** A six-digit
code is valid for its whole window; without recording the step, the same digits
work twice, and the second time is the one somebody read over a shoulder.

**Turning it off requires proving you have it.** Otherwise a stolen session -
which is exactly what a second factor exists to survive - can remove the second
factor and keep the account.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import ROLE_PERMISSIONS, AuthenticationError
from app.core import totp
from app.core.enums import Permission, UserRole
from app.core.errors import ValidationFailedError
from app.models.recovery_codes import RecoveryCode
from app.models.tenancy import User

#: Shown in the authenticator app's account list.
ISSUER = "MolidoTrade AI"

#: How many recovery codes an enrolment issues.
RECOVERY_CODES = 10

#: Characters per code, before grouping. Twenty base32 characters is about 100
#: bits - far beyond guessing, and still short enough to write on paper.
RECOVERY_LENGTH = 20

#: Unambiguous alphabet: no 0/O, no 1/I/L. These are read off a screen and
#: typed back weeks later, and "the code is wrong" is the least useful error
#: message a person can be given about their own handwriting.
RECOVERY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

#: Roles that cannot sign in without a second factor. The ones that can send an
#: order or connect a broker - the two things that reach money.
REQUIRED_PERMISSIONS = frozenset({Permission.EXECUTE, Permission.BROKER_MANAGE})


def required_for(role: UserRole) -> bool:
    """Whether this role must enrol before it can sign in.

    Derived from the permission table rather than listed, so a role given
    EXECUTE tomorrow inherits the requirement without anybody remembering to
    add it here.
    """
    held = ROLE_PERMISSIONS.get(role, set())
    return bool(REQUIRED_PERMISSIONS & set(held))


@dataclass(frozen=True)
class Enrolment:
    """What the browser needs to show, and nothing it should keep."""

    secret: str
    uri: str
    manual_entry: str
    account: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "secret": self.secret,
            "otpauth_uri": self.uri,
            "manual_entry": self.manual_entry,
            "account": self.account,
            "issuer": ISSUER,
            "digits": totp.DIGITS,
            "period": totp.STEP,
            "note": (
                "scan the QR or type the manual entry, then send a code from "
                "the app to confirm. Nothing is protected until you do"
            ),
        }


@dataclass(frozen=True)
class Status:
    """Where this account stands with its second factor."""

    enrolled: bool
    required: bool
    started: bool
    recovery_codes_left: int

    @property
    def blocking_sign_in(self) -> bool:
        """Required and not finished. The state that stops a sign-in, and the
        only one the login page has to do anything different about."""
        return self.required and not self.enrolled

    def as_dict(self) -> dict[str, Any]:
        return {
            "enrolled": self.enrolled,
            "required": self.required,
            "started": self.started,
            "recovery_codes_left": self.recovery_codes_left,
            "blocking_sign_in": self.blocking_sign_in,
        }


def status(session: Session, user: User) -> Status:
    """Where this account stands, as one query rather than two."""
    unused = session.scalar(
        select(func.count())
        .select_from(RecoveryCode)
        .where(RecoveryCode.user_id == user.id)
        .where(RecoveryCode.used_at.is_(None))
    )
    count = int(unused or 0)
    return Status(
        enrolled=user.totp_confirmed_at is not None,
        required=required_for(UserRole(user.role)),
        started=bool(user.totp_secret),
        recovery_codes_left=count,
    )


def begin(session: Session, user: User) -> Enrolment:
    """Issue a secret and the URI an app scans. Confirms nothing.

    Re-issued on every call while unconfirmed, so somebody who abandoned an
    enrolment halfway gets a clean one rather than a QR that half-matches
    whatever is still in their phone. Once confirmed, this refuses: replacing a
    working secret is a thing that should require proving you hold the current
    one.
    """
    if user.totp_confirmed_at is not None:
        raise ValidationFailedError(
            "This account already has a second factor. Remove it first, which "
            "needs a current code."
        )

    secret = totp.generate_secret()
    user.totp_secret = secret
    user.totp_last_step = None
    session.flush()

    return Enrolment(
        secret=secret,
        uri=totp.enrolment_uri(secret, account=user.email, issuer=ISSUER),
        manual_entry=totp.grouped(secret),
        account=user.email,
    )


def confirm(
    session: Session, user: User, code: str, *, now: datetime | None = None
) -> list[str]:
    """Finish enrolment and return the recovery codes, once.

    The plaintext codes are returned here and never again - only hashes are
    stored. A caller that does not show them has cost the user their way back
    in, which is why this returns them rather than writing them anywhere.
    """
    moment = now or datetime.now(UTC)

    if not user.totp_secret:
        raise ValidationFailedError("This account has not started enrolling.")
    if user.totp_confirmed_at is not None:
        raise ValidationFailedError("This account is already enrolled.")

    step = totp.verify(user.totp_secret, code, at=moment.timestamp())
    if step is None:
        raise ValidationFailedError(
            "That code does not match. Check the time on the phone - a clock "
            "more than a minute out produces codes that look right and are not."
        )

    user.totp_confirmed_at = moment
    user.totp_last_step = step
    codes = _issue_recovery_codes(session, user, now=moment)
    session.flush()
    return codes


def check(
    session: Session, user: User, code: str, *, now: datetime | None = None
) -> str:
    """Verify a code at sign-in. Returns how it was satisfied.

    Either "totp" or "recovery". Reported rather than swallowed, because a
    sign-in that spent a recovery code is a thing the owner should see in the
    security log - it usually means somebody lost a phone, and occasionally
    means somebody else has the codes.

    Raises `AuthenticationError`, not a validation error: this is a failed
    authentication and belongs in the same shape as a wrong password.
    """
    moment = now or datetime.now(UTC)

    if user.totp_confirmed_at is None or not user.totp_secret:
        raise AuthenticationError("This account has no second factor to check.")

    step = totp.verify(
        user.totp_secret, code, at=moment.timestamp(), last_step=user.totp_last_step
    )
    if step is not None:
        # Recorded before returning. A code is valid for its whole window, and
        # this is what stops the same six digits working twice.
        user.totp_last_step = step
        session.flush()
        return "totp"

    if _spend_recovery_code(session, user, code, now=moment):
        return "recovery"

    raise AuthenticationError("That code is not valid.")


def disable(
    session: Session, user: User, code: str, *, now: datetime | None = None
) -> None:
    """Turn the second factor off, having proved it is held.

    The proof is the point. A stolen session is exactly what a second factor
    exists to survive, and one that could remove the factor would survive
    nothing.
    """
    if user.totp_confirmed_at is None:
        raise ValidationFailedError("This account has no second factor.")

    check(session, user, code, now=now)

    user.totp_secret = None
    user.totp_confirmed_at = None
    user.totp_last_step = None
    _clear_recovery_codes(session, user)
    session.flush()


def reissue_recovery_codes(
    session: Session, user: User, code: str, *, now: datetime | None = None
) -> list[str]:
    """A fresh set, replacing every old one, having proved the factor is held.

    Whole sets only. Somebody with three left who is handed seven more cannot
    tell which of the ten on their screen still work.
    """
    if user.totp_confirmed_at is None:
        raise ValidationFailedError("This account has no second factor.")

    check(session, user, code, now=now)
    return _issue_recovery_codes(session, user, now=now or datetime.now(UTC))


def _new_recovery_code() -> str:
    body = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_LENGTH))
    return "-".join(body[i : i + 5] for i in range(0, len(body), 5))


def _digest_recovery(code: str) -> str:
    """SHA-256, not PBKDF2, and for the reason `sessions_auth` gives about
    session tokens: PBKDF2 exists to make guessing a *human-chosen* secret
    slow. A recovery code is twenty characters drawn from a 31-symbol alphabet
    - about 99 bits - and no amount of stretching moves a number that size into
    reach.

    What stretching does buy here is cost on the wrong side. Enrolment hashes
    ten codes, and `_spend_recovery_code` compares every unused one on every
    attempt to keep the timing flat: at password-grade iterations that is
    seconds of CPU on a path somebody reaches for when they have already lost
    their phone.
    """
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _normalise_recovery(code: str) -> str:
    """One spelling. These are typed off paper, with whatever spacing the
    person used, and refusing a correct code over a hyphen is refusing the
    thing they were told to write down."""
    return "".join(ch for ch in (code or "").upper() if ch in RECOVERY_ALPHABET)


def _issue_recovery_codes(session: Session, user: User, *, now: datetime) -> list[str]:
    _clear_recovery_codes(session, user)
    plain = [_new_recovery_code() for _ in range(RECOVERY_CODES)]
    for code in plain:
        session.add(
            RecoveryCode(
                user_id=user.id,
                issued_at=now,
                code_hash=_digest_recovery(_normalise_recovery(code)),
            )
        )
    session.flush()
    return plain


def _clear_recovery_codes(session: Session, user: User) -> None:
    for row in session.scalars(
        select(RecoveryCode).where(RecoveryCode.user_id == user.id)
    ):
        session.delete(row)
    session.flush()


def _spend_recovery_code(
    session: Session, user: User, code: str, *, now: datetime
) -> bool:
    """Find an unused code matching, stamp it, and say whether one did.

    Every unused code is compared even after a match would have been found, so
    the time this takes does not depend on which code was right or on how many
    are left.
    """
    candidate = _normalise_recovery(code)
    if len(candidate) != RECOVERY_LENGTH:
        return False
    wanted = _digest_recovery(candidate)

    matched: RecoveryCode | None = None
    for row in session.scalars(
        select(RecoveryCode)
        .where(RecoveryCode.user_id == user.id)
        .where(RecoveryCode.used_at.is_(None))
    ):
        if hmac.compare_digest(row.code_hash, wanted) and matched is None:
            matched = row

    if matched is None:
        return False

    matched.used_at = now
    session.flush()
    return True


def user_for(session: Session, user_id: uuid.UUID) -> User | None:
    return session.get(User, user_id)
