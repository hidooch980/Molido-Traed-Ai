"""Proof that the caller spent something, before they may guess again (spec §52).

The "I am not a robot" box, without a third party.

**Why not hCaptcha, reCAPTCHA or Turnstile.** Each is an account to open, a
key to obtain and paste, and a request from the sign-in page of a private
trading system to a company that then knows the address of every person who
signs into it and when. The first two are the reason nobody would turn this
on; the third is a reason not to.

**What this actually proves, honestly.** Not that the caller is a person. It
proves the caller burned processor time - roughly a twentieth of a second per
attempt for a browser, which nobody notices, and the same twentieth of a second
per attempt for a script, which is the entire point. A guessing loop that ran
at a thousand attempts a second now runs at twenty, and pays for every one. A
determined attacker with hardware is not stopped by this and is not meant to
be; they are stopped by `login_guard`, which this exists to keep them inside.

The check is a hashcash: find a nonce such that the SHA-256 of `salt:nonce`
begins with `difficulty` zero bits. Verifying is one hash. Solving is 2^d on
average. That asymmetry is the whole mechanism, and it is the same one bitcoin
uses, which is to say it is old, understood and has no patent, licence or
account attached to it.

**Solutions are single-use.** A stateless signed challenge would be cheaper to
implement and would fail at the only thing that matters: solve once, replay the
solution on every request until it expires, and a two-minute window becomes two
minutes of unimpeded guessing. So a challenge is a row, and verifying spends
it.

**Difficulty rises with suspicion.** A first-time caller is asked for nothing.
Somebody who has failed a few times is asked for a cheap proof. Somebody who
has failed many times is asked for one that costs seconds. The ladder is short
because a proof that takes a person ten seconds is a proof they will not wait
for, and a login nobody can face using is a login that gets switched off.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import MolidoError
from app.models.human_checks import HumanChallenge

#: How long a challenge stays solvable. Long enough for a slow phone to finish
#: the hardest ladder rung, short enough that a stolen one is worthless.
LIFETIME = timedelta(minutes=5)

#: Leading zero bits at the bottom of the ladder. Sixteen is about 65,000
#: hashes: a few tens of milliseconds in a browser, and invisible.
BASE_DIFFICULTY = 16

#: The top of the ladder. Twenty bits is about a million hashes - still under a
#: second in a browser, and fifty times the cost of the base rung to a loop.
MAX_DIFFICULTY = 20

#: What the ladder is indexed by: recent failures, from `login_guard`.
#: One extra bit - a doubling of cost - per two failures past the point where
#: proof starts being asked for.
FAILURES_PER_BIT = 2

#: The forms this is used on. A proof solved for one must not be spendable on
#: another, or the cheapest form becomes the mint for all of them.
SIGN_IN = "sign-in"
REGISTER = "register"
CLAIM = "claim"


class HumanCheckError(MolidoError):
    """The proof was absent, wrong, expired or already spent. Which one is
    reported, because every one of them is a client bug in the ordinary case
    and an unexplained login failure is worse than a rude one."""

    code = "human_check_failed"
    http_status = 400


@dataclass(frozen=True)
class Challenge:
    """What the client is given, and everything it needs to solve it."""

    challenge_id: uuid.UUID
    salt: str
    difficulty: int
    purpose: str
    expires_at: datetime

    def as_dict(self) -> dict[str, object]:
        return {
            "challenge_id": str(self.challenge_id),
            "salt": self.salt,
            "difficulty": self.difficulty,
            "purpose": self.purpose,
            "expires_at": self.expires_at.isoformat(),
            "algorithm": "sha256",
            # Spelled out rather than assumed. A client that hashes the wrong
            # string fails in a way that looks like a wrong password.
            "instructions": (
                "find any nonce for which sha256(f'{salt}:{nonce}') has at "
                "least `difficulty` leading zero bits, then send "
                "{challenge_id, nonce}"
            ),
        }


def difficulty_for(failures: int) -> int:
    """How hard to make it, given how many times this caller has just failed."""
    if failures <= 0:
        return BASE_DIFFICULTY
    return min(BASE_DIFFICULTY + failures // FAILURES_PER_BIT, MAX_DIFFICULTY)


def leading_zero_bits(digest: bytes) -> int:
    """How many bits of zero the digest starts with.

    Bits rather than hex characters, so difficulty can be raised by a factor of
    two instead of a factor of sixteen. A ladder whose only steps are 16x is a
    ladder with one usable rung.
    """
    total = 0
    for byte in digest:
        if byte == 0:
            total += 8
            continue
        # `bit_length` of a non-zero byte is 8 minus its leading zeros.
        total += 8 - byte.bit_length()
        break
    return total


def solve(salt: str, difficulty: int, *, limit: int = 1 << 26) -> int:
    """Find a nonce. Here because the tests and the CLI need it, not the app.

    The browser does this in JavaScript. Having the reference implementation in
    the same module as the verifier is what keeps the two agreeing about what
    is hashed - a client and server that disagree by one colon produce a login
    that rejects every correct password.

    `limit` bounds the search so a difficulty set absurdly high in a test fails
    as a test rather than as a hang.
    """
    for nonce in range(limit):
        if leading_zero_bits(_digest(salt, nonce)) >= difficulty:
            return nonce
    raise HumanCheckError(
        "no nonce found within the search limit", difficulty=difficulty, limit=limit
    )


def _digest(salt: str, nonce: int | str) -> bytes:
    return hashlib.sha256(f"{salt}:{nonce}".encode()).digest()


def issue(
    session: Session,
    *,
    purpose: str,
    failures: int = 0,
    now: datetime | None = None,
) -> Challenge:
    """Hand out a challenge sized to how suspicious the caller looks."""
    moment = now or datetime.now(UTC)
    row = HumanChallenge(
        issued_at=moment,
        expires_at=moment + LIFETIME,
        salt=secrets.token_urlsafe(24),
        difficulty=difficulty_for(failures),
        purpose=purpose,
    )
    session.add(row)
    session.flush()
    return Challenge(
        challenge_id=row.id,
        salt=row.salt,
        difficulty=row.difficulty,
        purpose=row.purpose,
        expires_at=row.expires_at,
    )


def verify(
    session: Session,
    *,
    challenge_id: str | uuid.UUID | None,
    nonce: str | int | None,
    purpose: str,
    now: datetime | None = None,
) -> None:
    """Spend a challenge, or raise saying exactly why it could not be spent.

    Spends it on *every* outcome that identifies the challenge - wrong nonce
    included. Leaving a challenge alive after a failed solution would let a
    caller grind nonces against one issued challenge for its whole lifetime,
    which is the same as having no difficulty at all.
    """
    moment = now or datetime.now(UTC)

    if challenge_id is None or nonce is None:
        raise HumanCheckError("This form needs a completed human check.")

    try:
        identifier = uuid.UUID(str(challenge_id))
    except ValueError as bad:
        raise HumanCheckError("That human check is not one this server issued.") from bad

    row = session.scalar(select(HumanChallenge).where(HumanChallenge.id == identifier))
    if row is None:
        # Covers never-issued, already-spent and pruned alike. They are the
        # same instruction to the client: ask for a new one.
        raise HumanCheckError("That human check has been used already. Ask for a new one.")

    # Spent from here on, whatever the verdict.
    session.delete(row)
    session.flush()

    if row.purpose != purpose:
        raise HumanCheckError("That human check was issued for a different form.")

    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires <= moment:
        raise HumanCheckError("That human check expired. Ask for a new one.")

    if leading_zero_bits(_digest(row.salt, nonce)) < row.difficulty:
        raise HumanCheckError(
            "That human check was not solved.", difficulty=row.difficulty
        )


def prune(session: Session, *, now: datetime | None = None) -> int:
    """Delete challenges nobody can spend any more."""
    moment = now or datetime.now(UTC)
    result = session.execute(
        delete(HumanChallenge).where(HumanChallenge.expires_at < moment)
    )
    return int(getattr(result, "rowcount", 0) or 0)
