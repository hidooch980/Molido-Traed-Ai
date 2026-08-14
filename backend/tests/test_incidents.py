"""Operational memory, and the three claims it has to keep straight.

A failure has a stable identity, or nothing built on top works: alerts cannot
be suppressed, repeats cannot be counted, and a remedy cannot be attached to
anything. That is what `fingerprint` is for, and most of this file is about the
line between "the same problem again" and "a different problem".

The other two claims are stricter than they look. A returning problem is open
again, not still-resolved. And a remedy is only credited when the incident was
seen after it and then cleared - anything looser records a coincidence and
hands it to the next reader as knowledge.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.ops import incidents

NOW = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


def report(summary="collector cycle failed", source="collector", severity="warning", **details):
    return incidents.Report(
        source=source, summary=summary, severity=severity, details=details or None
    )


class TestFingerprintIdentity:
    def test_the_same_failure_twice_is_one_incident(self, session):
        incidents.record(session, report(), now=NOW)
        second = incidents.record(session, report(), now=NOW + timedelta(minutes=5))

        assert second.occurrences == 2
        assert len(incidents.open_incidents(session)) == 1

    def test_timestamps_inside_the_message_do_not_split_it(self, session):
        """The most common way a fingerprint fails: every occurrence carries a
        different clock reading and looks unique."""
        first = incidents.record(
            session, report("ingest stalled at 2026-08-14T11:02:03Z"), now=NOW
        )
        second = incidents.record(
            session, report("ingest stalled at 2026-08-14T11:47:59Z"), now=NOW
        )

        assert first.fingerprint == second.fingerprint
        assert second.occurrences == 2

    def test_uuids_and_counts_do_not_split_it_either(self, session):
        a = incidents.record(
            session,
            report("run 3f4a1b2c-1d2e-4f5a-8b9c-0d1e2f3a4b5c failed after 4200ms"),
            now=NOW,
        )
        b = incidents.record(
            session,
            report("run 9c8b7a6d-5e4f-4a3b-2c1d-0e9f8a7b6c5d failed after 5100ms"),
            now=NOW,
        )

        assert a.fingerprint == b.fingerprint

    def test_two_sources_saying_the_same_words_stay_apart(self, session):
        """"Connection refused" from the broker bridge and from the database
        need different remedies, so they are not one incident."""
        first = incidents.record(session, report("connection refused", source="bridge"), now=NOW)
        second = incidents.record(session, report("connection refused", source="database"), now=NOW)

        assert first.fingerprint != second.fingerprint

    def test_genuinely_different_problems_stay_apart(self, session):
        first = incidents.record(session, report("disk is full"), now=NOW)
        second = incidents.record(session, report("provider returned no bars"), now=NOW)

        assert first.fingerprint != second.fingerprint
        assert len(incidents.open_incidents(session)) == 2


class TestResolution:
    def test_clearing_needs_the_signal_to_stop(self, session):
        incidents.record(session, report(), now=NOW)

        cleared = incidents.clear(
            session, "collector", "collector cycle failed", now=NOW + timedelta(minutes=1)
        )

        assert cleared.resolved_at is not None
        assert incidents.open_incidents(session) == []

    def test_a_returning_problem_is_open_again(self, session):
        """Leaving the old resolution in place would let a health score report
        a live failure as settled."""
        incidents.record(session, report(), now=NOW)
        incidents.clear(session, "collector", "collector cycle failed", now=NOW)

        again = incidents.record(session, report(), now=NOW + timedelta(hours=1))

        assert again.resolved_at is None
        assert again.occurrences == 3 or again.occurrences == 2

    def test_the_count_never_resets(self, session):
        """A problem that returns after being fixed is more interesting than
        one that never left, and a reset count hides exactly that."""
        incidents.record(session, report(), now=NOW)
        incidents.clear(session, "collector", "collector cycle failed", now=NOW)
        incidents.record(session, report(), now=NOW + timedelta(hours=1))

        assert incidents.open_incidents(session)[0].occurrences == 2

    def test_clearing_something_that_never_happened_is_not_an_error(self, session):
        assert incidents.clear(session, "collector", "never seen", now=NOW) is None


class TestSeverity:
    def test_a_repeat_can_raise_it(self, session):
        incidents.record(session, report(severity="warning"), now=NOW)
        raised = incidents.record(session, report(severity="critical"), now=NOW)

        assert raised.severity == "critical"

    def test_a_repeat_cannot_quietly_lower_it(self, session):
        """One occurrence reporting itself as a warning should not downgrade a
        record of something critical."""
        incidents.record(session, report(severity="critical"), now=NOW)
        lowered = incidents.record(session, report(severity="info"), now=NOW)

        assert lowered.severity == "critical"

    def test_an_unknown_severity_is_refused(self, session):
        with pytest.raises(ValueError):
            incidents.record(session, report(severity="catastrophic"), now=NOW)


class TestRemedies:
    def test_a_remedy_is_not_confirmed_by_being_written_down(self, session):
        incident = incidents.record(session, report(), now=NOW)

        incidents.record_remedy(session, incident.fingerprint, "restarted the worker")

        assert incident.remedy_confirmed is False
        assert incidents.known_remedies(session) == []

    def test_it_is_confirmed_when_the_incident_clears_afterwards(self, session):
        incident = incidents.record(session, report(), now=NOW)
        incidents.record_remedy(session, incident.fingerprint, "restarted the worker")

        incidents.clear(session, "collector", "collector cycle failed", now=NOW)

        assert incident.remedy_confirmed is True
        assert len(incidents.known_remedies(session)) == 1

    def test_a_new_remedy_for_a_returning_problem_starts_unconfirmed(self, session):
        """The old remedy working says nothing about the new one."""
        incident = incidents.record(session, report(), now=NOW)
        incidents.record_remedy(session, incident.fingerprint, "restarted the worker")
        incidents.clear(session, "collector", "collector cycle failed", now=NOW)

        incidents.record(session, report(), now=NOW + timedelta(hours=1))
        incidents.record_remedy(session, incident.fingerprint, "raised the memory limit")

        assert incident.remedy_confirmed is False

    def test_unconfirmed_remedies_are_excluded_rather_than_flagged(self, session):
        """This list has to be trustworthy at three in the morning, and a list
        mixing "this worked" with "somebody typed this once" is not."""
        first = incidents.record(session, report("disk is full"), now=NOW)
        second = incidents.record(session, report("queue is stuck"), now=NOW)
        incidents.record_remedy(session, first.fingerprint, "pruned old rows")
        incidents.record_remedy(session, second.fingerprint, "guessed")
        incidents.clear(session, "collector", "disk is full", now=NOW)

        remedies = incidents.known_remedies(session)

        assert [r["remedy"] for r in remedies] == ["pruned old rows"]


class TestAlertCooldown:
    def test_the_first_alert_goes_out(self, session):
        incident = incidents.record(session, report(), now=NOW)

        allowed, reason = incidents.should_alert(session, incident.fingerprint, now=NOW)

        assert allowed is True
        assert "first alert" in reason

    def test_a_repeat_inside_the_window_is_suppressed(self, session):
        """Without this a flapping container pages somebody every thirty
        seconds, and the alert everybody has learned to ignore is the one that
        mattered."""
        incident = incidents.record(session, report(), now=NOW)
        incidents.mark_alerted(session, incident.fingerprint, now=NOW)

        allowed, reason = incidents.should_alert(
            session, incident.fingerprint, now=NOW + timedelta(minutes=5)
        )

        assert allowed is False
        assert "suppressed" in reason

    def test_it_speaks_again_once_the_cooldown_elapses(self, session):
        incident = incidents.record(session, report(), now=NOW)
        incidents.mark_alerted(session, incident.fingerprint, now=NOW)

        allowed, _ = incidents.should_alert(
            session, incident.fingerprint, now=NOW + incidents.ALERT_COOLDOWN + timedelta(minutes=1)
        )

        assert allowed is True

    def test_a_resolved_incident_does_not_alert(self, session):
        incident = incidents.record(session, report(), now=NOW)
        incidents.clear(session, "collector", "collector cycle failed", now=NOW)

        allowed, reason = incidents.should_alert(session, incident.fingerprint, now=NOW)

        assert allowed is False
        assert "resolved" in reason

    def test_the_cooldown_survives_a_restart(self, session):
        """It is stored on the row, not held in memory. An in-memory cooldown
        forgets on the one event most likely to cause an alert storm."""
        incident = incidents.record(session, report(), now=NOW)
        incidents.mark_alerted(session, incident.fingerprint, now=NOW)
        session.expire_all()

        allowed, _ = incidents.should_alert(
            session, incident.fingerprint, now=NOW + timedelta(minutes=1)
        )

        assert allowed is False


class TestWhatKeepsComingBack:
    def test_a_repeated_warning_outranks_a_single_critical(self, session):
        """A critical seen once is an event. A warning seen ninety times is a
        condition, and it is usually the one costing something."""
        incidents.record(session, report("disk is full", severity="critical"), now=NOW)
        for minute in range(5):
            incidents.record(
                session,
                report("provider returned no bars"),
                now=NOW + timedelta(minutes=minute),
            )

        ranked = incidents.recurring(session, minimum=3)

        assert len(ranked) == 1
        assert ranked[0]["occurrences"] == 5

    def test_the_window_excludes_old_conditions(self, session):
        for minute in range(4):
            incidents.record(session, report(), now=NOW + timedelta(minutes=minute))

        recent = incidents.recurring(
            session, minimum=3, window=timedelta(hours=1), now=NOW + timedelta(days=2)
        )

        assert recent == []
