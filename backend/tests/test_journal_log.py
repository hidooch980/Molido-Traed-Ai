"""Storing decisions, and keeping the two arms honest.

`app/brain/journal.py` has been complete and tested since early on and nothing
stored what it produced, so every decision the system made vanished on restart.
That matters now: the live loop records a decision every cycle, and the only
thing that can prove or kill the edge is the forward series those decisions
make. A journal with no storage is a forward measurement that resets on deploy.

Most of this file is about the comparison staying trustworthy - both arms
written together, open entries excluded, nothing invented for a value that was
never measured.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models.journal import ARM_CONTROL, ARM_RULE, JournalEntry
from app.services import journal_log

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


def bar(n: int) -> datetime:
    return NOW + timedelta(hours=n)


class TestRecording:
    def test_a_decision_is_stored(self, session):
        result = journal_log.record_decision(
            session, symbol="EURUSD", decision="long", at=NOW
        )

        assert result.new is True
        assert result.entry_id is not None

    def test_the_same_bar_twice_is_stored_once(self, session):
        """The loop republishes a decision whenever one cycle overlaps the
        previous, and a duplicate inflates the very sample the measurement
        rests on."""
        first = journal_log.record_decision(
            session, symbol="EURUSD", decision="long", at=NOW
        )
        second = journal_log.record_decision(
            session, symbol="EURUSD", decision="long", at=NOW
        )

        assert first.new is True
        assert second.new is False
        assert second.entry_id == first.entry_id

    def test_a_missing_probability_is_stored_as_missing(self, session):
        """0.5 is a forecast the system never made, and afterwards it is
        indistinguishable from one it did."""
        result = journal_log.record_decision(
            session, symbol="EURUSD", decision="long", at=NOW, probability=None
        )

        entry = session.get(JournalEntry, result.entry_id)
        assert entry.probability is None

    def test_an_open_entry_has_no_outcome(self, session):
        result = journal_log.record_decision(
            session, symbol="EURUSD", decision="long", at=NOW
        )

        entry = session.get(JournalEntry, result.entry_id)
        assert entry.outcome is None
        assert entry.closed_at is None


class TestTheTwoArmsAreWrittenTogether:
    def test_one_call_writes_both(self, session):
        """A rule series built over months beside a control series skipped on
        the days somebody was debugging is a comparison with an invisible
        hole."""
        result = journal_log.record_with_control(
            session,
            symbol="EURUSD",
            decision="long",
            at=NOW,
            price=1.1000,
            stop_distance=0.0025,
        )

        assert result["rule"]["new"] is True
        assert result["control"]["new"] is True
        assert result["control"]["arm"] == ARM_CONTROL

    def test_an_unusable_geometry_forms_no_control_and_says_so(self, session):
        """An unmatched rule entry silently included in a comparison is a
        bias."""
        result = journal_log.record_with_control(
            session,
            symbol="EURUSD",
            decision="long",
            at=NOW,
            price=1.1000,
            stop_distance=0.0,
        )

        assert result["control"] is None
        assert "excluded from the comparison" in result["reason"]

    def test_the_control_direction_is_reproducible(self, session):
        """Same bar, same side, always - so a re-run of any period reproduces
        the benchmark exactly."""
        journal_log.record_with_control(
            session,
            symbol="EURUSD",
            decision="long",
            at=NOW,
            price=1.1,
            stop_distance=0.0025,
        )
        stored = session.scalar(
            __import__("sqlalchemy").select(JournalEntry).where(
                JournalEntry.arm == ARM_CONTROL
            )
        )

        from app.learning import control

        expected = "long" if control.side_for("EURUSD", NOW) > 0 else "short"
        assert stored.decision == expected


class TestClosing:
    def test_an_entry_resolves(self, session):
        result = journal_log.record_decision(
            session, symbol="EURUSD", decision="long", at=NOW
        )

        changed = journal_log.close(
            session, result.entry_id, outcome="win", r_multiple=1.0, at=bar(2)
        )

        assert changed is True
        entry = session.get(JournalEntry, result.entry_id)
        assert entry.outcome == "win"
        assert entry.r_multiple == 1.0

    def test_closing_twice_does_not_rewrite_a_counted_result(self, session):
        result = journal_log.record_decision(
            session, symbol="EURUSD", decision="long", at=NOW
        )
        journal_log.close(session, result.entry_id, outcome="win", r_multiple=1.0)

        again = journal_log.close(
            session, result.entry_id, outcome="loss", r_multiple=-1.0
        )

        assert again is False
        assert session.get(JournalEntry, result.entry_id).outcome == "win"

    def test_closing_an_unknown_entry_is_false_not_an_error(self, session):
        import uuid

        assert journal_log.close(session, uuid.uuid4(), outcome="win") is False


class TestTheComparison:
    def resolve(self, session, arm, wins, losses, start=0):
        n = start
        for _ in range(wins):
            r = journal_log.record_decision(
                session, symbol=f"S{n}", decision="long", at=bar(n), arm=arm
            )
            journal_log.close(session, r.entry_id, outcome="win", r_multiple=1.0)
            n += 1
        for _ in range(losses):
            r = journal_log.record_decision(
                session, symbol=f"S{n}", decision="long", at=bar(n), arm=arm
            )
            journal_log.close(session, r.entry_id, outcome="loss", r_multiple=-1.0)
            n += 1
        return n

    def test_it_measures_rule_against_control(self, session):
        n = self.resolve(session, ARM_RULE, wins=60, losses=40)
        self.resolve(session, ARM_CONTROL, wins=50, losses=50, start=n)

        measured = journal_log.comparison(session)

        assert measured.rule_hit == 0.6
        assert measured.control_hit == 0.5
        assert round(measured.edge, 4) == 0.1

    def test_open_entries_are_excluded_from_both_arms(self, session):
        """Counting an open position as a loss makes every measurement
        pessimistic in exactly the periods the system was most active."""
        n = self.resolve(session, ARM_RULE, wins=10, losses=0)
        journal_log.record_decision(
            session, symbol="STILLOPEN", decision="long", at=bar(n), arm=ARM_RULE
        )

        measured = journal_log.comparison(session)

        assert measured.rule_trials == 10

    def test_an_empty_journal_reports_nothing_rather_than_zero(self, session):
        """An empty measurement is not a measurement of zero."""
        measured = journal_log.comparison(session)

        assert measured.edge is None
        assert measured.as_dict()["significant"] is False

    def test_the_summary_states_what_is_still_open(self, session):
        """"40 recorded, 12 resolved" reads as two unrelated numbers until the
        third is spelled out."""
        n = self.resolve(session, ARM_RULE, wins=3, losses=2)
        journal_log.record_decision(
            session, symbol="OPEN1", decision="long", at=bar(n), arm=ARM_RULE
        )

        described = journal_log.summary(session)

        assert described["arms"][ARM_RULE]["recorded"] == 6
        assert described["arms"][ARM_RULE]["resolved"] == 5
        assert described["arms"][ARM_RULE]["still_open"] == 1
