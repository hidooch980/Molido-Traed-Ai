"""When the forward measurement will be able to answer the question.

Not `test_readiness.py` - that name belongs to the production-readiness
checker in `app/ops`, which asks whether the deployment is safe to run. This
asks a different question: whether there is yet enough evidence to say the rule
works.

The question behind the module is "when can a real account be connected", and
the trap in it is that it invites a countdown to yes. These tests are mostly
about refusing that: the date is when the question becomes answerable, the unit
of evidence is the instant rather than the decision, and with no observed rate
there is no date at all.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.learning import readiness

TODAY = date(2026, 8, 17)


class TestTheSpreadIsWhatCosts:
    """An edge of +0.0212 R sounds decisive until you see it sits inside a
    per-instant spread of 0.61 R. That ratio, not the edge, sets the wait."""

    def test_the_spread_is_recovered_from_the_published_t(self):
        spread = readiness.spread_from_t(
            readiness.HISTORICAL_EDGE_R,
            readiness.HISTORICAL_T,
            readiness.HISTORICAL_INSTANTS,
        )

        assert spread == pytest.approx(0.6138, abs=0.001)

    def test_it_is_derived_rather_than_hardcoded(self):
        """So a revised t cannot leave a stale spread behind it, agreeing with
        nothing and looking authoritative."""
        assert readiness.spread_from_t(0.02, 4.0, 10000) == pytest.approx(0.5)

    def test_a_t_of_zero_raises_rather_than_returning_something(self):
        with pytest.raises(ValueError):
            readiness.spread_from_t(0.02, 0.0, 10000)


class TestTheSampleSize:
    def test_halving_the_edge_quadruples_the_wait(self):
        """The relationship is quadratic, which is the single most important
        thing to know before planning around any of these dates."""
        spread = 0.6138
        full = readiness.instants_needed(0.0212, spread)
        half = readiness.instants_needed(0.0106, spread)

        assert half == pytest.approx(full * 4, rel=0.01)

    def test_power_is_included_not_just_confidence(self):
        """Sizing on 1.96 alone plans to a coin flip on whether the exercise
        concludes: half the time the estimate lands low and a real edge is
        reported as nothing."""
        spread = 0.6138
        with_power = readiness.instants_needed(0.0212, spread)
        without = readiness.instants_needed(0.0212, spread, power_z=0.0)

        assert with_power > without * 2

    def test_a_negative_edge_has_no_sample_size(self):
        """No number of instants establishes something that is not there, and
        a very large number would read as "keep going" rather than as "this is
        the wrong question"."""
        assert readiness.instants_needed(-0.01, 0.6) is None
        assert readiness.instants_needed(0.0, 0.6) is None


class TestTheUnitIsTheInstant:
    """One cross-section at one moment produces both tails at once. Eight
    decisions there are one piece of evidence about one market move."""

    def test_both_counts_are_published(self):
        described = readiness.assess(
            instants_resolved=10,
            decisions_resolved=80,
            instants_per_week=120.0,
            today=TODAY,
        ).as_dict()

        assert described["instants_resolved"] == 10
        assert described["decisions_resolved"] == 80

    def test_progress_is_measured_in_instants_not_decisions(self):
        """The decision count is eight times larger. A fraction computed from
        it would report eight times the progress that exists."""
        assessed = readiness.assess(
            instants_resolved=10,
            decisions_resolved=80,
            instants_per_week=120.0,
            today=TODAY,
        )

        assert assessed.fraction == pytest.approx(10 / assessed.instants_needed)

    def test_the_reason_travels_with_the_numbers(self):
        described = readiness.assess(
            instants_resolved=0,
            decisions_resolved=0,
            instants_per_week=None,
            today=TODAY,
        ).as_dict()

        assert "one market move rather than eight" in described["why_instants"]


class TestTheRateIsObservedNeverAssumed:
    def test_without_a_rate_there_is_no_date(self):
        """A projection from an assumed rate is a forecast of the assumption."""
        assessed = readiness.assess(
            instants_resolved=0,
            decisions_resolved=0,
            instants_per_week=None,
            today=TODAY,
        )

        assert assessed.answerable_on is None
        assert assessed.instants_needed is not None

    def test_a_zero_rate_gives_no_date_rather_than_an_infinite_one(self):
        assessed = readiness.assess(
            instants_resolved=5,
            decisions_resolved=40,
            instants_per_week=0.0,
            today=TODAY,
        )

        assert assessed.answerable_on is None

    def test_a_slower_rate_pushes_the_date_out(self):
        fast = readiness.assess(
            instants_resolved=0,
            decisions_resolved=0,
            instants_per_week=120.0,
            today=TODAY,
        )
        slow = readiness.assess(
            instants_resolved=0,
            decisions_resolved=0,
            instants_per_week=60.0,
            today=TODAY,
        )

        assert slow.answerable_on > fast.answerable_on

    def test_a_finished_sample_answers_today(self):
        assessed = readiness.assess(
            instants_resolved=999_999,
            decisions_resolved=999_999,
            instants_per_week=120.0,
            today=TODAY,
        )

        assert assessed.answerable_on == TODAY
        assert assessed.fraction == 1.0


class TestTheDateIsNotAPromise:
    """The question invites a countdown to yes. It is a countdown to an
    answer, and the evidence so far points the other way: re-run unchanged on
    eleven years of daily bars the rule scored -0.0015 R at t = -0.12."""

    def test_it_says_so_in_the_payload(self):
        described = readiness.assess(
            instants_resolved=100,
            decisions_resolved=800,
            instants_per_week=120.0,
            today=TODAY,
        ).as_dict()

        assert "not the date it is answered yes" in described["what_the_date_means"]
        assert "-0.12" in described["what_the_date_means"]

    def test_the_projection_names_its_own_assumption(self):
        """The sample is sized for the historical edge, which is the number
        under test. A projection that hid that would be circular and look
        precise."""
        described = readiness.assess(
            instants_resolved=0,
            decisions_resolved=0,
            instants_per_week=120.0,
            today=TODAY,
        ).as_dict()

        assert "the number under test" in described["the_assumption"]
        assert "quadratic" in described["the_assumption"]

    def test_open_requirements_are_carried_not_summarised_away(self):
        """A date with three unmet requirements behind it is not a date."""
        described = readiness.assess(
            instants_resolved=100,
            decisions_resolved=800,
            instants_per_week=120.0,
            today=TODAY,
            open_requirements=("no forward evidence yet",),
            met_requirements=("the hypothesis was registered first",),
        ).as_dict()

        assert described["open_requirements"] == ["no forward evidence yet"]
        assert described["met_requirements"] == ["the hypothesis was registered first"]


class TestItReadsTheRealJournal:
    """The counts come from the table, and the requirements from the edge
    registry rather than a second copy. A restated list is a second thing to
    update, and the one nobody updates becomes a claim the system makes about
    itself that stopped being true."""

    def test_an_empty_journal_has_no_rate_and_no_date(self, session):
        from app.services import journal_log

        assessed = journal_log.readiness_of(session)

        assert assessed.instants_resolved == 0
        assert assessed.instants_per_week is None
        assert assessed.answerable_on is None

    def test_the_open_requirements_come_from_the_registry(self, session):
        from app.services import journal_log

        assessed = journal_log.readiness_of(session)

        assert assessed.open_requirements
        assert any("forward" in note or "held-out" in note
                   for note in assessed.open_requirements)

    def test_decisions_at_one_instant_count_once(self, session):
        """The whole point. Eight rows at one moment are one piece of
        evidence, and a counter that says eight would report eight times the
        progress that exists."""
        from datetime import timedelta

        from app.services import journal_log

        at = journal_log.MEASUREMENT_STARTS_AT + timedelta(hours=1)
        for symbol in ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD"):
            row = journal_log.record_decision(
                session, symbol=symbol, decision="long", at=at
            )
            journal_log.close(session, row.entry_id, outcome="win", r_multiple=1.0)

        assessed = journal_log.readiness_of(session)

        assert assessed.decisions_resolved == 4
        assert assessed.instants_resolved == 1

    def test_a_short_window_publishes_no_rate(self, session):
        """Three instants in the first two hours is 180 a week, and a date
        built on that would be confident and meaningless."""
        from datetime import timedelta

        from app.services import journal_log

        at = journal_log.MEASUREMENT_STARTS_AT + timedelta(hours=1)
        row = journal_log.record_decision(session, symbol="EURUSD", decision="long", at=at)
        journal_log.close(session, row.entry_id, outcome="win", r_multiple=1.0)

        early = journal_log.readiness_of(
            session, now=journal_log.MEASUREMENT_STARTS_AT + timedelta(hours=2)
        )
        later = journal_log.readiness_of(
            session, now=journal_log.MEASUREMENT_STARTS_AT + timedelta(days=14)
        )

        assert early.instants_per_week is None
        assert later.instants_per_week == pytest.approx(0.5, abs=0.01)

    def test_each_series_is_counted_on_its_own(self, session):
        from datetime import timedelta

        from app.models.journal import SOURCE_BROKER, SOURCE_PUBLIC
        from app.services import journal_log

        at = journal_log.MEASUREMENT_STARTS_AT + timedelta(hours=1)
        row = journal_log.record_decision(
            session, symbol="EURUSD", decision="long", at=at,
            price_source=SOURCE_PUBLIC,
        )
        journal_log.close(session, row.entry_id, outcome="win", r_multiple=1.0)

        assert journal_log.readiness_of(
            session, price_source=SOURCE_PUBLIC
        ).instants_resolved == 1
        assert journal_log.readiness_of(
            session, price_source=SOURCE_BROKER
        ).instants_resolved == 0


class TestOverlappingWindowsAreNotIndependentDraws:
    """The module already learned this once across the book: eight decisions
    at one instant are one piece of evidence. The same error runs along time.
    A decision is scored over 120 bars and instants land one bar apart, so
    consecutive instants re-measure almost the same stretch of market."""

    def make(self, resolved: int, **kw):
        return readiness.Readiness(
            instants_resolved=resolved,
            instants_needed=6573,
            decisions_resolved=resolved * 8,
            instants_per_week=40.0,
            answerable_on=None,
            **kw,
        )

    def test_the_horizon_is_imported_not_restated(self):
        """A window that drifts from the one the measurement scored over is a
        different measurement wearing the same name."""
        from app.workers.resolve import HORIZON

        assert readiness.Readiness.horizon_bars == HORIZON

    def test_the_floor_divides_by_the_window(self):
        assert self.make(250).independent_blocks == 2      # 250 // 120
        assert self.make(6573).independent_blocks == 54

    def test_the_floor_is_never_above_the_instant_count(self):
        for resolved in (0, 1, 119, 120, 121, 10_000):
            entry = self.make(resolved)
            assert entry.independent_blocks <= entry.instants_resolved

    def test_a_single_bar_horizon_makes_them_equal(self):
        """With no overlap there is nothing to discount, and the floor should
        not invent a penalty that is not there."""
        assert self.make(250, horizon_bars=1).independent_blocks == 250

    def test_a_zero_horizon_does_not_divide_by_zero(self):
        assert self.make(250, horizon_bars=0).independent_blocks == 250

    def test_both_numbers_are_published_so_neither_stands_alone(self):
        published = self.make(250).as_dict()

        assert published["instants_resolved"] == 250
        assert published["independent_blocks"] == 2
        assert published["horizon_bars"] == 120

    def test_the_payload_says_the_fraction_is_an_upper_bound(self):
        """Somebody will read `fraction` as progress. It is a ceiling."""
        published = self.make(250).as_dict()

        assert "upper bound on progress" in published["why_blocks"]
        assert "not independent draws" in published["why_blocks"]
