"""Production readiness, as code rather than as a document (phase 53, §74).

A readiness checklist in a markdown file is a list of things somebody believed
were true on the day they wrote it. This one runs. Every check inspects the
system as it actually is, so the answer moves when the system moves, and a
regression shows up as a failed check rather than as a stale tick.

The checks are graded, and the grading is the point:

**BLOCKING** — the deployment is not safe to trade with. An execution path with
no authentication, a kill switch that starts disengaged, a backup nobody
restored. None of these are opinions.

**IMPORTANT** — the deployment will work and will hurt when something goes
wrong. No log rotation, no retention, an unmeasured SLO.

**ADVISORY** — worth doing, costs nothing to defer.

Two deliberate refusals:

`assess` never reports "ready" from a partial inspection. A check that could not
run is a check that failed, because a readiness report that quietly skips the
thing it could not reach is precisely the report that says everything is fine.

And nothing here grades *profitability*. A system can pass every check in this
module and lose money: readiness is about whether the machine is safe to run,
not whether the strategy is worth running. Conflating the two would let a green
checklist read as a green light.

One principle governs this module, the evidence readers behind it and the
research registry beside it:

    The system must optimise for discovering whether the deployment is safe
    and whether an edge is real, not for producing a PASS or a PROVEN label.

A failed check is a finding. Making it pass by widening the check, guessing
the fact, or reading "unknown" as "fine" is not repair; it is deleting the
finding. If the result is negative, the negative result is the deliverable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any


class Grade(StrEnum):
    BLOCKING = "blocking"
    IMPORTANT = "important"
    ADVISORY = "advisory"


@dataclass
class Check:
    """One question about the deployment, and the evidence for the answer."""

    name: str
    grade: Grade
    passed: bool
    detail: str
    # Why this check exists at all. A checklist item nobody understands is one
    # that eventually gets ticked to make the list green.
    rationale: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "grade": self.grade.value,
            "passed": self.passed,
            "detail": self.detail,
            "rationale": self.rationale,
            "evidence": self.evidence,
        }


@dataclass
class ReadinessReport:
    checked_at: datetime
    checks: list[Check] = field(default_factory=list)

    @property
    def blocking_failures(self) -> list[Check]:
        return [c for c in self.checks if not c.passed and c.grade is Grade.BLOCKING]

    @property
    def important_failures(self) -> list[Check]:
        return [c for c in self.checks if not c.passed and c.grade is Grade.IMPORTANT]

    @property
    def safe_to_trade(self) -> bool:
        return not self.blocking_failures

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def total(self) -> int:
        return len(self.checks)

    def as_dict(self) -> dict[str, Any]:
        return {
            "checked_at": self.checked_at.isoformat(),
            "safe_to_trade": self.safe_to_trade,
            "blocking_failures": [c.name for c in self.blocking_failures],
            "important_failures": [c.name for c in self.important_failures],
            "passed": self.passed,
            "total": self.total,
            "checks": [c.as_dict() for c in self.checks],
            # Said on every report, because a green checklist is the easiest
            # thing in this system to mistake for permission.
            "note": (
                "this grades whether the machine is safe to run, not whether the "
                "strategy is worth running"
            ),
        }


@dataclass
class Deployment:
    """What the assessor is allowed to know about the running system.

    Every field is optional and `None` means "could not be determined", which
    fails its check. A readiness report assembled from partial information must
    not read as a passing one.
    """

    require_auth: bool | None = None
    execution_enabled: bool | None = None
    execution_dry_run: bool | None = None
    kill_switch_default_engaged: bool | None = None
    ungated_mutating_routes: list[str] | None = None
    log_rotation_configured: bool | None = None
    retention_configured: bool | None = None
    last_successful_restore: datetime | None = None
    disk_free_ratio: float | None = None
    data_age_bars: float | None = None
    calibrated_sources: int | None = None
    slo_observations: int | None = None
    audit_chain_intact: bool | None = None
    secrets_in_repository: list[str] | None = None
    broker_is_simulated: bool | None = None


def _check(
    name: str,
    grade: Grade,
    value: Any,
    predicate: Any,
    pass_detail: str,
    fail_detail: str,
    rationale: str,
) -> Check:
    """Build one check, treating an undeterminable value as a failure."""
    # A tuple with a None inside it is as undeterminable as a bare None. Without
    # this, a check on two facts silently decides on the one it happens to know.
    undeterminable = value is None or (
        isinstance(value, tuple) and any(item is None for item in value)
    )
    if undeterminable:
        return Check(
            name=name,
            grade=grade,
            passed=False,
            detail="could not be determined, which is not the same as satisfied",
            rationale=rationale,
        )
    passed = bool(predicate(value))
    return Check(
        name=name,
        grade=grade,
        passed=passed,
        detail=pass_detail if passed else fail_detail,
        rationale=rationale,
        evidence={"observed": value},
    )


def assess(
    deployment: Deployment,
    *,
    now: datetime,
    max_restore_age: timedelta = timedelta(days=30),
    min_disk_free: float = 0.15,
) -> ReadinessReport:
    """Grade a deployment against every check, and never skip one silently."""
    report = ReadinessReport(checked_at=now)

    # ------------------------------------------------------------- blocking
    report.checks.append(
        _check(
            "no_ungated_mutating_routes",
            Grade.BLOCKING,
            deployment.ungated_mutating_routes,
            lambda routes: len(routes) == 0,
            "every mutating route declares a permission",
            "a route can change state without a permission dependency",
            "an unauthenticated write is an action with no attributable actor",
        )
    )
    report.checks.append(
        _check(
            "auth_required_if_execution_enabled",
            Grade.BLOCKING,
            (deployment.execution_enabled, deployment.require_auth),
            lambda pair: pair[0] is False or pair[1] is True,
            "execution is off, or authentication is on",
            "execution is enabled while authentication is off",
            "an order placed by an unnamed caller cannot be reconstructed afterwards",
        )
    )
    report.checks.append(
        _check(
            "kill_switch_defaults_engaged",
            Grade.BLOCKING,
            deployment.kill_switch_default_engaged,
            lambda engaged: engaged is True,
            "the kill switch starts engaged",
            "the kill switch starts disengaged",
            "a switch that starts open protects nothing until somebody remembers it",
        )
    )
    report.checks.append(
        _check(
            "no_secrets_in_repository",
            Grade.BLOCKING,
            deployment.secrets_in_repository,
            lambda found: len(found) == 0,
            "no secret-shaped files are tracked",
            "secret-shaped files are tracked in the repository",
            "a committed secret is public from the moment it is pushed",
        )
    )
    report.checks.append(
        _check(
            "restore_drill_recent",
            Grade.BLOCKING,
            deployment.last_successful_restore,
            lambda when: now - when <= max_restore_age,
            "a restore was verified recently",
            "no recent successful restore — untested backups are an assumption",
            "the only evidence a backup works is a restore that happened",
        )
    )

    # ------------------------------------------------------------ important
    report.checks.append(
        _check(
            "log_rotation",
            Grade.IMPORTANT,
            deployment.log_rotation_configured,
            lambda on: on is True,
            "container logs rotate",
            "container logs are unbounded",
            "unbounded logs fill the disk describing work rather than doing it",
        )
    )
    report.checks.append(
        _check(
            "operational_retention",
            Grade.IMPORTANT,
            deployment.retention_configured,
            lambda on: on is True,
            "the operational tables have retention",
            "the operational tables grow without a ceiling",
            "ingestion_runs gains more rows per day than the market produces bars",
        )
    )
    report.checks.append(
        _check(
            "disk_headroom",
            Grade.IMPORTANT,
            deployment.disk_free_ratio,
            lambda ratio: ratio >= min_disk_free,
            "the volume has headroom for a build",
            "the volume is too full for the next build to succeed",
            "a build that fails for space reads as a broken deploy, not a full disk",
        )
    )
    report.checks.append(
        _check(
            "data_is_fresh",
            Grade.IMPORTANT,
            deployment.data_age_bars,
            lambda age: age <= 3.0,
            "the feed is current",
            "the feed is stale",
            "stale data means no new position, so a stale feed halts trading anyway",
        )
    )
    report.checks.append(
        _check(
            "audit_chain_intact",
            Grade.IMPORTANT,
            deployment.audit_chain_intact,
            lambda intact: intact is True,
            "the audit chain verifies",
            "the audit chain is broken",
            "a trail that cannot be verified answers nothing after an incident",
        )
    )
    report.checks.append(
        _check(
            "at_least_one_calibrated_source",
            Grade.IMPORTANT,
            deployment.calibrated_sources,
            lambda count: count >= 1,
            "at least one score source is calibrated",
            "no score source is calibrated, so every expected value refuses",
            "conviction is not probability, and an uncalibrated chain never trades",
        )
    )

    # ------------------------------------------------------------- advisory
    report.checks.append(
        _check(
            "slo_window_populated",
            Grade.ADVISORY,
            deployment.slo_observations,
            lambda count: count >= 100,
            "the SLO window holds enough observations to judge",
            "the SLO window is too thin to judge",
            "an objective measured on a handful of requests is unmeasured, not met",
        )
    )
    report.checks.append(
        _check(
            "dry_run_while_simulated",
            Grade.ADVISORY,
            (deployment.broker_is_simulated, deployment.execution_dry_run),
            lambda pair: not (pair[0] is True and pair[1] is False),
            "the broker and the dry-run flag agree",
            "the broker is simulated while dry run is off, so its fills will be "
            "recorded as trades that never happened",
            "a rehearsal nobody labelled becomes a track record nobody earned",
        )
    )

    return report
