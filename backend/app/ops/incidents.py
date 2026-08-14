"""Record failures so the system stops solving them from scratch (spec §53, §66).

Four things read this module, and each one needs something the others do not:

  alerting     needs to know this is a repeat, and when it last spoke
  health score needs what is open right now, weighted by how bad it is
  bottlenecks  need what keeps coming back rather than what broke loudest
  self-healing needs what was tried last time and whether it actually worked

All four collapse without a stable identity for a failure, which is what
`fingerprint` is: the part of a problem that stays the same across occurrences,
with timestamps, ids and counts stripped out. Two occurrences share it or they
are different incidents. There is no third answer, and inventing one is how a
system ends up with four hundred rows describing one broken disk.

`remedy_confirmed` is the strictest thing here and deliberately so. A remedy is
credited only when the same fingerprint was seen again *after* it was applied
and then cleared. Marking it on the operator's say-so records a belief; marking
it on "the alert stopped" records a coincidence, because the alert also stops
when the checker dies.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.incidents import Incident

#: Ordered. Anything comparing severities uses the index, so a new level slots
#: in without every comparison having to learn about it.
SEVERITIES = ("info", "warning", "serious", "critical")

#: How long an alert stays quiet for one fingerprint. Long enough that a
#: flapping container does not page anybody every thirty seconds, short enough
#: that a real outage is not silent for an afternoon.
ALERT_COOLDOWN = timedelta(minutes=30)

#: What gets stripped before hashing. Times, ids and counts are exactly the
#: parts that make two occurrences of one problem look like two problems.
_VOLATILE = re.compile(
    r"""
    \d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?  # timestamps
    | \b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b       # uuids
    | \b\d+(\.\d+)?(ms|s|m|h)\b                                              # durations
    | \b\d{3,}\b                                                             # counts, ports, pids
    """,
    re.X | re.I,
)


def fingerprint(source: str, summary: str) -> str:
    """A stable identity for one kind of failure.

    Hashed rather than stored raw so the column has a fixed width and an index
    that behaves, and prefixed with the source so two subsystems reporting a
    similarly-worded problem stay apart - "connection refused" from the broker
    bridge and from the database are not the same incident.
    """
    skeleton = _VOLATILE.sub("#", summary.strip().lower())
    skeleton = re.sub(r"\s+", " ", skeleton)
    digest = hashlib.sha256(f"{source}|{skeleton}".encode()).hexdigest()[:24]
    return f"{source}:{digest}"


@dataclass(frozen=True)
class Report:
    """One observation of something being wrong."""

    source: str
    summary: str
    severity: str = "warning"
    details: dict[str, Any] | None = None

    def key(self) -> str:
        return fingerprint(self.source, self.summary)


def record(session: Session, report: Report, *, now: datetime | None = None) -> Incident:
    """Record an occurrence, creating the incident or counting against it.

    A repeat updates `last_seen_at` and increments the count. It also clears
    `resolved_at`: a problem that returns is open again, and leaving the old
    resolution in place would report a system as healthy while it is failing.
    """
    if report.severity not in SEVERITIES:
        raise ValueError(f"severity must be one of {SEVERITIES}, got {report.severity!r}")

    moment = now or datetime.now(UTC)
    key = report.key()
    incident = session.scalar(select(Incident).where(Incident.fingerprint == key))

    if incident is None:
        incident = Incident(
            fingerprint=key,
            source=report.source,
            summary=report.summary[:400],
            severity=report.severity,
            occurrences=1,
            first_seen_at=moment,
            last_seen_at=moment,
            details=report.details or {},
        )
        session.add(incident)
        session.flush()
        return incident

    incident.occurrences += 1
    incident.last_seen_at = moment
    # A returning problem is open again. Keeping the old resolution would let
    # the health score count a live failure as settled.
    incident.resolved_at = None
    # Severity can rise on a repeat but never falls silently: a warning that
    # became critical is news, and a critical that reports itself as a warning
    # once should not downgrade the record.
    if SEVERITIES.index(report.severity) > SEVERITIES.index(incident.severity):
        incident.severity = report.severity
    if report.details:
        incident.details = {**incident.details, **report.details}
    session.flush()
    return incident


def clear(
    session: Session, source: str, summary: str, *, now: datetime | None = None
) -> Incident | None:
    """Mark an incident resolved because its signal stopped being true.

    Called by whatever raised it, on the pass where the check succeeds. That is
    the only honest trigger: an operator pressing "resolved" records a belief,
    and a timer expiring records nothing at all.

    If a remedy was recorded before this clearance, it is confirmed here - the
    problem was seen again after the remedy and then went away, which is the
    weakest evidence worth calling evidence.
    """
    moment = now or datetime.now(UTC)
    key = fingerprint(source, summary)
    incident = session.scalar(select(Incident).where(Incident.fingerprint == key))
    if incident is None or incident.resolved_at is not None:
        return incident

    incident.resolved_at = moment
    if incident.remedy and not incident.remedy_confirmed:
        incident.remedy_confirmed = True
    session.flush()
    return incident


def record_remedy(
    session: Session, fingerprint_value: str, remedy: str
) -> Incident | None:
    """Note what was tried. Unconfirmed until the incident clears afterwards."""
    incident = session.scalar(
        select(Incident).where(Incident.fingerprint == fingerprint_value)
    )
    if incident is None:
        return None
    incident.remedy = remedy.strip()
    # Deliberately reset. A new remedy for a returning problem has not been
    # shown to work just because an older one was.
    incident.remedy_confirmed = False
    session.flush()
    return incident


def should_alert(
    session: Session, fingerprint_value: str, *, now: datetime | None = None
) -> tuple[bool, str]:
    """Whether to speak about this incident, and why not if not.

    The cooldown is stored on the row rather than held in memory, so it
    survives a restart - an in-memory cooldown forgets on the one event most
    likely to cause an alert storm.
    """
    moment = now or datetime.now(UTC)
    incident = session.scalar(
        select(Incident).where(Incident.fingerprint == fingerprint_value)
    )
    if incident is None:
        return False, "no such incident"
    if incident.resolved_at is not None:
        return False, "already resolved"
    if incident.last_alerted_at is None:
        return True, "first alert for this incident"

    quiet_until = incident.last_alerted_at + ALERT_COOLDOWN
    if moment < quiet_until:
        return False, (
            f"suppressed until {quiet_until.isoformat(timespec='seconds')}: "
            f"seen {incident.occurrences} times, last alerted "
            f"{incident.last_alerted_at.isoformat(timespec='seconds')}"
        )
    return True, "cooldown elapsed"


def mark_alerted(
    session: Session, fingerprint_value: str, *, now: datetime | None = None
) -> None:
    incident = session.scalar(
        select(Incident).where(Incident.fingerprint == fingerprint_value)
    )
    if incident is not None:
        incident.last_alerted_at = now or datetime.now(UTC)
        session.flush()


def open_incidents(session: Session) -> list[Incident]:
    return list(
        session.scalars(
            select(Incident)
            .where(Incident.resolved_at.is_(None))
            .order_by(Incident.last_seen_at.desc())
        )
    )


def known_remedies(session: Session, source: str | None = None) -> list[dict[str, Any]]:
    """Remedies that were actually followed by the problem going away.

    Unconfirmed ones are excluded rather than listed with a caveat. The point
    of this list is to be trusted at three in the morning, and a list mixing
    "this worked" with "somebody typed this once" is not.
    """
    query = select(Incident).where(
        Incident.remedy.is_not(None), Incident.remedy_confirmed.is_(True)
    )
    if source:
        query = query.where(Incident.source == source)
    return [
        {
            "fingerprint": incident.fingerprint,
            "source": incident.source,
            "summary": incident.summary,
            "remedy": incident.remedy,
            "occurrences": incident.occurrences,
            "last_seen_at": incident.last_seen_at.isoformat(),
        }
        for incident in session.scalars(query.order_by(Incident.occurrences.desc()))
    ]


def recurring(
    session: Session, *, minimum: int = 3, window: timedelta | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """What keeps coming back, which is rarely what broke loudest.

    A critical seen once is an event. A warning seen ninety times is a
    condition, and it is usually the one costing something - the loud failure
    already has somebody's attention.
    """
    moment = now or datetime.now(UTC)
    query = select(Incident).where(Incident.occurrences >= minimum)
    if window is not None:
        query = query.where(Incident.last_seen_at >= moment - window)

    return [
        {
            "fingerprint": incident.fingerprint,
            "source": incident.source,
            "summary": incident.summary,
            "severity": incident.severity,
            "occurrences": incident.occurrences,
            "open": incident.resolved_at is None,
            "first_seen_at": incident.first_seen_at.isoformat(),
            "last_seen_at": incident.last_seen_at.isoformat(),
            "has_confirmed_remedy": incident.remedy_confirmed,
        }
        for incident in session.scalars(query.order_by(Incident.occurrences.desc()))
    ]
