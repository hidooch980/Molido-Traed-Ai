"""Repair, and the four things that must stay impossible.

A system that repairs itself can break itself, and the failure mode is worse
than the one it fixes: a restart loop that misread the cause takes down a
healthy service, and on a two-core host that takes the rest with it. So these
tests are mostly about what does not happen.

Nothing here restarts anything. `apply` takes the runner as an argument, so the
decision can be tested exactly as production makes it while the action itself
is a function that records - which is also why this module never holds the
ability to execute anything on its own.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.ops import incidents as incident_memory
from app.ops import self_healing

NOW = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


def raise_incident(session, source="collector", summary="worker stopped", severity="serious"):
    return incident_memory.record(
        session,
        incident_memory.Report(source=source, summary=summary, severity=severity),
        now=NOW,
    )


class Runner:
    """A runner that records instead of acting."""

    def __init__(self, succeeds=True):
        self.calls: list[str] = []
        self.succeeds = succeeds

    def __call__(self, action):
        self.calls.append(action.name)
        return self.succeeds, "recorded"


class TestNothingActsByDefault:
    def test_confirm_is_required(self, session):
        """A healer that acts because it was imported is a healer nobody chose
        to run."""
        incident = raise_incident(session)
        runner = Runner()

        result = self_healing.apply(session, incident.fingerprint, runner, now=NOW)

        assert result["attempted"] is False
        assert runner.calls == []
        assert "confirm=True is required" in result["reason"]

    def test_planning_never_acts(self, session):
        """`plan` exists so a person can read the decision without a container
        being restarted to find out what it would be."""
        incident = raise_incident(session)

        decision = self_healing.plan(session, incident.fingerprint, now=NOW)

        assert decision.allowed is True
        assert decision.action.name == "restart_collector"


class TestOnlyReversibleActions:
    def test_every_catalogued_action_is_reversible(self):
        """An irreversible action does not belong in a table something else
        decides when to run."""
        assert all(action.reversible for action in self_healing.CATALOGUE.values())

    def test_every_action_states_why_it_is_safe(self):
        """The sentence is the review. An action whose justification cannot be
        written in one line has not been thought about enough to run
        unattended."""
        assert all(len(action.why_safe) > 40 for action in self_healing.CATALOGUE.values())

    def test_an_unrouted_source_gets_no_action(self, session):
        """The correct default for anything nobody has thought about."""
        incident = raise_incident(session, source="something_new")

        decision = self_healing.plan(session, incident.fingerprint, now=NOW)

        assert decision.allowed is False
        assert decision.action is None
        assert "nobody has thought about" in decision.reason

    def test_the_catalogue_cannot_be_reached_by_name_alone(self, session):
        """Routing is by incident source, not by a name a caller supplies. A
        caller that could name an action could pick one for the wrong
        problem."""
        incident = raise_incident(session, source="disk", summary="disk at 95%")

        decision = self_healing.plan(session, incident.fingerprint, now=NOW)

        assert decision.action.name == "prune_build_cache"


class TestTheBudget:
    def test_three_attempts_then_it_stops(self, session):
        """An unbounded healer facing something it cannot fix does not fail -
        it loops, and the loop is indistinguishable from the outage."""
        incident = raise_incident(session)
        runner = Runner()

        for _ in range(self_healing.MAX_ATTEMPTS_PER_WINDOW):
            self_healing.apply(
                session, incident.fingerprint, runner, confirm=True, now=NOW
            )

        blocked = self_healing.apply(
            session, incident.fingerprint, runner, confirm=True, now=NOW
        )

        assert len(runner.calls) == self_healing.MAX_ATTEMPTS_PER_WINDOW
        assert blocked["attempted"] is False
        assert "budget spent" in blocked["reason"]

    def test_the_budget_refills_after_the_window(self, session):
        incident = raise_incident(session)
        runner = Runner()
        for _ in range(self_healing.MAX_ATTEMPTS_PER_WINDOW):
            self_healing.apply(session, incident.fingerprint, runner, confirm=True, now=NOW)

        later = NOW + self_healing.ATTEMPT_WINDOW + timedelta(minutes=1)
        allowed = self_healing.apply(
            session, incident.fingerprint, runner, confirm=True, now=later
        )

        assert allowed["attempted"] is True

    def test_the_budget_survives_a_restart(self, session):
        """It is stored on the incident, not in memory. An in-memory counter
        resets on exactly the event most likely to be part of the loop."""
        incident = raise_incident(session)
        runner = Runner()
        for _ in range(self_healing.MAX_ATTEMPTS_PER_WINDOW):
            self_healing.apply(session, incident.fingerprint, runner, confirm=True, now=NOW)

        session.expire_all()
        decision = self_healing.plan(session, incident.fingerprint, now=NOW)

        assert decision.allowed is False
        assert decision.attempts_in_window == self_healing.MAX_ATTEMPTS_PER_WINDOW


class TestRecordedBeforeItActs:
    def test_the_attempt_is_written_before_the_action_runs(self, session):
        """A crash mid-repair must leave a trace, or the next reader diagnoses
        a system that has been restarting itself all night without knowing."""
        incident = raise_incident(session)
        seen: list[int] = []

        def runner(action):
            # By the time the action runs, the attempt is already recorded.
            seen.append(len(incident.details.get("repair_attempts", [])))
            return True, "ok"

        self_healing.apply(session, incident.fingerprint, runner, confirm=True, now=NOW)

        assert seen == [1]

    def test_a_failed_action_still_counts_against_the_budget(self, session):
        """Otherwise a repair that always fails retries forever."""
        incident = raise_incident(session)
        runner = Runner(succeeds=False)

        for _ in range(self_healing.MAX_ATTEMPTS_PER_WINDOW + 2):
            self_healing.apply(session, incident.fingerprint, runner, confirm=True, now=NOW)

        assert len(runner.calls) == self_healing.MAX_ATTEMPTS_PER_WINDOW


class TestVerification:
    def test_a_command_exiting_zero_is_not_repair(self, session):
        incident = raise_incident(session)
        runner = Runner(succeeds=True)

        result = self_healing.apply(
            session, incident.fingerprint, runner, confirm=True, now=NOW
        )

        assert result["command_succeeded"] is True
        assert result["verified"] is False
        assert incident.remedy_confirmed is False

    def test_the_remedy_is_confirmed_only_when_the_signal_clears(self, session):
        incident = raise_incident(session)
        self_healing.apply(session, incident.fingerprint, Runner(), confirm=True, now=NOW)

        incident_memory.clear(session, "collector", "worker stopped", now=NOW)

        assert incident.remedy_confirmed is True
        assert "attempted: restart the collector worker" in incident.remedy

    def test_a_resolved_incident_is_not_repaired_again(self, session):
        incident = raise_incident(session)
        incident_memory.clear(session, "collector", "worker stopped", now=NOW)
        runner = Runner()

        result = self_healing.apply(
            session, incident.fingerprint, runner, confirm=True, now=NOW
        )

        assert result["attempted"] is False
        assert runner.calls == []
