"""One number for the deployment, and the two lies it must not tell.

A mean over checks reports 93% when thirteen pass and one blocker fails, which
reads as "nearly fine" about a system that must not trade. And counting an
unmeasured check as passing lets a deployment climb toward 100 by going blind.
Both are the ordinary way health scores are built, and both are what these
tests exist to prevent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.ops import incidents as incident_memory
from app.ops.health_score import BLOCKED_CEILING, compute
from app.ops.readiness import Check, Grade, ReadinessReport

NOW = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


def check(name, grade=Grade.ADVISORY, passed=True, detail="", **evidence):
    return Check(
        name=name,
        grade=grade,
        passed=passed,
        detail=detail or ("ok" if passed else "failed"),
        rationale="because",
        evidence=evidence,
    )


def report(*checks):
    return ReadinessReport(checked_at=NOW, checks=list(checks))


class TestABlockerCapsRatherThanAverages:
    def test_thirteen_passes_and_one_blocker_is_not_ninety_three(self, session):
        """The mistake this module exists to prevent. A mean would call this
        93% and somebody would read it as nearly fine."""
        checks = [check(f"fine-{i}") for i in range(13)]
        checks.append(check("cannot trade", grade=Grade.BLOCKING, passed=False))

        score = compute(report(*checks), session, now=NOW)

        assert score.score <= BLOCKED_CEILING
        assert score.capped_by == "cannot trade"

    def test_the_band_says_blocked_not_poor(self, session):
        """A capped score must never read as merely low. They call for
        different actions."""
        score = compute(
            report(check("cannot trade", grade=Grade.BLOCKING, passed=False)),
            session,
            now=NOW,
        )

        assert score.band == "blocked"

    def test_a_blocked_deployment_is_not_flattened_to_zero(self, session):
        """A blocker with everything else healthy is a different position from
        nothing working, and the difference decides what to do next."""
        healthy = [check(f"fine-{i}") for i in range(10)]
        blocked = compute(
            report(*healthy, check("blocked", grade=Grade.BLOCKING, passed=False)),
            session,
            now=NOW,
        )

        assert blocked.score > 0

    def test_only_the_first_blocker_is_named(self, session):
        """Listing every blocker as a separate deduction implies they add up.
        They do not - the system is already stopped."""
        score = compute(
            report(
                check("first", grade=Grade.BLOCKING, passed=False),
                check("second", grade=Grade.BLOCKING, passed=False),
            ),
            session,
            now=NOW,
        )

        assert score.capped_by == "first"


class TestUnmeasuredIsNotPassing:
    def test_an_unavailable_check_is_excluded_from_the_denominator(self, session):
        score = compute(
            report(check("measured"), check("blind", available=False)),
            session,
            now=NOW,
        )

        assert score.checks_measured == 1
        assert score.unmeasured == ["blind"]

    def test_going_blind_does_not_raise_the_score(self, session):
        """The failure mode: a check stops working, stops failing, and the
        number goes up."""
        failing = compute(
            report(check("thing", grade=Grade.IMPORTANT, passed=False)), session, now=NOW
        )
        blind = compute(
            report(check("thing", grade=Grade.IMPORTANT, passed=False, available=False)),
            session,
            now=NOW,
        )

        assert blind.score >= failing.score
        assert blind.unmeasured == ["thing"]
        assert blind.checks_measured == 0

    def test_unmeasured_checks_are_named_not_counted(self, session):
        """"Three checks could not be measured" sends nobody anywhere."""
        score = compute(
            report(check("alpha", available=False), check("beta", unmeasured=True)),
            session,
            now=NOW,
        )

        assert sorted(score.unmeasured) == ["alpha", "beta"]


class TestWeighting:
    def test_an_important_failure_costs_more_than_an_advisory_one(self, session):
        important = compute(
            report(check("x", grade=Grade.IMPORTANT, passed=False)), session, now=NOW
        )
        advisory = compute(
            report(check("x", grade=Grade.ADVISORY, passed=False)), session, now=NOW
        )

        assert important.score < advisory.score

    def test_a_perfect_deployment_scores_a_hundred(self, session):
        score = compute(report(check("a"), check("b"), check("c")), session, now=NOW)

        assert score.score == 100
        assert score.band == "healthy"

    def test_deductions_are_ordered_by_cost(self, session):
        """The reader needs the biggest thing first; a list in check order
        makes them hunt."""
        score = compute(
            report(
                check("small", grade=Grade.ADVISORY, passed=False),
                check("large", grade=Grade.IMPORTANT, passed=False),
            ),
            session,
            now=NOW,
        )

        assert score.deductions[0].points >= score.deductions[-1].points


class TestIncidentsCount:
    def test_an_open_critical_incident_lowers_the_score(self, session):
        incident_memory.record(
            session,
            incident_memory.Report(source="collector", summary="disk full", severity="critical"),
            now=NOW,
        )

        score = compute(report(check("fine")), session, now=NOW)

        assert score.score < 100
        assert score.open_incidents == 1

    def test_a_resolved_incident_does_not(self, session):
        incident_memory.record(
            session,
            incident_memory.Report(source="collector", summary="disk full", severity="critical"),
            now=NOW,
        )
        incident_memory.clear(session, "collector", "disk full", now=NOW)

        score = compute(report(check("fine")), session, now=NOW)

        assert score.score == 100

    def test_an_old_incident_stops_counting_against_the_present(self, session):
        """It stays in the memory and in the recurring list. It has simply
        stopped being evidence about now."""
        incident_memory.record(
            session,
            incident_memory.Report(source="collector", summary="disk full", severity="critical"),
            now=NOW,
        )

        score = compute(report(check("fine")), session, now=NOW + timedelta(days=3))

        assert score.score == 100
        assert score.open_incidents == 0

    def test_the_score_works_without_incident_memory(self, session):
        """Requiring the database would make the score unavailable exactly when
        the database is what is broken."""
        score = compute(report(check("fine")), None, now=NOW)

        assert score.score == 100
        assert score.open_incidents == 0
