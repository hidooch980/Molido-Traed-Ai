"""Resilience, recovery and observability tests (phases 35-37, 49).

The failure mode this block exists for is a system that keeps answering while
the thing it depends on has stopped working, so most of these tests check that
it stops — and that it does not start again too eagerly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import ValidationFailedError
from app.ops import observability as obs
from app.ops import resilience as res

NOW = datetime(2026, 3, 12, 10, 0, tzinfo=UTC)


def monitor() -> res.StabilityMonitor:
    return res.StabilityMonitor(
        [
            res.Dependency("database", res.Level.HALTED),
            res.Dependency("broker", res.Level.READ_ONLY),
            res.Dependency("market_data", res.Level.DEGRADED),
        ]
    )


def settled(mon: res.StabilityMonitor, at: datetime = NOW) -> None:
    """Bring every dependency up and let the settle window elapse."""
    for name in ("database", "broker", "market_data"):
        mon.record(name, True, now=at - timedelta(minutes=5))


# =============================================================== the ladder
class TestTheDegradationLadder:
    def test_everything_healthy_permits_everything(self):
        mon = monitor()
        settled(mon)

        report = mon.report(now=NOW)

        assert report.level is res.Level.FULL
        assert report.permits("execute") is True

    def test_a_broken_feed_stops_new_risk_but_not_reading(self):
        mon = monitor()
        settled(mon)
        mon.record("market_data", False, detail="no bars for 40 minutes", now=NOW)

        report = mon.report(now=NOW)

        assert report.level is res.Level.DEGRADED
        assert report.permits("execute") is False
        assert report.permits("read") is True

    def test_the_worst_dependency_sets_the_level(self):
        mon = monitor()
        settled(mon)
        mon.record("market_data", False, now=NOW)
        mon.record("database", False, now=NOW)

        assert mon.report(now=NOW).level is res.Level.HALTED

    def test_a_halted_system_permits_nothing(self):
        mon = monitor()
        settled(mon)
        mon.record("database", False, now=NOW)

        report = mon.report(now=NOW)

        assert report.permits("read") is False
        assert report.as_dict()["permits"] == []

    def test_the_reason_names_the_dependency_and_its_cost(self):
        mon = monitor()
        settled(mon)
        mon.record("broker", False, detail="connection refused", now=NOW)

        report = mon.report(now=NOW)

        assert any("broker is down" in r and "read_only" in r for r in report.reasons)


class TestDescentIsFasterThanAscent:
    def test_one_failure_drops_the_level_immediately(self):
        mon = monitor()
        settled(mon)
        mon.record("market_data", False, now=NOW)

        assert mon.report(now=NOW).level is res.Level.DEGRADED

    def test_recovery_does_not_climb_on_the_first_success(self):
        """A dependency that failed a moment ago is a dependency that is failing."""
        mon = monitor()
        settled(mon)
        mon.record("market_data", False, now=NOW)
        mon.record("market_data", True, now=NOW + timedelta(seconds=1))

        report = mon.report(now=NOW + timedelta(seconds=2))

        assert report.level is res.Level.DEGRADED
        assert any("has not settled" in h for h in report.holding_back)

    def test_it_climbs_once_the_settle_window_has_passed(self):
        mon = monitor()
        settled(mon)
        mon.record("market_data", False, now=NOW)
        mon.record("market_data", True, now=NOW + timedelta(seconds=1))

        report = mon.report(now=NOW + timedelta(minutes=5))

        assert report.level is res.Level.FULL

    def test_a_flapping_dependency_never_climbs(self):
        mon = monitor()
        settled(mon)
        moment = NOW
        for _ in range(10):
            mon.record("market_data", False, now=moment)
            moment += timedelta(seconds=5)
            mon.record("market_data", True, now=moment)
            moment += timedelta(seconds=5)

        assert mon.report(now=moment).level is res.Level.DEGRADED

    def test_three_failures_in_a_row_open_the_circuit(self):
        mon = monitor()
        settled(mon)
        for _ in range(3):
            mon.record("broker", False, now=NOW)

        broker = next(
            d for d in mon.report(now=NOW).dependencies if d["name"] == "broker"
        )
        assert broker["circuit_open"] is True

    def test_one_failure_is_an_event_not_a_state(self):
        mon = monitor()
        settled(mon)
        mon.record("broker", False, now=NOW)

        broker = next(
            d for d in mon.report(now=NOW).dependencies if d["name"] == "broker"
        )
        assert broker["circuit_open"] is False

    def test_a_monitor_with_no_dependencies_is_refused(self):
        with pytest.raises(ValueError):
            res.StabilityMonitor([])

    def test_an_unknown_dependency_is_refused(self):
        with pytest.raises(KeyError):
            monitor().record("nope", True, now=NOW)


# ================================================================ recovery
class TestCrashRecovery:
    def test_a_clean_restart_with_nothing_outstanding_resumes(self):
        plan = res.plan_recovery(
            clean_shutdown=True,
            unresolved_orders=[],
            open_positions_believed=0,
            positions_reconciled=True,
            last_checkpoint=NOW - timedelta(minutes=1),
            now=NOW,
        )

        assert plan.may_resume is True
        assert plan.permitted_level is res.Level.FULL

    def test_an_unclean_stop_trusts_none_of_its_last_known_state(self):
        plan = res.plan_recovery(
            clean_shutdown=False,
            unresolved_orders=[],
            open_positions_believed=0,
            positions_reconciled=True,
            last_checkpoint=NOW - timedelta(minutes=1),
            now=NOW,
        )

        assert plan.may_resume is False
        assert any("last-known state" in q.question for q in plan.questions)

    def test_an_unresolved_order_blocks_resumption(self):
        plan = res.plan_recovery(
            clean_shutdown=True,
            unresolved_orders=["mld-abc"],
            open_positions_believed=0,
            positions_reconciled=True,
            last_checkpoint=NOW,
            now=NOW,
        )

        assert plan.may_resume is False
        assert any("may be live" in q.question for q in plan.questions)

    def test_unreconciled_positions_block_resumption(self):
        plan = res.plan_recovery(
            clean_shutdown=True,
            unresolved_orders=[],
            open_positions_believed=2,
            positions_reconciled=False,
            last_checkpoint=NOW,
            now=NOW,
        )

        assert plan.may_resume is False

    def test_a_stale_checkpoint_costs_work_not_correctness(self):
        """The database is authoritative and can be re-read."""
        plan = res.plan_recovery(
            clean_shutdown=True,
            unresolved_orders=[],
            open_positions_believed=0,
            positions_reconciled=True,
            last_checkpoint=NOW - timedelta(hours=3),
            now=NOW,
        )

        assert plan.may_resume is True
        assert any(q.topic == "checkpoint" and not q.blocking for q in plan.questions)

    def test_a_blocked_recovery_still_comes_back_readable(self):
        """Halting removes the one view an operator needs to resolve the questions."""
        plan = res.plan_recovery(
            clean_shutdown=False,
            unresolved_orders=["mld-abc"],
            open_positions_believed=1,
            positions_reconciled=False,
            last_checkpoint=None,
            now=NOW,
        )

        assert plan.permitted_level is res.Level.READ_ONLY

    def test_the_plan_answers_nothing(self):
        plan = res.plan_recovery(
            clean_shutdown=False, unresolved_orders=["x"], open_positions_believed=1,
            positions_reconciled=False, last_checkpoint=None, now=NOW,
        )

        assert plan.as_dict()["note"].endswith("it answers nothing")
        assert all(q.resolvable_by for q in plan.questions)


# ================================================================== gauges
class TestAMetricCanBeAbsent:
    def test_an_unreported_gauge_is_not_zero(self):
        """A counter nobody wired and a counter that counted nothing are opposites."""
        gauge = obs.Gauge("orders_rejected", "count")

        assert gauge.as_dict()["value"] is None
        assert gauge.as_dict()["reported"] is False

    def test_a_measured_zero_is_reported_as_zero(self):
        gauge = obs.Gauge("orders_rejected", "count")
        gauge.observe(0.0, at=NOW)

        assert gauge.as_dict()["value"] == 0.0
        assert gauge.as_dict()["reported"] is True

    def test_a_non_finite_observation_is_refused(self):
        with pytest.raises(ValidationFailedError):
            obs.Gauge("latency", "ms").observe(float("nan"))


class TestSLOsCarryTheirWindow:
    def test_too_few_observations_is_unmeasured_not_met(self):
        objective = obs.SLO("availability", 0.999, timedelta(days=30))

        result = objective.evaluate([1.0] * 4)

        assert result["available"] is False
        assert "unmeasured, not met" in result["reason"]

    def test_a_met_objective_reports_its_margin(self):
        objective = obs.SLO("availability", 0.99, timedelta(days=30))

        result = objective.evaluate([1.0] * 200)

        assert result["met"] is True
        assert result["margin"] > 0

    def test_a_missed_objective_reports_a_negative_margin(self):
        objective = obs.SLO("availability", 0.99, timedelta(days=30))

        result = objective.evaluate(([1.0] * 180) + ([0.0] * 20))

        assert result["met"] is False
        assert result["margin"] < 0

    def test_a_lower_is_better_objective_reads_the_same_way(self):
        """So a reader does not have to remember which way this one runs."""
        objective = obs.SLO(
            "p95_latency", 250.0, timedelta(days=1), unit="ms", higher_is_better=False
        )

        good = objective.evaluate([100.0] * 200)
        bad = objective.evaluate([400.0] * 200)

        assert good["met"] is True and good["margin"] > 0
        assert bad["met"] is False and bad["margin"] < 0


# ============================================================== audit trail
class TestTheAuditTrailIsChained:
    def test_entries_chain_to_their_predecessor(self):
        trail = obs.AuditTrail()
        first = trail.record(actor="operator", action="kill_switch.disengage", at=NOW)
        second = trail.record(actor="operator", action="order.submit", at=NOW)

        assert first.previous_hash == obs.GENESIS_HASH
        assert second.previous_hash == first.entry_hash

    def test_an_intact_trail_verifies(self):
        trail = obs.AuditTrail()
        for index in range(5):
            trail.record(actor="worker", action=f"step-{index}", at=NOW)

        assert trail.verify() == (True, None)

    def test_an_altered_entry_breaks_the_chain_at_a_named_point(self):
        trail = obs.AuditTrail()
        for index in range(5):
            trail.record(actor="worker", action=f"step-{index}", at=NOW)
        # Reaching into the private list is the point: this is the tampering
        # the chain exists to make detectable, not to make impossible.
        entries = trail._entries  # noqa: SLF001
        entries[2] = obs.AuditEntry(
            sequence=2, at=NOW, actor="worker", action="something-else",
            detail={}, previous_hash=entries[2].previous_hash,
            entry_hash=entries[2].entry_hash,
        )

        intact, broken_at = trail.verify()

        assert intact is False
        assert broken_at == 2

    def test_a_removed_entry_is_detected(self):
        trail = obs.AuditTrail()
        for index in range(5):
            trail.record(actor="worker", action=f"step-{index}", at=NOW)
        del trail._entries[2]  # noqa: SLF001

        assert trail.verify()[0] is False

    def test_an_entry_without_an_actor_is_refused(self):
        with pytest.raises(ValidationFailedError):
            obs.AuditTrail().record(actor="   ", action="order.submit", at=NOW)

    def test_a_naive_timestamp_is_refused(self):
        with pytest.raises(ValidationFailedError):
            obs.AuditTrail().record(
                actor="operator", action="x", at=datetime(2026, 3, 12, 10, 0)
            )


# ========================================================= disaster recovery
class TestOnlyRestoresCount:
    def test_no_drill_means_no_recovery_capability(self):
        """An untested backup is a file of unknown contents."""
        posture = obs.recovery_posture(
            [], target_rpo=timedelta(hours=1), target_rto=timedelta(hours=2), now=NOW
        )

        assert posture.available is False
        assert "assumption" in posture.reason

    def test_a_recent_successful_drill_meets_the_objectives(self):
        drill = obs.RestoreDrill(
            performed_at=NOW - timedelta(days=2),
            backup_taken_at=NOW - timedelta(days=2, minutes=20),
            duration=timedelta(minutes=25),
            rows_verified=1_200_000,
            succeeded=True,
        )

        posture = obs.recovery_posture(
            [drill], target_rpo=timedelta(hours=1), target_rto=timedelta(hours=2), now=NOW
        )

        assert posture.meets_objectives is True

    def test_an_old_drill_is_no_longer_evidence(self):
        drill = obs.RestoreDrill(
            performed_at=NOW - timedelta(days=200),
            backup_taken_at=NOW - timedelta(days=200, minutes=10),
            duration=timedelta(minutes=20),
            rows_verified=10,
            succeeded=True,
        )

        posture = obs.recovery_posture(
            [drill], target_rpo=timedelta(hours=1), target_rto=timedelta(hours=2), now=NOW
        )

        assert posture.meets_objectives is False
        assert any("schema has moved" in f for f in posture.findings)

    def test_a_slow_restore_misses_the_rto(self):
        drill = obs.RestoreDrill(
            performed_at=NOW - timedelta(days=1),
            backup_taken_at=NOW - timedelta(days=1, minutes=5),
            duration=timedelta(hours=9),
            rows_verified=500,
            succeeded=True,
        )

        posture = obs.recovery_posture(
            [drill], target_rpo=timedelta(hours=1), target_rto=timedelta(hours=2), now=NOW
        )

        assert any("beyond the 120-minute objective" in f for f in posture.findings)

    def test_failures_after_the_last_success_are_a_regression(self):
        good = obs.RestoreDrill(
            performed_at=NOW - timedelta(days=10),
            backup_taken_at=NOW - timedelta(days=10, minutes=5),
            duration=timedelta(minutes=20),
            rows_verified=100,
            succeeded=True,
        )
        bad = obs.RestoreDrill(
            performed_at=NOW - timedelta(days=1),
            backup_taken_at=NOW - timedelta(days=1, minutes=5),
            duration=timedelta(minutes=20),
            rows_verified=0,
            succeeded=False,
        )

        posture = obs.recovery_posture(
            [good, bad], target_rpo=timedelta(hours=1), target_rto=timedelta(hours=2), now=NOW
        )

        assert any("regressing" in f for f in posture.findings)

    def test_a_successful_restore_that_verified_nothing_is_refused(self):
        with pytest.raises(ValidationFailedError):
            obs.RestoreDrill(
                performed_at=NOW,
                backup_taken_at=NOW - timedelta(minutes=5),
                duration=timedelta(minutes=10),
                rows_verified=0,
                succeeded=True,
            )
