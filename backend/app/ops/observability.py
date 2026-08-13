"""Metrics, SLOs and the audit trail (spec phases 37 and 49, §39 and §66).

Three things that get built badly and are cheap to build well.

**A metric that cannot be absent.** Every gauge here distinguishes "measured
zero" from "never reported". A dashboard showing 0 errors because the error
counter was never wired looks exactly like a dashboard showing 0 errors because
there were none, and the second is the one people assume.

**An SLO with no window.** "99.9% availability" is not a target until it says
over what period and out of how many observations. An objective evaluated on
four requests is not met or missed; it is unmeasured, and this module says so
rather than reporting 100%.

**An audit trail that can be edited.** The trail exists for the moments when
somebody wants to know what the system did before it went wrong, which are
exactly the moments when a mutable log is worth nothing. Entries here are
append-only and chained: each carries the hash of the one before it, so a
removed or altered entry breaks the chain at a verifiable point.

The disaster-recovery record at the bottom is phase 37's actual requirement,
and it is deliberately not a backup log. A backup nobody restored is a file of
unknown contents; the only evidence that a backup works is a restore that
happened, so `RestoreDrill` records restores and `recovery_posture` refuses to
call an untested backup a recovery capability.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.errors import ValidationFailedError

# Below this many observations an availability or latency objective is not
# being measured, it is being sampled by accident.
MIN_SLO_OBSERVATIONS = 100

# How old a restore drill may be before the backup is no longer evidence of
# anything. Thirty days is policy, published in the payload.
MAX_DRILL_AGE = timedelta(days=30)


@dataclass
class Gauge:
    """One measurement, or the explicit fact that it was never taken."""

    name: str
    unit: str
    value: float | None = None
    observed_at: datetime | None = None
    samples: int = 0

    @property
    def reported(self) -> bool:
        return self.observed_at is not None

    def observe(self, value: float, *, at: datetime | None = None) -> None:
        if not math.isfinite(value):
            raise ValidationFailedError(f"{self.name} received a non-finite value")
        self.value = value
        self.observed_at = at or datetime.now(UTC)
        self.samples += 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "unit": self.unit,
            # Never coerced to 0. A counter that was never wired and a counter
            # that counted nothing are opposite facts, and only one of them is
            # good news.
            "value": self.value,
            "reported": self.reported,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "samples": self.samples,
        }


@dataclass
class SLO:
    """An objective, its window, and whether the window holds enough to judge."""

    name: str
    target: float
    window: timedelta
    unit: str = "ratio"
    higher_is_better: bool = True

    def evaluate(self, observations: list[float]) -> dict[str, Any]:
        if len(observations) < MIN_SLO_OBSERVATIONS:
            return {
                "name": self.name,
                "available": False,
                "reason": (
                    f"{len(observations)} observations in the window, below the "
                    f"{MIN_SLO_OBSERVATIONS} needed — an objective judged on this "
                    "many is unmeasured, not met"
                ),
                "observations": len(observations),
                "target": self.target,
            }

        achieved = statistics.fmean(observations)
        met = achieved >= self.target if self.higher_is_better else achieved <= self.target
        # The margin is signed toward "better", so a reader does not have to
        # remember which direction this particular objective runs in.
        margin = achieved - self.target if self.higher_is_better else self.target - achieved
        return {
            "name": self.name,
            "available": True,
            "met": met,
            "achieved": round(achieved, 6),
            "target": self.target,
            "margin": round(margin, 6),
            "unit": self.unit,
            "window_seconds": self.window.total_seconds(),
            "observations": len(observations),
        }


@dataclass(frozen=True)
class AuditEntry:
    """One recorded fact, chained to the one before it."""

    sequence: int
    at: datetime
    actor: str
    action: str
    detail: dict[str, Any]
    previous_hash: str
    entry_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "at": self.at.isoformat(),
            "actor": self.actor,
            "action": self.action,
            "detail": self.detail,
            "previous_hash": self.previous_hash,
            "hash": self.entry_hash,
        }


GENESIS_HASH = "0" * 64


class AuditTrail:
    """Append-only and chained, so tampering is detectable rather than merely discouraged.

    Chaining does not make the trail immutable — nothing in a process can do
    that. It makes an edit *provable*: changing an entry changes its hash, and
    every entry after it then references a hash that no longer exists. `verify`
    reports the first sequence where the chain breaks.
    """

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    @staticmethod
    def _hash(sequence: int, at: datetime, actor: str, action: str,
              detail: dict[str, Any], previous: str) -> str:
        material = json.dumps(
            {
                "sequence": sequence,
                "at": at.isoformat(),
                "actor": actor,
                "action": action,
                "detail": detail,
                "previous": previous,
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(material.encode()).hexdigest()

    def record(
        self,
        *,
        actor: str,
        action: str,
        detail: dict[str, Any] | None = None,
        at: datetime | None = None,
    ) -> AuditEntry:
        if not actor.strip():
            raise ValidationFailedError(
                "an audit entry with no actor records that something happened and "
                "nothing about who did it"
            )
        moment = at or datetime.now(UTC)
        if moment.tzinfo is None:
            raise ValidationFailedError("audit timestamps must be timezone-aware")

        sequence = len(self._entries)
        previous = self._entries[-1].entry_hash if self._entries else GENESIS_HASH
        payload = detail or {}
        entry = AuditEntry(
            sequence=sequence,
            at=moment,
            actor=actor,
            action=action,
            detail=payload,
            previous_hash=previous,
            entry_hash=self._hash(sequence, moment, actor, action, payload, previous),
        )
        self._entries.append(entry)
        return entry

    def verify(self) -> tuple[bool, int | None]:
        """`(intact, first broken sequence)`. The second is None when intact."""
        previous = GENESIS_HASH
        for entry in self._entries:
            expected = self._hash(
                entry.sequence, entry.at, entry.actor, entry.action,
                entry.detail, previous,
            )
            if entry.previous_hash != previous or entry.entry_hash != expected:
                return False, entry.sequence
            previous = entry.entry_hash
        return True, None

    def entries(self) -> list[AuditEntry]:
        return list(self._entries)

    def as_dict(self) -> dict[str, Any]:
        intact, broken_at = self.verify()
        return {
            "count": len(self._entries),
            "intact": intact,
            "broken_at": broken_at,
            "entries": [e.as_dict() for e in self._entries],
        }


# ------------------------------------------------------------ disaster recovery


@dataclass(frozen=True)
class RestoreDrill:
    """A restore that actually happened, with what it proved.

    `rows_verified` is required and must be positive. A restore that produced a
    running database nobody queried has demonstrated that a file decompresses,
    which is not the claim anyone wants to make about their backups.
    """

    performed_at: datetime
    backup_taken_at: datetime
    duration: timedelta
    rows_verified: int
    succeeded: bool
    notes: str = ""

    def __post_init__(self) -> None:
        if self.performed_at.tzinfo is None or self.backup_taken_at.tzinfo is None:
            raise ValidationFailedError("drill timestamps must be timezone-aware")
        if self.succeeded and self.rows_verified <= 0:
            raise ValidationFailedError(
                "a successful restore must have verified something — a database "
                "nobody queried proves only that a file decompresses"
            )

    @property
    def achieved_rpo(self) -> timedelta:
        """How much data the backup would have cost, had it been needed."""
        return self.performed_at - self.backup_taken_at


@dataclass
class RecoveryPosture:
    available: bool
    reason: str | None = None
    meets_objectives: bool = False
    latest_drill: datetime | None = None
    achieved_rpo_seconds: float | None = None
    achieved_rto_seconds: float | None = None
    findings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "reason": self.reason,
            "meets_objectives": self.meets_objectives,
            "latest_drill": self.latest_drill.isoformat() if self.latest_drill else None,
            "achieved_rpo_seconds": self.achieved_rpo_seconds,
            "achieved_rto_seconds": self.achieved_rto_seconds,
            "max_drill_age_days": MAX_DRILL_AGE.days,
            "findings": self.findings,
        }


def recovery_posture(
    drills: list[RestoreDrill],
    *,
    target_rpo: timedelta,
    target_rto: timedelta,
    now: datetime | None = None,
) -> RecoveryPosture:
    """Whether this deployment can actually recover, judged only on restores.

    Backups are not evidence. A backup nobody restored is a file of unknown
    contents, and the number of organisations that discovered this during the
    incident rather than before it is the reason this function takes drills and
    not backup jobs.
    """
    moment = now or datetime.now(UTC)
    successful = [d for d in drills if d.succeeded]

    if not successful:
        return RecoveryPosture(
            available=False,
            reason=(
                "no successful restore drill on record — untested backups are not a "
                "recovery capability, they are an assumption"
            ),
        )

    latest = max(successful, key=lambda d: d.performed_at)
    findings: list[str] = []

    age = moment - latest.performed_at
    if age > MAX_DRILL_AGE:
        findings.append(
            f"the last successful restore was {age.days} days ago, beyond the "
            f"{MAX_DRILL_AGE.days}-day limit — the schema has moved since"
        )

    achieved_rpo = latest.achieved_rpo
    if achieved_rpo > target_rpo:
        findings.append(
            f"the drill restored to a point {achieved_rpo.total_seconds() / 60:.0f} "
            f"minutes old, beyond the {target_rpo.total_seconds() / 60:.0f}-minute "
            "objective"
        )
    if latest.duration > target_rto:
        findings.append(
            f"the restore took {latest.duration.total_seconds() / 60:.0f} minutes, "
            f"beyond the {target_rto.total_seconds() / 60:.0f}-minute objective"
        )

    failed_since = [
        d for d in drills if not d.succeeded and d.performed_at > latest.performed_at
    ]
    if failed_since:
        findings.append(
            f"{len(failed_since)} restore drill(s) have failed since the last "
            "successful one — the capability is regressing, not holding"
        )

    return RecoveryPosture(
        available=True,
        meets_objectives=not findings,
        latest_drill=latest.performed_at,
        achieved_rpo_seconds=achieved_rpo.total_seconds(),
        achieved_rto_seconds=latest.duration.total_seconds(),
        findings=findings,
    )
