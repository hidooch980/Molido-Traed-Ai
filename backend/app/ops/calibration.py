"""Which score sources have earned the right to be believed, and on what.

`at_least_one_calibrated_source` was hard-coded to zero. Not because nothing
had been measured - the forward journal has recorded every brain's decision
beside a random control since the day it went live - but because nothing read
that record back and asked the calibration question of it.

The question is not "does this source have a probability column". None of the
brains emit one; they emit a side. The question a calibration answers is
whether a source's claims are borne out at the rate it implies, and for a
source that claims a direction the implied rate is "better than a coin on the
same bars". So a source is calibrated when, on observations it could not have
seen when it was designed:

  1. it has resolved at least `MIN_RESOLVED` entries, each beside its control;
  2. its hit rate exceeds the control's by more than the noise of the sample.

Out-of-sample by construction: the forward journal only contains decisions
made after the brain was deployed, on bars that did not exist when it was
written. The period is reported so the reader can see how much of it there is.

**Existing is not calibrated.** A source with forty resolved entries has a
sample, not a calibration, and is listed with the number it is short by.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.journal import ARM_CONTROL, ARM_RULE

#: Below this many resolved entries a hit rate has a standard error above
#: about 3.5 points, and a comparison inside that is a comparison of noise.
MIN_RESOLVED = 200

#: The rule must beat its control by this many standard errors of the
#: difference. 1.96 is one pre-registered comparison; each source here is
#: its own hypothesis, published before its data.
REQUIRED_Z = 1.96

#: Which version of this policy produced a result, recorded beside it.
VERSION = "forward-journal-vs-control-v1"


@dataclass(frozen=True)
class SourceCalibration:
    source: str
    resolved_rule: int
    resolved_control: int
    wins_rule: int
    wins_control: int
    mean_r_rule: float | None
    mean_r_control: float | None
    period_start: datetime | None
    period_end: datetime | None

    @property
    def hit_rate(self) -> float | None:
        return self.wins_rule / self.resolved_rule if self.resolved_rule else None

    @property
    def control_hit_rate(self) -> float | None:
        return self.wins_control / self.resolved_control if self.resolved_control else None

    @property
    def z(self) -> float | None:
        p1, p2 = self.hit_rate, self.control_hit_rate
        if p1 is None or p2 is None:
            return None
        n1, n2 = self.resolved_rule, self.resolved_control
        variance = p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2
        if variance <= 0:
            return None
        return (p1 - p2) / math.sqrt(variance)

    @property
    def sample_sufficient(self) -> bool:
        return min(self.resolved_rule, self.resolved_control) >= MIN_RESOLVED

    @property
    def calibrated(self) -> bool:
        z = self.z
        return self.sample_sufficient and z is not None and z >= REQUIRED_Z

    @property
    def shortfall(self) -> int:
        return max(0, MIN_RESOLVED - min(self.resolved_rule, self.resolved_control))

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "resolved_rule": self.resolved_rule,
            "resolved_control": self.resolved_control,
            "hit_rate": round(self.hit_rate, 4) if self.hit_rate is not None else None,
            "control_hit_rate": (
                round(self.control_hit_rate, 4) if self.control_hit_rate is not None else None
            ),
            "mean_r_rule": round(self.mean_r_rule, 4) if self.mean_r_rule is not None else None,
            "mean_r_control": (
                round(self.mean_r_control, 4) if self.mean_r_control is not None else None
            ),
            "z": round(self.z, 2) if self.z is not None else None,
            "required_z": REQUIRED_Z,
            "min_resolved": MIN_RESOLVED,
            "sample_sufficient": self.sample_sufficient,
            "shortfall": self.shortfall,
            "calibrated": self.calibrated,
            "period_start": self.period_start.isoformat() if self.period_start else None,
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "oos": "forward journal: every entry post-dates the source's deployment",
        }


@dataclass
class CalibrationReport:
    measured_at: datetime
    version: str = VERSION
    sources: list[SourceCalibration] = field(default_factory=list)

    @property
    def calibrated(self) -> list[SourceCalibration]:
        return [s for s in self.sources if s.calibrated]

    def as_dict(self) -> dict[str, Any]:
        return {
            "measured_at": self.measured_at.isoformat(),
            "version": self.version,
            "calibrated_sources": len(self.calibrated),
            "calibrated": [s.source for s in self.calibrated],
            "sources": [s.as_dict() for s in self.sources],
            "policy": (
                f"at least {MIN_RESOLVED} resolved entries per arm, and the rule's "
                f"hit rate above its control's by z >= {REQUIRED_Z}"
            ),
        }


def _aware(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def measure(session: Session, *, now: datetime | None = None) -> CalibrationReport:
    # Through the model rather than raw SQL so the timestamp type decodes the
    # period on every database: sqlite hands raw SQL back strings.
    from sqlalchemy import func, select

    from app.models.journal import JournalEntry as J

    moment = (now or datetime.now(UTC)).astimezone(UTC)
    report = CalibrationReport(measured_at=moment)
    by_source: dict[str, dict[str, Any]] = {}
    resolved = J.outcome.is_not(None)
    statement = (
        select(
            J.strategy,
            J.arm,
            func.count().filter(resolved),
            func.count().filter(J.outcome == "win"),
            func.avg(J.r_multiple).filter(resolved),
            func.min(J.opened_at),
            func.max(J.opened_at).filter(resolved),
        )
        .where(J.strategy.is_not(None))
        .group_by(J.strategy, J.arm)
    )
    for strategy, arm, resolved_n, wins, mean_r, first_at, last_at in session.execute(statement):
        resolved = resolved_n
        slot = by_source.setdefault(str(strategy), {})
        slot[str(arm)] = {
            "resolved": int(resolved or 0),
            "wins": int(wins or 0),
            "mean_r": float(mean_r) if mean_r is not None else None,
            "first_at": _aware(first_at),
            "last_at": _aware(last_at),
        }
    for source, arms in sorted(by_source.items()):
        rule = arms.get(ARM_RULE, {})
        control = arms.get(ARM_CONTROL, {})
        starts = [v for v in (rule.get("first_at"), control.get("first_at")) if v]
        ends = [v for v in (rule.get("last_at"), control.get("last_at")) if v]
        report.sources.append(
            SourceCalibration(
                source=source,
                resolved_rule=rule.get("resolved", 0),
                resolved_control=control.get("resolved", 0),
                wins_rule=rule.get("wins", 0),
                wins_control=control.get("wins", 0),
                mean_r_rule=rule.get("mean_r"),
                mean_r_control=control.get("mean_r"),
                period_start=min(starts) if starts else None,
                period_end=max(ends) if ends else None,
            )
        )
    return report


__all__ = [
    "MIN_RESOLVED",
    "REQUIRED_Z",
    "VERSION",
    "CalibrationReport",
    "SourceCalibration",
    "measure",
]
