"""Should a real account be connected? The answer that is easy to get wrong.

Every operational check this deployment runs can be green while the thing
that decides whether it makes money has never been measured. A readiness
report that answered "yes" on operational health alone would be the most
expensive lie this project could tell, and the easiest - because everything
it measures well would be green.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.ops.real_money import Assessment, Finding, Verdict

NOW = datetime(2026, 9, 4, 2, 0, tzinfo=UTC)


def assessment(*findings: Finding) -> Assessment:
    return Assessment(at=NOW, findings=list(findings))


def ok(name: str) -> Finding:
    return Finding(name, True, "fine")


def defect(name: str) -> Finding:
    return Finding(name, False, "broken", blocks_connection=True)


def unproven(name: str) -> Finding:
    return Finding(name, False, "not measured yet", blocks_connection=False)


class TestTheMiddleVerdictExists:
    def test_sound_machinery_with_no_proven_edge_is_not_ready(self):
        """This is the whole reason for a third state. Two states would force
        this case into "ready", which is the lie."""
        report = assessment(ok("terminals"), ok("stops"), unproven("a brain beats its control"))

        assert report.verdict is Verdict.MECHANICALLY_READY
        assert "strategy is not" in report.headline

    def test_the_middle_verdict_is_not_a_softer_yes(self):
        report = assessment(ok("terminals"), unproven("a brain beats its control"))

        assert report.verdict is not Verdict.READY
        assert "will make any either" in report.headline

    def test_everything_measured_and_proven_is_ready(self):
        report = assessment(ok("terminals"), ok("stops"), ok("a brain beats its control"))

        assert report.verdict is Verdict.READY

    def test_a_defect_outranks_an_unproven_edge(self):
        """A naked stop costs money tonight; an unproven edge costs nothing
        by itself. The louder answer has to be the one that bleeds."""
        report = assessment(defect("stops"), unproven("a brain beats its control"))

        assert report.verdict is Verdict.NOT_READY
        assert "Do not connect" in report.headline


class TestTheTwoKindsOfFailureStayApart:
    def test_an_unproven_edge_is_not_listed_as_a_defect(self):
        """Otherwise "no proven edge" reads as "something is broken", and the
        operator goes looking for a fault that does not exist."""
        report = assessment(unproven("a brain beats its control"))

        assert report.defects == []
        assert len(report.unproven) == 1

    def test_a_defect_is_not_listed_as_merely_unproven(self):
        report = assessment(defect("stops"))

        assert len(report.defects) == 1
        assert report.unproven == []

    def test_both_are_reported_together(self):
        report = assessment(defect("stops"), unproven("a brain beats its control"))
        payload = report.as_dict()

        assert len(payload["defects"]) == 1
        assert len(payload["unproven"]) == 1
        assert len(payload["findings"]) == 2


class TestTheThresholdIsNotChosenToBeReachable:
    def test_it_corrects_for_testing_eight_brains(self):
        """1.96 is the single-hypothesis figure. Using it while running eight
        brains finds an edge in noise roughly one week in three."""
        from app.ops import real_money

        assert real_money.PROVEN_T > 1.96
        assert real_money.PROVEN_PAIRS >= 200
