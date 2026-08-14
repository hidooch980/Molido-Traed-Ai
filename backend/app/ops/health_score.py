"""One number for the whole deployment, and the arithmetic behind it (spec §64).

A score is a summary, and every summary throws information away. This one is
built so that what it throws away is stated, and so that the two mistakes a
health score usually makes are impossible here.

The first mistake is averaging a blocker into irrelevance. Thirteen checks pass
and one blocking check fails, and a mean says 93% - a number that reads as
"nearly fine" about a system that must not trade. So a failed blocking check
caps the score outright rather than subtracting from it. Ninety-three with a
blocker is a lie; twenty-five with a blocker is a summary.

The second is scoring what was never measured. An unmeasured check is not a
passing one, and counting it either way invents a fact. Unmeasured checks are
excluded from the denominator and reported separately, so a system that has
stopped checking cannot climb toward a hundred by going blind.

The score is deliberately arithmetic on data that already exists - readiness
checks, open incidents, feed age. No new process, no new container, no new
poller. On a two-core box with 2GB free, a monitoring service that needs its
own memory is a cost paid to watch the thing it took memory from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.ops import incidents as incident_memory
from app.ops.readiness import Grade, ReadinessReport

#: What a failed check of each grade costs, when nothing is capping the score.
#: Blocking never reaches these - it caps instead - but it is listed so the
#: table is readable as one thing.
WEIGHTS: dict[Grade, int] = {
    Grade.BLOCKING: 100,
    Grade.IMPORTANT: 12,
    Grade.ADVISORY: 3,
}

#: The ceiling a failed blocking check imposes. Not zero: a deployment with a
#: blocker and everything else healthy is in a different position from one
#: where nothing works, and flattening both to zero throws away the distinction
#: that decides what to do next.
BLOCKED_CEILING = 25

#: What an open incident costs, by severity. Smaller than a failed check on
#: purpose - an incident is a thing that happened, a failed check is a thing
#: that is true right now.
INCIDENT_COST: dict[str, int] = {
    "critical": 15,
    "serious": 8,
    "warning": 3,
    "info": 0,
}

#: An incident nobody has seen for this long stops counting against the score.
#: It is still in the memory and still in the recurring list; it has simply
#: stopped being evidence about the present.
INCIDENT_HORIZON = timedelta(hours=24)


@dataclass
class Deduction:
    """One thing that cost the score points, and how many."""

    reason: str
    points: int
    kind: str

    def as_dict(self) -> dict[str, Any]:
        return {"reason": self.reason, "points": self.points, "kind": self.kind}


@dataclass
class HealthScore:
    score: int
    capped_by: str | None
    deductions: list[Deduction] = field(default_factory=list)
    unmeasured: list[str] = field(default_factory=list)
    checks_passed: int = 0
    checks_measured: int = 0
    open_incidents: int = 0

    @property
    def band(self) -> str:
        """A word for the number, because "72" alone tells nobody what to do.

        The boundaries are not decoration: `blocked` exists as its own band so
        a capped score can never be read as merely poor.
        """
        if self.capped_by is not None:
            return "blocked"
        if self.score >= 90:
            return "healthy"
        if self.score >= 70:
            return "degraded"
        if self.score >= 40:
            return "poor"
        return "failing"

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "band": self.band,
            "capped_by": self.capped_by,
            "deductions": [d.as_dict() for d in self.deductions],
            # Named rather than counted. "Three checks could not be measured"
            # sends nobody anywhere; the names do.
            "unmeasured": self.unmeasured,
            "checks_passed": self.checks_passed,
            "checks_measured": self.checks_measured,
            "open_incidents": self.open_incidents,
            "note": (
                "a failed blocking check caps the score rather than averaging "
                "into it: a mean would report 93% about a system that must not "
                "trade. Unmeasured checks are excluded from the denominator, so "
                "a deployment cannot climb toward 100 by going blind"
            ),
        }


def _unmeasured(check) -> bool:
    """Whether a check could not answer, as opposed to answering "no".

    Read from the evidence the check itself published. A check that says
    `available: false` or carries a reason and no verdict has not failed - it
    has abstained, and the difference is the whole point of this module.
    """
    evidence = check.evidence or {}
    if evidence.get("unavailable") is True:
        return True
    if evidence.get("available") is False:
        return True
    return bool(evidence.get("unmeasured"))


def compute(
    report: ReadinessReport,
    session: Session | None = None,
    *,
    now: datetime | None = None,
) -> HealthScore:
    """Score the deployment from checks that already ran.

    `session` is optional: the score works without incident memory, it just
    knows less. Requiring it would make the score unavailable exactly when the
    database is the thing that is broken.
    """
    moment = now or datetime.now(UTC)
    deductions: list[Deduction] = []
    unmeasured: list[str] = []
    capped_by: str | None = None

    measured = []
    for check in report.checks:
        if _unmeasured(check):
            unmeasured.append(check.name)
            continue
        measured.append(check)

    for check in measured:
        if check.passed:
            continue
        if check.grade is Grade.BLOCKING:
            # First blocker wins the cap. Listing the rest as deductions would
            # imply they add up to something; they do not, the system is
            # already stopped.
            capped_by = capped_by or check.name
            deductions.append(
                Deduction(
                    reason=f"{check.name}: {check.detail}",
                    points=0,
                    kind="blocking",
                )
            )
            continue
        cost = WEIGHTS[check.grade]
        deductions.append(
            Deduction(
                reason=f"{check.name}: {check.detail}",
                points=cost,
                kind=check.grade.value,
            )
        )

    open_count = 0
    if session is not None:
        for incident in incident_memory.open_incidents(session):
            if moment - incident.last_seen_at > INCIDENT_HORIZON:
                continue
            open_count += 1
            cost = INCIDENT_COST.get(incident.severity, 0)
            if cost:
                deductions.append(
                    Deduction(
                        reason=f"open incident: {incident.summary}",
                        points=cost,
                        kind=f"incident/{incident.severity}",
                    )
                )

    score = 100 - sum(d.points for d in deductions)
    score = max(0, min(100, score))
    if capped_by is not None:
        score = min(score, BLOCKED_CEILING)

    return HealthScore(
        score=score,
        capped_by=capped_by,
        deductions=sorted(deductions, key=lambda d: d.points, reverse=True),
        unmeasured=unmeasured,
        checks_passed=sum(1 for c in measured if c.passed),
        checks_measured=len(measured),
        open_incidents=open_count,
    )
