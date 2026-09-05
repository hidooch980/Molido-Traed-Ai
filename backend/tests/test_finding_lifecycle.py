"""A gate with an entrance and no exit.

Nothing in this codebase had ever set `DataQualityFinding.resolved_at` - 0 of
95,795 on production - and `_persisted_finding_stats` counts every unresolved
error-level finding as blocking, which `is_training_eligible` requires to be
zero. So one bad bar, once, blocked its dataset for good: a dataset that had
been repaired looked exactly like one that never was.

The risk in fixing that is the opposite failure, and it is the worse one. A
re-check that cannot fail silently readmits bad data while reporting
progress. So every test here is about a finding being closed **only** on
evidence, and about the ones this mechanism deliberately refuses to judge.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.enums import DataQualityIssue, Severity, Timeframe
from app.models.ingestion import DataQualityFinding
from app.models.instruments import Instrument, Provider
from app.models.market_data import Bar
from app.services import data_quality

WHEN = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


@pytest.fixture()
def dataset(session):
    """One instrument and provider, with nothing stored yet."""
    provider = Provider(code="testing", name="Testing")
    instrument = Instrument(
        symbol="EURUSD",
        asset_class="forex",
        base_currency="EUR",
        quote_currency="USD",
        timezone="UTC",
    )
    session.add_all([provider, instrument])
    session.flush()
    return instrument, provider


def store_bar(session, instrument, provider, *, at, o, h, low, c, revision=1):
    session.add(
        Bar(
            instrument_id=instrument.id,
            provider_id=provider.id,
            timeframe=Timeframe.H1,
            event_time=at,
            revision=revision,
            open=o,
            high=h,
            low=low,
            close=c,
            volume=1.0,
            ingested_at=at,
        )
    )
    session.flush()


def raise_finding(session, instrument, provider, *, issue, at, severity=Severity.ERROR):
    finding = DataQualityFinding(
        instrument_id=instrument.id,
        provider_id=provider.id,
        timeframe=Timeframe.H1,
        issue=issue,
        severity=severity,
        window_start=at,
        window_end=at,
        detected_at=at,
        affected_rows=1,
    )
    session.add(finding)
    session.flush()
    return finding


def recheck(session, instrument, provider, *, now=None):
    return data_quality.recheck_findings(
        session,
        instrument_id=instrument.id,
        provider_id=provider.id,
        timeframe=Timeframe.H1,
        now=now or WHEN + timedelta(days=1),
    )


class TestOnlyOnEvidence:
    def test_a_repaired_bar_closes_its_finding(self, session, dataset):
        """The provider revised the bar and it is coherent now. This is the
        case the whole mechanism exists for."""
        instrument, provider = dataset
        store_bar(session, instrument, provider, at=WHEN, o=1.1, h=1.0, low=1.05, c=1.08)
        finding = raise_finding(
            session,
            instrument,
            provider,
            issue=DataQualityIssue.INVALID_OHLC_RELATION,
            at=WHEN,
        )
        # Revision 2: what a reader would now see.
        store_bar(
            session, instrument, provider, at=WHEN, o=1.06, h=1.1, low=1.05, c=1.08, revision=2
        )

        assert recheck(session, instrument, provider) == 1
        assert finding.resolved_at is not None

    def test_a_bar_that_is_still_wrong_keeps_its_finding(self, session, dataset):
        """The one that matters. A re-check that closed this would be
        readmitting bad data while reporting progress."""
        instrument, provider = dataset
        store_bar(session, instrument, provider, at=WHEN, o=1.1, h=1.0, low=1.05, c=1.08)
        finding = raise_finding(
            session,
            instrument,
            provider,
            issue=DataQualityIssue.INVALID_OHLC_RELATION,
            at=WHEN,
        )

        assert recheck(session, instrument, provider) == 0
        assert finding.resolved_at is None

    def test_it_judges_the_newest_revision_not_the_one_that_was_wrong(
        self, session, dataset
    ):
        """`point_in_time` serves the newest revision, so that is what a
        reader gets and what the finding has to be judged against. Reading the
        superseded row would keep a finding open about data nothing reads."""
        instrument, provider = dataset
        store_bar(session, instrument, provider, at=WHEN, o=1.06, h=1.1, low=1.05, c=1.08)
        store_bar(
            session, instrument, provider, at=WHEN, o=1.1, h=1.0, low=1.05, c=1.08, revision=2
        )
        finding = raise_finding(
            session,
            instrument,
            provider,
            issue=DataQualityIssue.INVALID_OHLC_RELATION,
            at=WHEN,
        )

        # Newest revision is the broken one, so the finding stands.
        assert recheck(session, instrument, provider) == 0
        assert finding.resolved_at is None

    def test_a_bar_that_no_longer_exists_closes_its_finding(self, session, dataset):
        """Retention trimmed it or a correction replaced the instant. Either
        way the defect is not in the data a reader would get."""
        instrument, provider = dataset
        finding = raise_finding(
            session,
            instrument,
            provider,
            issue=DataQualityIssue.INVALID_OHLC_RELATION,
            at=WHEN,
        )

        assert recheck(session, instrument, provider) == 1
        assert finding.resolved_at is not None


class TestWhatItRefusesToJudge:
    def test_a_duplicate_bar_finding_is_left_open(self, session, dataset):
        """It says the provider sent one timestamp twice *in a batch*, and the
        batch is gone. Storage keys bars by revision, so the same instant
        legitimately appears twice as a correction - a re-check would either
        always close it or never close it, and neither answer is about the
        defect that was reported."""
        instrument, provider = dataset
        store_bar(session, instrument, provider, at=WHEN, o=1.06, h=1.1, low=1.05, c=1.08)
        finding = raise_finding(
            session, instrument, provider, issue=DataQualityIssue.DUPLICATE_BAR, at=WHEN
        )

        assert recheck(session, instrument, provider) == 0
        assert finding.resolved_at is None

    def test_a_provider_conflict_is_left_open(self, session, dataset):
        """Settling it needs the other provider's series, which this does not
        load."""
        instrument, provider = dataset
        store_bar(session, instrument, provider, at=WHEN, o=1.06, h=1.1, low=1.05, c=1.08)
        finding = raise_finding(
            session,
            instrument,
            provider,
            issue=DataQualityIssue.PROVIDER_CONFLICT,
            at=WHEN,
        )

        assert recheck(session, instrument, provider) == 0
        assert finding.resolved_at is None

    def test_a_missing_candle_is_left_open(self, session, dataset):
        """Gap detection needs the series and the schedule, so a re-check over
        the one instant it names would be a weaker test wearing the same
        name."""
        instrument, provider = dataset
        finding = raise_finding(
            session,
            instrument,
            provider,
            issue=DataQualityIssue.MISSING_CANDLE,
            at=WHEN,
            severity=Severity.WARNING,
        )

        assert recheck(session, instrument, provider) == 0
        assert finding.resolved_at is None


class TestStaleness:
    def test_a_feed_that_came_back_closes_its_finding(self, session, dataset):
        """The finding says the newest bar then was `window_start`. A bar
        after it is the feed answering."""
        instrument, provider = dataset
        finding = raise_finding(
            session,
            instrument,
            provider,
            issue=DataQualityIssue.STALE_DATA,
            at=WHEN,
            severity=Severity.CRITICAL,
        )
        store_bar(
            session,
            instrument,
            provider,
            at=WHEN + timedelta(hours=1),
            o=1.06,
            h=1.1,
            low=1.05,
            c=1.08,
        )

        assert recheck(session, instrument, provider) == 1
        assert finding.resolved_at is not None

    def test_a_feed_still_silent_keeps_its_finding(self, session, dataset):
        instrument, provider = dataset
        store_bar(session, instrument, provider, at=WHEN, o=1.06, h=1.1, low=1.05, c=1.08)
        finding = raise_finding(
            session,
            instrument,
            provider,
            issue=DataQualityIssue.STALE_DATA,
            at=WHEN,
            severity=Severity.CRITICAL,
        )

        assert recheck(session, instrument, provider) == 0
        assert finding.resolved_at is None


class TestItUnblocksTheGate:
    def test_a_repaired_dataset_becomes_eligible_again(self, session, dataset):
        """End to end, through the gate itself: the exit that never existed."""
        instrument, provider = dataset
        for hour in range(30):
            store_bar(
                session,
                instrument,
                provider,
                at=WHEN + timedelta(hours=hour),
                o=1.06,
                h=1.1,
                low=1.05,
                c=1.08,
            )
        raise_finding(
            session,
            instrument,
            provider,
            issue=DataQualityIssue.INVALID_OHLC_RELATION,
            at=WHEN,
        )

        # What the gate said before this existed: one open error-level
        # finding, so blocking, so ineligible - permanently, because nothing
        # could ever close it.
        _penalty, _open, blocking = data_quality._persisted_finding_stats(
            session, instrument.id, provider.id, Timeframe.H1
        )
        assert blocking == 1

        # The bar at WHEN was always coherent; the finding was stale. One
        # re-evaluation settles it and the gate opens on the same pass -
        # deferring to the next one would add a delay to a gate that had no
        # exit at all for its whole life.
        healed = data_quality.update_dataset_quality(
            session,
            instrument_id=instrument.id,
            provider_id=provider.id,
            timeframe=Timeframe.H1,
            report=data_quality.QualityReport(),
        )

        assert healed.is_training_eligible is True

    def test_a_dataset_with_a_real_defect_stays_blocked(self, session, dataset):
        """The gate must still close. This is what stops the mechanism from
        being a way to launder bad data through a re-evaluation."""
        instrument, provider = dataset
        for hour in range(30):
            store_bar(
                session,
                instrument,
                provider,
                at=WHEN + timedelta(hours=hour),
                o=1.06,
                h=1.1,
                low=1.05,
                c=1.08,
            )
        store_bar(
            session,
            instrument,
            provider,
            at=WHEN,
            o=1.1,
            h=1.0,
            low=1.05,
            c=1.08,
            revision=2,
        )
        raise_finding(
            session,
            instrument,
            provider,
            issue=DataQualityIssue.INVALID_OHLC_RELATION,
            at=WHEN,
        )

        record = data_quality.update_dataset_quality(
            session,
            instrument_id=instrument.id,
            provider_id=provider.id,
            timeframe=Timeframe.H1,
            report=data_quality.QualityReport(),
        )

        assert record.is_training_eligible is False


class TestTheDrainIsBounded:
    def test_one_pass_settles_at_most_a_batch(self, session, dataset):
        """This runs inside the collector's per-entry work every cycle. A
        dataset carrying thousands of open findings must not turn a
        fifteen-minute sweep into a backlog drain."""
        instrument, provider = dataset
        for minute in range(data_quality.RECHECK_BATCH + 10):
            raise_finding(
                session,
                instrument,
                provider,
                issue=DataQualityIssue.INVALID_OHLC_RELATION,
                at=WHEN + timedelta(minutes=minute),
            )

        assert recheck(session, instrument, provider) == data_quality.RECHECK_BATCH

    def test_the_oldest_go_first_so_the_queue_empties(self, session, dataset):
        instrument, provider = dataset
        oldest = raise_finding(
            session,
            instrument,
            provider,
            issue=DataQualityIssue.INVALID_OHLC_RELATION,
            at=WHEN,
        )
        for minute in range(1, 5):
            raise_finding(
                session,
                instrument,
                provider,
                issue=DataQualityIssue.INVALID_OHLC_RELATION,
                at=WHEN + timedelta(minutes=minute),
            )

        data_quality.recheck_findings(
            session,
            instrument_id=instrument.id,
            provider_id=provider.id,
            timeframe=Timeframe.H1,
            now=WHEN + timedelta(days=1),
            limit=1,
        )

        assert oldest.resolved_at is not None


def test_a_dataset_with_nothing_open_costs_nothing(session, dataset):
    instrument, provider = dataset

    assert recheck(session, instrument, provider) == 0


