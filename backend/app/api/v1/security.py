"""The security timeline over HTTP (spec §52, §66).

Behind `AUDIT_READ`, which is deliberately not part of `READ`. Everything else
this API publishes is a fact about the market or about the system's own
refusals; this is a record of people. It carries the addresses somebody signed
in from, the times they did it, and every account name an attacker has tried -
and a role created to look at charts has no business reading any of it.

The permission exists for a second reason too. An attacker who reaches a
viewer account should not be handed a list of which account names are real,
which is exactly what a readable failed-sign-in log is.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.core.enums import AuditEventType, Permission
from app.db.session import get_db
from app.services import login_guard, security_log

router = APIRouter(prefix="/security", tags=["security"])

AUDIT_READ = Depends(require(Permission.AUDIT_READ))


@router.get("/events")
def read_events(
    _: Principal = AUDIT_READ,
    hours: int = Query(default=168, ge=1, le=24 * 90),
    limit: int = Query(default=100, ge=1, le=1000),
    alarming_only: bool = Query(default=False),
    event: str | None = Query(default=None),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Who did what, from where, and whether it worked.

    Bounded by default - a week, a hundred rows. An unbounded default on a
    table that grows forever is a query that gets slower every day until
    somebody meets it as an outage.
    """
    wanted: tuple[AuditEventType, ...] | None = None
    if event:
        matched = [e for e in security_log.SECURITY_EVENTS if str(e) == event]
        # An unknown name returns nothing rather than everything. Silently
        # ignoring a filter is how a reader concludes there were no failed
        # sign-ins when they had simply mistyped the event name.
        wanted = tuple(matched)

    since = datetime.now(UTC) - timedelta(hours=hours)
    rows = security_log.recent(
        session,
        limit=limit,
        since=since,
        events=wanted,
        alarming_only=alarming_only,
    )
    return {
        "window_hours": hours,
        "count": len(rows),
        "events": [security_log.as_dict(row) for row in rows],
        "summary": security_log.summarise(rows),
        "known_events": [str(e) for e in security_log.SECURITY_EVENTS],
        "alarming_events": sorted(str(e) for e in security_log.ALARMING),
        "note": (
            "the timeline is bounded by `hours` and `limit`. Nothing here is "
            "a conclusion - a burst of failures is somebody guessing or "
            "somebody on holiday with the wrong password, and a count cannot "
            "tell them apart"
        ),
    }


@router.get("/sign-in-pressure")
def read_sign_in_pressure(
    _: Principal = AUDIT_READ,
    email: str = Query(default="", max_length=320),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """What the rate limiter currently thinks about one account.

    The question an owner actually has when they cannot sign in: *am I locked
    out, and for how long?* Answering it from the log means counting rows and
    reproducing the ladder by hand; this asks the limiter itself, so the
    answer is the same one the sign-in route will act on rather than a second
    implementation that agrees with it most of the time.
    """
    verdict = login_guard.check(session, email=email or "unknown", address=None)
    return {
        "email": login_guard.normalise(email) if email else None,
        **verdict.as_dict(),
        "thresholds": {
            "subject_failures_before_waiting": login_guard.SUBJECT_THRESHOLD,
            "address_failures_before_waiting": login_guard.ADDRESS_THRESHOLD,
            "proof_of_work_after": login_guard.HUMAN_CHECK_AFTER,
            "longest_account_wait_seconds": int(
                login_guard.SUBJECT_MAX_COOLDOWN.total_seconds()
            ),
            "window_minutes": int(login_guard.WINDOW.total_seconds() // 60),
        },
        "note": (
            "the account ladder is capped short on purpose. The kill switch is "
            "reached from the signed-in dashboard, so an hour of lockout is an "
            "hour of not being able to halt your own trading - and somebody "
            "who cannot guess the password can still cause it by failing"
        ),
    }
