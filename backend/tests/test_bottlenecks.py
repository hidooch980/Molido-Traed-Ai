"""Where the waste is, which is rarely where the noise is.

Every finding here is something that costs time and raises no alarm: a job that
retries four times and succeeds, a sweep three times slower than the same
series usually takes, a symbol re-fetched every cycle that writes nothing.
Failure counts see none of it, because none of it fails.

The ordering is by estimated cost rather than by severity, and the two disagree
constantly. A critical seen once is an event; a warning seen ninety times is a
condition, and the condition is what is actually expensive - which is exactly
why nobody has fixed it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.core.enums import IngestionStatus, Timeframe
from app.models.ingestion import IngestionRun
from app.ops import bottlenecks
from app.ops import incidents as incident_memory

NOW = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


def add_run(
    session,
    instrument,
    provider,
    *,
    attempts=1,
    written=10,
    seconds=2.0,
    minutes_ago=10,
):
    started = NOW - timedelta(minutes=minutes_ago)
    run = IngestionRun(
        provider_id=provider.id,
        instrument_id=instrument.id,
        timeframe=Timeframe.H1,
        idempotency_key=uuid.uuid4().hex,
        requested_start=started,
        requested_end=started + timedelta(hours=1),
        status=IngestionStatus.SUCCEEDED,
        started_at=started,
        finished_at=started + timedelta(seconds=seconds),
        rows_fetched=written,
        rows_written=written,
        attempts=attempts,
    )
    session.add(run)
    session.flush()
    return run


class TestRetriesThatSucceed:
    def test_extra_attempts_are_found_even_though_nothing_failed(
        self, session, instrument, provider
    ):
        """The whole point: these runs succeeded, so no failure count sees
        them, and each retry is still a request and a backoff."""
        for _ in range(5):
            add_run(session, instrument, provider, attempts=3)

        findings = bottlenecks.retry_waste(session, now=NOW)

        assert len(findings) == 1
        assert findings[0].evidence["extra"] == 10

    def test_clean_runs_produce_nothing(self, session, instrument, provider):
        for _ in range(5):
            add_run(session, instrument, provider, attempts=1)

        assert bottlenecks.retry_waste(session, now=NOW) == []

    def test_runs_outside_the_window_are_ignored(self, session, instrument, provider):
        """Something fixed last week must stop being reported as a current
        cost."""
        for _ in range(5):
            add_run(session, instrument, provider, attempts=3, minutes_ago=60 * 24 * 10)

        assert bottlenecks.retry_waste(session, now=NOW) == []


class TestSlowRuns:
    def test_a_run_far_slower_than_its_own_median_is_named(
        self, session, instrument, provider
    ):
        for _ in range(bottlenecks.MIN_RUNS_FOR_MEDIAN):
            add_run(session, instrument, provider, seconds=2.0)
        add_run(session, instrument, provider, seconds=30.0)

        findings = bottlenecks.slow_runs(session, now=NOW)

        assert len(findings) == 1
        assert findings[0].evidence["slow_runs"] == 1

    def test_it_compares_against_the_series_own_median(
        self, session, instrument, provider
    ):
        """A daily bar and a fifteen-minute bar have nothing to say to each
        other about what slow means, so a fixed threshold would flag every one
        of them or none."""
        for _ in range(bottlenecks.MIN_RUNS_FOR_MEDIAN + 4):
            add_run(session, instrument, provider, seconds=60.0)

        assert bottlenecks.slow_runs(session, now=NOW) == []

    def test_too_few_runs_says_nothing(self, session, instrument, provider):
        """"Slower than usual" over two data points is a claim, not a
        finding."""
        add_run(session, instrument, provider, seconds=1.0)
        add_run(session, instrument, provider, seconds=60.0)

        assert bottlenecks.slow_runs(session, now=NOW) == []


class TestEmptyWork:
    def test_a_series_that_never_writes_is_found(self, session, instrument, provider):
        for _ in range(bottlenecks.MIN_RUNS_FOR_MEDIAN + 2):
            add_run(session, instrument, provider, written=0)

        findings = bottlenecks.empty_work(session, now=NOW)

        assert len(findings) == 1
        assert "wrong symbol mapping" in findings[0].detail

    def test_writing_anything_clears_it(self, session, instrument, provider):
        """A quiet feed is normal. A feed that has never once written is not."""
        for _ in range(bottlenecks.MIN_RUNS_FOR_MEDIAN + 2):
            add_run(session, instrument, provider, written=0)
        add_run(session, instrument, provider, written=1)

        assert bottlenecks.empty_work(session, now=NOW) == []


class TestConditionsBeatEvents:
    def test_a_repeated_warning_outranks_a_single_critical(self, session):
        incident_memory.record(
            session,
            incident_memory.Report(source="db", summary="disk full", severity="critical"),
            now=NOW,
        )
        for minute in range(9):
            incident_memory.record(
                session,
                incident_memory.Report(source="collector", summary="provider empty"),
                now=NOW + timedelta(minutes=minute),
            )

        findings = bottlenecks.recurring_incidents(session, now=NOW + timedelta(minutes=10))

        assert len(findings) == 1
        assert findings[0].evidence["occurrences"] == 9

    def test_the_ranking_is_by_cost_not_severity(self, session, instrument, provider):
        """The loud failure already has attention. The quiet one is still
        costing something, and a severity-ordered list buries it."""
        incident_memory.record(
            session,
            incident_memory.Report(source="db", summary="disk full", severity="critical"),
            now=NOW,
        )
        for _ in range(30):
            add_run(session, instrument, provider, attempts=4)

        analysis = bottlenecks.analyse(session, now=NOW)

        assert analysis["biggest"]["kind"] == "retries"


class TestTheReportIsHonestAboutItself:
    def test_an_empty_result_does_not_claim_optimal(self, session):
        analysis = bottlenecks.analyse(session, now=NOW)

        assert analysis["findings"] == []
        assert "not that the system is optimal" in analysis["nothing_found_means"]

    def test_costs_are_labelled_as_estimates(self, session):
        analysis = bottlenecks.analyse(session, now=NOW)

        assert analysis["cost_is_estimated"] is True
        assert "ordering signals, not measurements" in analysis["note"]

    def test_findings_are_ordered_by_cost(self, session, instrument, provider):
        for _ in range(20):
            add_run(session, instrument, provider, attempts=3)
        incident_memory.record(
            session,
            incident_memory.Report(source="x", summary="minor thing"),
            now=NOW,
        )
        for minute in range(6):
            incident_memory.record(
                session,
                incident_memory.Report(source="x", summary="minor thing"),
                now=NOW + timedelta(minutes=minute),
            )

        findings = bottlenecks.analyse(session, now=NOW + timedelta(minutes=10))["findings"]
        costs = [f["estimated_cost_seconds"] for f in findings]

        assert costs == sorted(costs, reverse=True)
