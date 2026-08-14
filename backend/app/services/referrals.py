"""Referral codes, the tree they build, and the points they pay.

The whole design turns on one question: what stops a referrer from registering
their own downline and collecting? Everything else here follows from the
answer.

**Points are paid on verification, never on registration.** Registering costs
nothing and proves nothing. Verifying proves control of a real inbox, which is
the cheapest thing available here that a referrer cannot produce on demand for
a hundred fake accounts.

**A referral is set once and never rewritten.** If it could be edited later,
the code would become a field somebody points at whoever is paying best this
week, and the tree would stop describing who actually introduced whom.

**Self-referral is refused**, including the loop where A refers B and B then
refers A. A cycle in the tree is not a clever edge case; it is two people
paying each other for nothing.

**A code that does not exist is refused rather than ignored.** Silently
dropping a mistyped code means somebody registers believing their friend was
credited, and nobody finds out until the friend asks where their points went.

None of this makes the system abuse-proof - somebody with a hundred real inboxes
can still farm it. It makes abuse cost something, which is the honest goal.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.models.tenancy import User

#: Points the referrer receives when a referral is confirmed. One place, so the
#: number in the terms and the number paid cannot drift apart.
POINTS_PER_CONFIRMED_REFERRAL = 100

#: Points the new account receives for verifying. Paid whether or not anybody
#: referred them - verification is worth encouraging on its own, and tying the
#: only reward to arriving through a referral quietly punishes the people who
#: found the site by themselves.
POINTS_FOR_VERIFYING = 25

#: Unambiguous in speech and in handwriting. No O/0, no I/1/l: a code exists to
#: be read aloud and typed by somebody else, and the two characters people
#: confuse most are the two worth losing.
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8

#: How many times to retry on a collision before giving up. With 31^8 codes a
#: collision is vanishingly unlikely; looping forever on one would be a hang
#: nobody could diagnose.
_MAX_CODE_ATTEMPTS = 12


@dataclass(frozen=True)
class Standing:
    """One account's position in the tree, and what it has earned."""

    code: str
    points: int
    referred_by: str | None
    confirmed: bool
    invited_total: int
    invited_confirmed: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "points": self.points,
            "referred_by": self.referred_by,
            "referral_confirmed": self.confirmed,
            "invited": {
                "total": self.invited_total,
                "confirmed": self.invited_confirmed,
                # Stated rather than left to subtraction. "3 invited, 1
                # confirmed" reads as two unrelated numbers until the third is
                # spelled out.
                "awaiting_verification": self.invited_total - self.invited_confirmed,
            },
            "points_per_confirmed_referral": POINTS_PER_CONFIRMED_REFERRAL,
            "note": (
                "points are paid when an invited account verifies its address, "
                "not when it registers. Registering proves nothing and costs "
                "nothing, which is exactly what makes it worth faking"
            ),
        }


def _generate(session: Session) -> str:
    for _ in range(_MAX_CODE_ATTEMPTS):
        code = "".join(secrets.choice(_ALPHABET) for _ in range(CODE_LENGTH))
        taken = session.scalar(select(User.id).where(User.referral_code == code))
        if taken is None:
            return code
    raise ConflictError(
        "Could not allocate a referral code after several attempts. That should "
        "be impossible with this alphabet, so treat it as a bug rather than as "
        "bad luck."
    )


def ensure_code(session: Session, user: User) -> str:
    """The account's own code, allocated on first use.

    Lazily rather than at creation, so accounts that existed before this feature
    get one the first time they look - a backfill migration that ran once would
    leave every later gap unfilled.
    """
    if not user.referral_code:
        user.referral_code = _generate(session)
        session.flush()
    return user.referral_code


def resolve_code(session: Session, code: str) -> User:
    """Find who a code belongs to, or refuse.

    Refused rather than ignored. Silently dropping a mistyped code means
    somebody registers believing their friend was credited, and nobody finds out
    until the friend asks where their points went.
    """
    cleaned = (code or "").strip().upper().replace("-", "").replace(" ", "")
    if not cleaned:
        raise ValidationFailedError("No referral code was given.")

    referrer = session.scalar(select(User).where(User.referral_code == cleaned))
    if referrer is None:
        raise NotFoundError(
            "No account has that referral code. Check it rather than continuing "
            "without one - registering with a code that does not exist credits "
            "nobody, and looks identical to registering with one that does."
        )
    if not referrer.is_active:
        raise ValidationFailedError("That referral code belongs to a closed account.")
    return referrer


def attach(session: Session, user: User, referrer: User) -> None:
    """Record who introduced whom. Once, and never rewritten."""
    if user.referred_by_id is not None:
        raise ConflictError(
            "This account already has a referrer, and that cannot be changed. "
            "A field that can be repointed later stops describing who actually "
            "introduced whom."
        )
    if referrer.id == user.id:
        raise ValidationFailedError("An account cannot refer itself.")
    if referrer.referred_by_id == user.id:
        # A refers B, then B refers A. Not a clever edge case - two people
        # paying each other for nothing.
        raise ValidationFailedError(
            "Those two accounts would refer each other, which credits both for "
            "introducing nobody."
        )

    user.referred_by_id = referrer.id
    session.flush()


def confirm(session: Session, user: User, *, now: datetime | None = None) -> dict[str, Any]:
    """Called when an account verifies its address. Pays out exactly once.

    Idempotent on `referral_confirmed_at`: a verification link clicked twice, or
    a retry after a timeout, must not pay twice. The stamp is the guard, not the
    caller's promise to only call this once.
    """
    moment = now or datetime.now(UTC)

    if user.referral_confirmed_at is not None:
        return {
            "confirmed": True,
            "already": True,
            "awarded": 0,
            "note": "this account was already confirmed, so nothing was paid again",
        }

    user.referral_confirmed_at = moment
    user.points = (user.points or 0) + POINTS_FOR_VERIFYING
    awarded_to_referrer = 0

    if user.referred_by_id is not None:
        referrer = session.get(User, user.referred_by_id)
        # An inactive referrer earns nothing. Paying a closed account is a
        # balance nobody can spend and a number that makes the totals wrong.
        if referrer is not None and referrer.is_active:
            referrer.points = (referrer.points or 0) + POINTS_PER_CONFIRMED_REFERRAL
            awarded_to_referrer = POINTS_PER_CONFIRMED_REFERRAL

    session.flush()
    return {
        "confirmed": True,
        "already": False,
        "awarded": POINTS_FOR_VERIFYING,
        "awarded_to_referrer": awarded_to_referrer,
    }


def standing(session: Session, user_id: uuid.UUID) -> Standing:
    """What one account has earned, and how its invitations are going."""
    user = session.get(User, user_id)
    if user is None:
        raise NotFoundError("No such user.")

    code = ensure_code(session, user)

    total = session.scalar(
        select(func.count()).select_from(User).where(User.referred_by_id == user.id)
    )
    confirmed = session.scalar(
        select(func.count())
        .select_from(User)
        .where(User.referred_by_id == user.id, User.referral_confirmed_at.is_not(None))
    )

    referrer_code = None
    if user.referred_by_id is not None:
        referrer = session.get(User, user.referred_by_id)
        # The referrer's code, not their address. Somebody's downline must not
        # be a way to read the email of the person above them.
        referrer_code = referrer.referral_code if referrer else None

    return Standing(
        code=code,
        points=user.points or 0,
        referred_by=referrer_code,
        confirmed=user.referral_confirmed_at is not None,
        invited_total=int(total or 0),
        invited_confirmed=int(confirmed or 0),
    )
