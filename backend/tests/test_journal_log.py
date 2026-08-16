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
    """These are about the arithmetic, not the window, so they pass `since`
    explicitly. `NOW` here predates `MEASUREMENT_STARTS_AT` - which is the
    window doing its job, and would otherwise silently empty every count
    below."""

    SINCE = NOW - timedelta(days=365)

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

        measured = journal_log.comparison(session, since=self.SINCE)

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

        measured = journal_log.comparison(session, since=self.SINCE)

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

        # Nested by price source now: the same rule runs on both the public
        # feed and the broker's own prices, and merging them would report one
        # count for two different measurements.
        from app.models.journal import SOURCE_PUBLIC

        rule = described["arms"][SOURCE_PUBLIC][ARM_RULE]
        assert rule["recorded"] == 6
        assert rule["resolved"] == 5
        assert rule["still_open"] == 1


class TestTheMeasurementWindowIsExplicit:
    """Everything recorded before the window came from code with three bugs in
    it - a weekend instant, two frozen symbols, and a series read past the
    moment being decided on. Those entries are kept, because a table that
    quietly loses its own history is worse evidence than one with a stated cut,
    and excluded, because they are not measurements of anything."""

    def test_the_comparison_ignores_entries_before_the_start(self, session):
        before = journal_log.MEASUREMENT_STARTS_AT - timedelta(days=1)
        after = journal_log.MEASUREMENT_STARTS_AT + timedelta(hours=1)

        for arm in (ARM_RULE, ARM_CONTROL):
            old = journal_log.record_decision(
                session, symbol=f"OLD{arm}", decision="long", at=before, arm=arm
            )
            journal_log.close(session, old.entry_id, outcome="win", r_multiple=1.0)
            new = journal_log.record_decision(
                session, symbol=f"NEW{arm}", decision="long", at=after, arm=arm
            )
            journal_log.close(session, new.entry_id, outcome="loss", r_multiple=-1.0)

        measured = journal_log.comparison(session)

        # Only the entries inside the window, so one per arm rather than two.
        assert measured.rule_trials == 1
        assert measured.control_trials == 1

    def test_an_explicit_since_still_wins(self, session):
        """The default is a fact about the deployment; a caller asking a
        different question may still ask it."""
        before = journal_log.MEASUREMENT_STARTS_AT - timedelta(days=1)

        for arm in (ARM_RULE, ARM_CONTROL):
            row = journal_log.record_decision(
                session, symbol=f"OLD{arm}", decision="long", at=before, arm=arm
            )
            journal_log.close(session, row.entry_id, outcome="win", r_multiple=1.0)

        assert journal_log.comparison(session).rule_trials == 0
        assert (
            journal_log.comparison(
                session, since=before - timedelta(days=1)
            ).rule_trials
            == 1
        )

    def test_the_summary_states_the_window_and_why(self, session):
        """So nobody has to guess which entries the numbers cover."""
        described = journal_log.summary(session)

        assert described["measurement_starts_at"]
        assert "three bugs" in described["why_it_starts_there"]

    def test_the_start_is_a_monday(self):
        """The markets reopen then. A window that starts mid-weekend begins
        with two days of nothing and one crypto instant."""
        assert journal_log.MEASUREMENT_STARTS_AT.strftime("%A") == "Monday"


class TestBothPriceSeriesAreMeasured:
    """The broker's prices and the public feed's differ by 33-39% of the stop
    distance on every major pair, measured over 490 shared hourly bars, and the
    edge being looked for is 0.021 R. One series answers half the question."""

    def test_the_same_bar_can_carry_a_decision_on_each_series(self, session):
        from app.models.journal import SOURCE_BROKER, SOURCE_PUBLIC

        public = journal_log.record_decision(
            session, symbol="EURUSD", decision="long", at=NOW,
            price_source=SOURCE_PUBLIC,
        )
        broker = journal_log.record_decision(
            session, symbol="EURUSD", decision="short", at=NOW,
            price_source=SOURCE_BROKER,
        )

        assert public.new is True
        assert broker.new is True
        assert public.entry_id != broker.entry_id

    def test_a_comparison_counts_one_series_only(self, session):
        """Merging them would report one number for two measurements."""
        from app.models.journal import SOURCE_BROKER, SOURCE_PUBLIC

        for arm in (ARM_RULE, ARM_CONTROL):
            row = journal_log.record_decision(
                session, symbol=f"P{arm}", decision="long",
                at=journal_log.MEASUREMENT_STARTS_AT + timedelta(hours=1),
                arm=arm, price_source=SOURCE_PUBLIC,
            )
            journal_log.close(session, row.entry_id, outcome="win", r_multiple=1.0)

        public = journal_log.comparison(session, price_source=SOURCE_PUBLIC)
        broker = journal_log.comparison(session, price_source=SOURCE_BROKER)

        assert public.rule_trials == 1
        assert broker.rule_trials == 0

    def test_the_summary_publishes_both_and_the_gap(self, session):
        from app.models.journal import SOURCE_BROKER, SOURCE_PUBLIC

        described = journal_log.summary(session)

        assert SOURCE_PUBLIC in described["by_source"]
        assert SOURCE_BROKER in described["by_source"]
        assert "edge_lost_to_real_prices" in described
        assert "33-39%" in described["why_two_series"]

    def test_the_gap_is_none_until_both_have_resolved(self, session):
        """An empty measurement is not a measurement of zero, and a gap
        computed from one arm is not a gap."""
        assert journal_log.summary(session)["edge_lost_to_real_prices"] is None
