"""Data-quality detector tests.

Each detector is exercised against input whose defect is known in advance, so
these assert detection, not merely execution (spec §73: code existence is not
a pass).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.enums import DataQualityIssue, Severity, Timeframe
from app.providers.base import RawBar
from app.services import data_quality
from tests.conftest import BASE_TIME, make_bars


def _issues(report) -> set[str]:
    return {f.issue.value for f in report.findings}


def test_clean_series_has_no_blocking_findings():
    report = data_quality.evaluate_bars(make_bars(200), Timeframe.H1)

    blocking = [
        f for f in report.findings if f.severity in (Severity.ERROR, Severity.CRITICAL)
    ]
    assert blocking == []
    assert report.score > 0.95


def test_empty_dataset_scores_zero_not_one():
    """No data is not perfect data."""
    report = data_quality.evaluate_bars([], Timeframe.H1)

    assert report.score == 0.0


def test_detects_missing_candles():
    bars = make_bars(100)
    del bars[40:45]  # five-bar hole, mid-week

    report = data_quality.evaluate_bars(bars, Timeframe.H1)

    missing = [f for f in report.findings if f.issue == DataQualityIssue.MISSING_CANDLE]
    assert len(missing) == 1
    assert missing[0].affected_rows == 5


def test_weekend_gap_is_informational_only():
    """Legitimate weekend closure must not be scored as a data defect."""
    friday = datetime(2024, 3, 8, 20, 0, tzinfo=UTC)
    bars = [
        make_bars(1, start=friday)[0],
        make_bars(1, start=friday + timedelta(hours=52))[0],  # Monday
    ] + make_bars(50, start=friday + timedelta(hours=53))

    report = data_quality.evaluate_bars(bars, Timeframe.H1)

    missing = [f for f in report.findings if f.issue == DataQualityIssue.MISSING_CANDLE]
    assert missing
    assert all(f.severity == Severity.INFO for f in missing)


def test_detects_duplicate_timestamp():
    bars = make_bars(50)
    bars.insert(10, bars[10])

    report = data_quality.evaluate_bars(bars, Timeframe.H1)

    assert DataQualityIssue.DUPLICATE_BAR.value in _issues(report)


def test_detects_out_of_order_timestamps():
    bars = make_bars(50)
    bars[10], bars[11] = bars[11], bars[10]

    report = data_quality.evaluate_bars(bars, Timeframe.H1)

    assert DataQualityIssue.NON_MONOTONIC_TIMESTAMP.value in _issues(report)


def test_detects_invalid_ohlc_relation():
    bars = make_bars(50)
    bars[5] = replace(bars[5], high=bars[5].low - 0.01)

    report = data_quality.evaluate_bars(bars, Timeframe.H1)

    assert DataQualityIssue.INVALID_OHLC_RELATION.value in _issues(report)


def test_detects_non_positive_price_as_critical():
    bars = make_bars(50)
    bars[7] = replace(bars[7], low=-1.0)

    report = data_quality.evaluate_bars(bars, Timeframe.H1)

    findings = [f for f in report.findings if f.issue == DataQualityIssue.NON_POSITIVE_PRICE]
    assert findings and findings[0].severity == Severity.CRITICAL


def test_detects_price_gap_and_outlier():
    bars = make_bars(200)
    spike = bars[100]
    bars[100] = replace(
        spike,
        open=spike.open * 1.05,
        close=spike.close * 1.05,
        high=spike.high * 1.06,
        low=spike.low * 1.04,
    )

    report = data_quality.evaluate_bars(bars, Timeframe.H1)
    issues = _issues(report)

    assert DataQualityIssue.PRICE_GAP.value in issues


def test_statistics_are_withheld_on_small_samples():
    """Below the sample floor the engine makes no statistical claim at all."""
    bars = make_bars(10)
    bars[5] = replace(bars[5], close=bars[5].close * 2)

    report = data_quality.evaluate_bars(bars, Timeframe.H1)

    assert DataQualityIssue.PRICE_GAP.value not in _issues(report)
    assert DataQualityIssue.OUTLIER.value not in _issues(report)


class TestCalendarAwareGaps:
    """Phase 6: the weekday guess is replaced by a real schedule."""

    @staticmethod
    def _crypto_calendar():
        from app.services.sessions import CRYPTO_HOURS, SessionCalendar, TradingWindow

        return SessionCalendar(
            timezone="Etc/UTC",
            windows=[TradingWindow.parse(w) for w in CRYPTO_HOURS],
        )

    @staticmethod
    def _fx_calendar(holidays=None):
        from app.services.sessions import (
            FX_HOURS,
            FX_TIMEZONE,
            SessionCalendar,
            TradingWindow,
        )

        return SessionCalendar(
            timezone=FX_TIMEZONE,
            windows=[TradingWindow.parse(w) for w in FX_HOURS],
            holidays=holidays or {},
        )

    def test_weekend_gap_produces_no_finding_at_all(self):
        """Previously downgraded to INFO; now it is simply not a gap.

        8 March 2024 is still EST, so the Friday 17:00 New York close is
        22:00 UTC and the last tradeable bar opens at 21:00. The market
        reopens Sunday 17:00 EDT = 21:00 UTC.
        """
        friday = datetime(2024, 3, 8, 12, 0, tzinfo=UTC)
        bars = make_bars(10, start=friday)  # 12:00 .. 21:00, right up to the close
        bars += make_bars(5, start=datetime(2024, 3, 10, 21, 0, tzinfo=UTC))

        report = data_quality.evaluate_bars(bars, Timeframe.H1, self._fx_calendar())

        assert DataQualityIssue.MISSING_CANDLE.value not in _issues(report)
        assert report.calendar_aware is True

    def test_weekday_hole_is_a_full_warning_not_a_downgrade(self):
        start = datetime(2024, 3, 6, 0, 0, tzinfo=UTC)  # Wednesday
        bars = make_bars(24, start=start)
        del bars[10:14]

        report = data_quality.evaluate_bars(bars, Timeframe.H1, self._crypto_calendar())

        missing = [f for f in report.findings if f.issue == DataQualityIssue.MISSING_CANDLE]
        assert len(missing) == 1
        assert missing[0].severity == Severity.WARNING
        assert missing[0].affected_rows == 4
        assert missing[0].details["calendar_aware"] is True

    def test_holiday_closure_is_not_reported_as_missing_data(self):
        from app.core.enums import HolidayKind
        from app.services.sessions import Holiday

        christmas = date(2024, 12, 25)
        calendar = self._fx_calendar(
            {
                christmas: Holiday(
                    holiday_date=christmas, kind=HolidayKind.CLOSED, name="Christmas"
                )
            }
        )
        # The holiday is a New York calendar day, which runs 05:00 UTC to
        # 05:00 UTC. Trade right up to it, skip it, resume the moment it ends.
        bars = make_bars(6, start=datetime(2024, 12, 24, 23, 0, tzinfo=UTC))
        bars += make_bars(6, start=datetime(2024, 12, 26, 5, 0, tzinfo=UTC))

        report = data_quality.evaluate_bars(bars, Timeframe.H1, calendar)

        assert DataQualityIssue.MISSING_CANDLE.value not in _issues(report)

    def test_bar_delivered_while_the_market_was_shut_is_flagged(self):
        """The inverse defect the old heuristic could never see."""
        bars = make_bars(6, start=datetime(2024, 3, 6, 12, 0, tzinfo=UTC))
        bars += make_bars(2, start=datetime(2024, 3, 9, 12, 0, tzinfo=UTC))  # Saturday

        report = data_quality.evaluate_bars(bars, Timeframe.H1, self._fx_calendar())

        assert DataQualityIssue.SESSION_MISMATCH.value in _issues(report)

    def test_expected_rows_counts_only_tradeable_slots(self):
        """The weekend must not inflate the denominator.

        Six bars spanning Friday evening to Sunday night cover ~52 wall-clock
        hours. The naive slot count would be ~52 and the dataset would look
        ~88% incomplete; the calendar knows only 8 of those hours were
        tradeable.
        """
        friday = datetime(2024, 3, 8, 18, 0, tzinfo=UTC)
        bars = make_bars(3, start=friday)  # 18:00, 19:00, 20:00
        bars += make_bars(3, start=datetime(2024, 3, 10, 22, 0, tzinfo=UTC))

        report = data_quality.evaluate_bars(bars, Timeframe.H1, self._fx_calendar())

        naive_slots = int(
            (bars[-1].event_time - bars[0].event_time) / Timeframe.H1.delta
        )
        assert naive_slots > 50
        # 21:00 Friday (before the 22:00 close) and 21:00 Sunday (the reopen)
        # are genuinely expected and genuinely absent - so 6 present + 2 missing.
        assert report.expected_rows == 8

    def test_without_a_calendar_the_old_heuristic_still_applies(self):
        """The fallback stays available for calendar-less batch evaluation."""
        bars = make_bars(100)
        del bars[40:45]

        report = data_quality.evaluate_bars(bars, Timeframe.H1)

        assert report.calendar_aware is False
        assert DataQualityIssue.MISSING_CANDLE.value in _issues(report)


def test_detects_provider_conflict():
    a = make_bars(20)
    b = [replace(bar, close=bar.close * 1.01) for bar in a]

    findings = data_quality.detect_provider_conflicts({"alpha": a, "beta": b})

    assert findings
    assert all(f.issue == DataQualityIssue.PROVIDER_CONFLICT for f in findings)


def test_provider_conflict_needs_two_providers():
    assert data_quality.detect_provider_conflicts({"alpha": make_bars(5)}) == []


def test_staleness_check():
    now = BASE_TIME + timedelta(hours=10)

    stale = data_quality.check_staleness(BASE_TIME, Timeframe.H1, now=now)
    fresh = data_quality.check_staleness(
        now - timedelta(minutes=30), Timeframe.H1, now=now
    )
    missing = data_quality.check_staleness(None, Timeframe.H1, now=now)

    assert stale is not None and stale.severity == Severity.CRITICAL
    assert fresh is None
    assert missing is not None


def test_score_penalises_severity_proportionally():
    clean = data_quality.evaluate_bars(make_bars(200), Timeframe.H1)

    corrupted_bars = make_bars(200)
    corrupted_bars[3] = replace(corrupted_bars[3], low=-1.0)
    corrupted = data_quality.evaluate_bars(corrupted_bars, Timeframe.H1)

    assert corrupted.score < clean.score


def test_persist_findings_is_idempotent(session, instrument, provider):
    bars = make_bars(100)
    del bars[40:45]
    report = data_quality.evaluate_bars(bars, Timeframe.H1)

    first = data_quality.persist_findings(
        session,
        instrument_id=instrument.id,
        provider_id=provider.id,
        timeframe=Timeframe.H1,
        findings=report.findings,
    )
    second = data_quality.persist_findings(
        session,
        instrument_id=instrument.id,
        provider_id=provider.id,
        timeframe=Timeframe.H1,
        findings=report.findings,
    )

    assert first > 0
    assert second == 0, "re-running the engine must not inflate the finding count"


def _store(session, instrument, provider, bars):
    """Persist bars so the rollup has stored history to measure.

    Stores the bar's own open, high and low rather than letting the shared
    `insert_bar` helper synthesise them around the close. That helper builds
    a doji by construction, so a batch carrying a deliberately broken bar was
    being stored as a clean one - which did not matter while findings were
    permanent, and matters entirely now that a re-check settles them against
    stored data. A fixture whose storage disagrees with the batch it
    evaluated is not what ingestion does.
    """
    from app.models.market_data import Bar

    for bar in bars:
        session.add(
            Bar(
                instrument_id=instrument.id,
                provider_id=provider.id,
                timeframe=Timeframe.H1,
                event_time=bar.event_time,
                revision=1,
                ingested_at=BASE_TIME,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume if bar.volume is not None else 1000.0,
            )
        )
    session.flush()


def _evaluate_and_roll_up(session, instrument, provider, bars):
    """The real sequence: evaluate, persist findings, then roll up."""
    report = data_quality.evaluate_bars(bars, Timeframe.H1)
    data_quality.persist_findings(
        session,
        instrument_id=instrument.id,
        provider_id=provider.id,
        timeframe=Timeframe.H1,
        findings=report.findings,
    )
    return data_quality.update_dataset_quality(
        session,
        instrument_id=instrument.id,
        provider_id=provider.id,
        timeframe=Timeframe.H1,
        report=report,
    )


def test_training_eligibility_blocked_by_single_critical(session, instrument, provider):
    bars = make_bars(500)
    bars[10] = replace(bars[10], low=-1.0)
    _store(session, instrument, provider, bars)

    record = _evaluate_and_roll_up(session, instrument, provider, bars)

    # One bad bar in 500 barely moves the average score, but it still blocks.
    assert float(record.score) > 0.9
    assert record.is_training_eligible is False


def test_unstored_dataset_is_never_eligible(session, instrument, provider):
    """The gate measures stored history; an empty dataset cannot pass it."""
    record = _evaluate_and_roll_up(session, instrument, provider, make_bars(500))

    assert record.actual_bars == 0
    assert record.is_training_eligible is False


def test_small_batch_cannot_reset_a_blocked_dataset(session, instrument, provider):
    """Regression: an incremental cycle must not readmit rejected data.

    Found by inspecting a live database. The collector had evaluated a batch of
    exactly one bar, and the rollup was rebuilt from that batch — resetting a
    dataset that a full evaluation had blocked (open error-level finding) back
    to `is_training_eligible = true`. Every collection cycle silently undid the
    gate.
    """
    # 500 unique bars are stored. The duplicate the provider sent is *not*
    # stored — the primary key prevents that — but it is still a defect in the
    # feed, so it lives on as an error-level finding.
    bars = make_bars(500)
    _store(session, instrument, provider, bars)
    full = data_quality.evaluate_bars([*bars, bars[10]], Timeframe.H1)
    data_quality.persist_findings(
        session,
        instrument_id=instrument.id,
        provider_id=provider.id,
        timeframe=Timeframe.H1,
        findings=full.findings,
    )
    blocked = data_quality.update_dataset_quality(
        session,
        instrument_id=instrument.id,
        provider_id=provider.id,
        timeframe=Timeframe.H1,
        report=full,
    )
    assert blocked.is_training_eligible is False

    # Now an incremental cycle evaluates a single clean bar.
    tiny = data_quality.evaluate_bars(make_bars(1, start=BASE_TIME + timedelta(days=30)),
                                      Timeframe.H1)
    after = data_quality.update_dataset_quality(
        session,
        instrument_id=instrument.id,
        provider_id=provider.id,
        timeframe=Timeframe.H1,
        report=tiny,
    )

    assert after.is_training_eligible is False, "a one-bar batch must not lift the block"
    assert after.actual_bars > 1, "the rollup must reflect stored history, not the batch"


def test_training_eligibility_granted_for_clean_data(session, instrument, provider):
    bars = make_bars(500)
    _store(session, instrument, provider, bars)

    record = _evaluate_and_roll_up(session, instrument, provider, bars)

    assert record.actual_bars == 500
    assert record.is_training_eligible is True


def test_naive_timestamp_is_flagged():
    naive = RawBar(
        event_time=datetime(2024, 3, 4, 0, 0),
        open=1.1, high=1.2, low=1.0, close=1.15,
    )

    report = data_quality.evaluate_bars([naive], Timeframe.H1)

    assert DataQualityIssue.INVALID_TIMESTAMP.value in _issues(report)


def test_expected_bar_count():
    assert (
        data_quality.expected_bar_count(
            BASE_TIME, BASE_TIME + timedelta(hours=10), Timeframe.H1
        )
        == 10
    )
    assert data_quality.expected_bar_count(BASE_TIME, BASE_TIME, Timeframe.H1) == 0


@pytest.mark.parametrize(
    "timeframe,expected_seconds",
    [(Timeframe.M1, 60), (Timeframe.H1, 3600), (Timeframe.D1, 86400)],
)
def test_timeframe_deltas(timeframe, expected_seconds):
    assert timeframe.delta.total_seconds() == expected_seconds

class TestComparingWhatProvidersStored:
    """`detect_provider_conflicts` had no caller for eleven phases.

    It was tested the whole time - as a pure function, over dictionaries a test
    built by hand. What was missing was any path from stored bars to it, so the
    coverage was real and the detector had still never seen a live row.
    """

    def _store(self, session, instrument, code: str, closes: dict, *, revision: int = 1):
        """Write bars for one provider, the way ingestion writes them."""
        from app.models.instruments import Provider
        from app.models.market_data import Bar

        provider = session.scalar(select(Provider).where(Provider.code == code))
        if provider is None:
            provider = Provider(name=code, code=code, kind="market_data")
            session.add(provider)
            session.flush()

        for event_time, close in closes.items():
            session.add(
                Bar(
                    instrument_id=instrument.id,
                    provider_id=provider.id,
                    timeframe=Timeframe.H1,
                    event_time=event_time,
                    revision=revision,
                    ingested_at=event_time,
                    open=close,
                    high=close * 1.001,
                    low=close * 0.999,
                    close=close,
                    volume=1.0,
                    quality_score=1.0,
                )
            )
        session.flush()
        return provider

    def test_one_provider_is_unchecked_rather_than_clean(self, session, instrument):
        """A feed cannot disagree with itself, and saying `conflicts: 0` here
        would be a measurement nobody made."""
        moment = BASE_TIME + timedelta(hours=1)
        self._store(session, instrument, "alpha", {moment: 1.1000})

        result = data_quality.compare_providers(session, instrument.id, Timeframe.H1)

        assert result["compared"] is False
        assert "needs two" in result["reason"]

    def test_two_agreeing_providers_raise_nothing(self, session, instrument):
        moment = BASE_TIME + timedelta(hours=1)
        self._store(session, instrument, "alpha", {moment: 1.1000})
        self._store(session, instrument, "beta", {moment: 1.1001})

        result = data_quality.compare_providers(session, instrument.id, Timeframe.H1)

        assert result["compared"] is True
        assert result["conflicts"] == 0

    def test_a_real_disagreement_is_found_and_stored(self, session, instrument):
        moment = BASE_TIME + timedelta(hours=1)
        self._store(session, instrument, "alpha", {moment: 1.1000})
        self._store(session, instrument, "beta", {moment: 1.1500})

        result = data_quality.compare_providers(session, instrument.id, Timeframe.H1)

        assert result["conflicts"] == 1
        assert result["written"] == 1

    def test_a_correction_is_not_a_conflict(self, session, instrument):
        """A superseded bar disagreeing with a current one is one feed
        correcting itself, which is the system working. Comparing every
        revision would turn every correction into an error."""
        moment = BASE_TIME + timedelta(hours=1)
        self._store(session, instrument, "alpha", {moment: 9.9999}, revision=1)
        self._store(session, instrument, "alpha", {moment: 1.1000}, revision=2)
        self._store(session, instrument, "beta", {moment: 1.1001})

        result = data_quality.compare_providers(session, instrument.id, Timeframe.H1)

        assert result["conflicts"] == 0

    def test_only_shared_instants_are_compared(self, session, instrument):
        """A bar one feed has and the other does not is a gap, which has its
        own detector. Treating it as a conflict would report the same defect
        twice under two names."""
        first = BASE_TIME + timedelta(hours=1)
        second = BASE_TIME + timedelta(hours=2)
        self._store(session, instrument, "alpha", {first: 1.1000, second: 1.1000})
        self._store(session, instrument, "beta", {first: 1.1001})

        result = data_quality.compare_providers(session, instrument.id, Timeframe.H1)

        assert result["bars_compared"] == 1
        assert result["conflicts"] == 0

    def test_re_running_does_not_inflate_the_finding_count(self, session, instrument):
        """Checking a dataset twice must not make it look worse. The score is
        derived from stored findings, so a repeat that wrote a second row would
        decay the score for no reason but being looked at."""
        moment = BASE_TIME + timedelta(hours=1)
        self._store(session, instrument, "alpha", {moment: 1.1000})
        self._store(session, instrument, "beta", {moment: 1.1500})

        data_quality.compare_providers(session, instrument.id, Timeframe.H1)
        again = data_quality.compare_providers(session, instrument.id, Timeframe.H1)

        assert again["conflicts"] == 1
        assert again["written"] == 0

    def test_the_since_window_limits_what_is_read(self, session, instrument):
        old = BASE_TIME + timedelta(hours=1)
        recent = BASE_TIME + timedelta(days=20)
        self._store(session, instrument, "alpha", {old: 1.1000, recent: 1.2000})
        self._store(session, instrument, "beta", {old: 1.9000, recent: 1.2001})

        result = data_quality.compare_providers(
            session, instrument.id, Timeframe.H1, since=BASE_TIME + timedelta(days=10)
        )

        assert result["bars_compared"] == 1
        assert result["conflicts"] == 0
