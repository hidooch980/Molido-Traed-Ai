"""What stands between a password guess and the next one (spec §52).

Nothing did. `sessions_auth.sign_in` checked one password per request and
returned the same refusal for every kind of failure - which is correct, and is
the whole reason a guess costs nothing: the attacker learns one bit per try and
can try as fast as the network allows. An address and a wordlist were the
entire attack, and the only trace it left was a `last_login_at` that moved if
it worked.

**The account holder is never locked out for long, on purpose.** This system's
kill switch is reachable from the signed-in dashboard. A lockout that keeps the
owner from signing in for an hour is a lockout that keeps them from halting
their own trading for an hour, and an attacker who cannot guess the password
can still trigger that by failing on purpose. So the subject ladder is capped
at `SUBJECT_MAX_COOLDOWN` - long enough that guessing is hopeless, short enough
that being locked out is an inconvenience rather than an incident. The severe
ladder is on the *caller's address*, where locking the wrong person out costs
them a change of network and costs the owner nothing.

Two rules, counted separately, and the longest cooldown wins:

**By address.** Many accounts tried from one place is the shape of enumeration,
and there is no legitimate caller it describes. This one is allowed to bite
hard.

**By subject.** Many failures against one account is the shape of a targeted
guess. Capped, for the reason above.

Both are counted from the database rather than from memory. An in-process
counter is reset by every deploy, and - worse - a deployment running four
workers would have four counters, each allowing the full quota, which is the
same as raising the limit fourfold without saying so.

**Time is passed in, never read here.** Every function takes `now`. A guard
whose windows come from the clock inside it cannot be tested for the boundary
that matters: the attempt that arrives one second after a cooldown expires.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import MolidoError
from app.models.login_attempts import LoginAttempt

#: How far back a count reaches. Failures older than this are not evidence of
#: anything current - somebody mistyping a password last Tuesday should not
#: shorten their patience today.
WINDOW = timedelta(minutes=15)

#: Failures against one address before that address is asked to wait.
SUBJECT_THRESHOLD = 5

#: Failures from one caller before that caller is asked to wait. Higher than
#: the subject threshold because one household, one office or one phone network
#: is legitimately several people behind one address.
ADDRESS_THRESHOLD = 15

#: The wait, doubling with each failure past the threshold.
BASE_COOLDOWN = timedelta(seconds=30)

#: The cap on a subject cooldown. Deliberately short. Twenty guesses buys an
#: attacker roughly one attempt every ten minutes, which ends the attack; and
#: the owner locked out by somebody else's failures waits ten minutes to reach
#: their own kill switch rather than an hour.
SUBJECT_MAX_COOLDOWN = timedelta(minutes=10)

#: The cap on an address cooldown. Long, because no legitimate caller produces
#: this pattern and the cost of being wrong is a different network.
ADDRESS_MAX_COOLDOWN = timedelta(hours=1)

#: Failures after which a caller must prove they are not a script. Lower than
#: either threshold: asking for a proof of work is cheap for a person and
#: expensive for a loop, so it is worth asking before anybody is made to wait.
HUMAN_CHECK_AFTER = 3

#: The most times the base cooldown is doubled, whatever the failure count.
#: Not a policy limit - every cap above is reached by the seventh doubling -
#: but a guard against arithmetic: `2 ** 200` seconds is not a `timedelta`, and
#: the exception would come from inside the check that decides whether anybody
#: may sign in.
MAX_DOUBLINGS = 20

#: How long an attempt row can affect any answer. Anything older than the
#: window is already ignored by every count; this is the pruner's horizon, kept
#: longer than the window so a day's attempts stay readable while being
#: irrelevant to the decision.
RETENTION = timedelta(days=30)


class TooManyAttemptsError(MolidoError):
    """The caller must wait. Carries how long, because a refusal that does not
    say when to come back is indistinguishable from a broken login."""

    code = "too_many_attempts"
    http_status = 429


@dataclass(frozen=True)
class Verdict:
    """Whether this attempt may proceed, and what it must carry if it does."""

    allowed: bool
    retry_after: timedelta | None
    #: Whether a proof of work must accompany the attempt. True well before
    #: `allowed` goes false: the point is to make the loop expensive while a
    #: person is still barely inconvenienced.
    human_check_required: bool
    subject_failures: int
    address_failures: int
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "retry_after_seconds": (
                int(self.retry_after.total_seconds()) if self.retry_after else 0
            ),
            "human_check_required": self.human_check_required,
            "subject_failures": self.subject_failures,
            "address_failures": self.address_failures,
            "reason": self.reason,
        }


def normalise(email: str) -> str:
    """One spelling of an address, so a lockout cannot be stepped around by
    changing the case or adding a space."""
    return email.strip().lower()


def _cooldown(failures: int, threshold: int, cap: timedelta) -> timedelta | None:
    """The wait after `failures`, doubling past `threshold` and capped.

    Returns None below the threshold rather than a zero duration, so a caller
    cannot read "wait for no time" as "you are being throttled".
    """
    if failures < threshold:
        return None
    # Clamped before the doubling, not after. `2 ** 200` is a perfectly good
    # Python integer and a `timedelta` that raises OverflowError on
    # construction - so the cap below never runs, and the guard raises instead
    # of answering. That is the worst failure available here: this function is
    # consulted on every sign-in, and an exception in it is the door jamming
    # for everybody rather than one attempt being refused. Two hundred failures
    # in fifteen minutes is not a hypothetical shape; it is the shape of the
    # attack this module exists for.
    #
    # Any clamp above seven reaches every cap this module defines (30s doubled
    # seven times is over an hour); MAX_DOUBLINGS is set well above that so the
    # ladder is bounded by the caps rather than by this line.
    steps = min(failures - threshold, MAX_DOUBLINGS)
    seconds = BASE_COOLDOWN.total_seconds() * (2**steps)
    return min(timedelta(seconds=seconds), cap)


def _count_failures(
    session: Session, *, column, value: str, since: datetime
) -> tuple[int, datetime | None]:
    """How many failures for one key since an instant, and the latest one."""
    rows = session.execute(
        select(LoginAttempt.attempted_at)
        .where(column == value)
        .where(LoginAttempt.succeeded.is_(False))
        .where(LoginAttempt.attempted_at >= since)
        .order_by(LoginAttempt.attempted_at.desc())
    ).all()
    if not rows:
        return 0, None
    return len(rows), rows[0][0]


def _as_utc(moment: datetime) -> datetime:
    """SQLite hands back naive datetimes; Postgres hands back aware ones.

    Comparing the two raises, and it would raise inside the guard - which is
    the one place in this system where an exception means the door opens or
    jams rather than a page failing to render.
    """
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def check(
    session: Session,
    *,
    email: str,
    address: str | None,
    now: datetime | None = None,
) -> Verdict:
    """May this attempt be tried at all, and what must it carry?

    Called before the password is read. A guard consulted after the check has
    already run is not a guard - it is a log.
    """
    moment = now or datetime.now(UTC)
    since = moment - WINDOW
    subject = normalise(email)

    subject_failures, subject_last = _count_failures(
        session, column=LoginAttempt.subject, value=subject, since=since
    )

    # Skipped when the address is unknown. Counting every proxied caller in one
    # bucket would lock out the whole deployment the first time anybody
    # mistyped a password fifteen times.
    address_failures, address_last = (0, None)
    if address:
        address_failures, address_last = _count_failures(
            session, column=LoginAttempt.address, value=address, since=since
        )

    waits: list[tuple[timedelta, str]] = []
    subject_wait = _cooldown(subject_failures, SUBJECT_THRESHOLD, SUBJECT_MAX_COOLDOWN)
    if subject_wait is not None and subject_last is not None:
        remaining = _as_utc(subject_last) + subject_wait - moment
        if remaining > timedelta(0):
            waits.append((remaining, "too many failed attempts for this account"))

    address_wait = _cooldown(address_failures, ADDRESS_THRESHOLD, ADDRESS_MAX_COOLDOWN)
    if address_wait is not None and address_last is not None:
        remaining = _as_utc(address_last) + address_wait - moment
        if remaining > timedelta(0):
            waits.append((remaining, "too many failed attempts from this address"))

    human_check = max(subject_failures, address_failures) >= HUMAN_CHECK_AFTER

    if waits:
        longest, why = max(waits, key=lambda pair: pair[0])
        return Verdict(
            allowed=False,
            retry_after=longest,
            human_check_required=True,
            subject_failures=subject_failures,
            address_failures=address_failures,
            reason=why,
        )

    return Verdict(
        allowed=True,
        retry_after=None,
        human_check_required=human_check,
        subject_failures=subject_failures,
        address_failures=address_failures,
        reason="within limits",
    )


def enforce(
    session: Session,
    *,
    email: str,
    address: str | None,
    now: datetime | None = None,
) -> Verdict:
    """`check`, but raising when the answer is no.

    The error says how long to wait. A refusal that does not is
    indistinguishable from a login that is simply broken, and the person who
    cannot tell them apart is the account holder.
    """
    verdict = check(session, email=email, address=address, now=now)
    if not verdict.allowed:
        raise TooManyAttemptsError(
            "Too many sign-in attempts. Try again shortly.",
            retry_after_seconds=int((verdict.retry_after or timedelta()).total_seconds()),
            reason=verdict.reason,
        )
    return verdict


def record(
    session: Session,
    *,
    email: str,
    address: str | None,
    succeeded: bool,
    user_id=None,
    reason: str | None = None,
    user_agent: str | None = None,
    now: datetime | None = None,
) -> LoginAttempt:
    """Write down what happened, whichever way it went.

    Successes are recorded too. A table of failures alone cannot answer the
    question an owner actually asks after a scare - "did anybody get in?" - and
    that is the question the table exists for.
    """
    attempt = LoginAttempt(
        attempted_at=now or datetime.now(UTC),
        subject=normalise(email),
        address=address,
        succeeded=succeeded,
        user_id=user_id,
        reason=reason,
        # Truncated rather than rejected: a client sending a long agent string
        # is not an attack, and failing the write would turn a cosmetic detail
        # into a failed sign-in.
        user_agent=(user_agent or "")[:256] or None,
    )
    session.add(attempt)
    session.flush()
    return attempt


def clear(session: Session, *, email: str) -> int:
    """Forget one account's failures. Called after a successful sign-in.

    Without this, five wrong attempts followed by the right one would leave the
    ladder standing: the next mistake would land on failure six and start a
    cooldown against somebody who has just proved they own the account.
    """
    result = session.execute(
        delete(LoginAttempt)
        .where(LoginAttempt.subject == normalise(email))
        .where(LoginAttempt.succeeded.is_(False))
    )
    # `rowcount` lives on CursorResult; the ORM's execute() is typed as the
    # narrower Result, so it is read defensively rather than asserted.
    return int(getattr(result, "rowcount", 0) or 0)


def prune(session: Session, *, now: datetime | None = None) -> int:
    """Delete attempts too old to affect any answer or tell anybody anything."""
    moment = now or datetime.now(UTC)
    result = session.execute(
        delete(LoginAttempt).where(LoginAttempt.attempted_at < moment - RETENTION)
    )
    return int(getattr(result, "rowcount", 0) or 0)
