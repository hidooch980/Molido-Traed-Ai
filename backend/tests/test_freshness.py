"""Freshness per source, judged in each source's own bars."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.enums import Timeframe
from app.ops import freshness
from tests.conftest import insert_bar

NOW = datetime(2026, 9, 2, 20, 30, tzinfo=UTC)


def bars(session, instrument, provider, *, last: datetime, timeframe=Timeframe.H1, count=3):
    step = timeframe.delta
    for i in range(count):
        when = last - step * (count - 1 - i)
        insert_bar(
            session,
            instrument.id,
            provider.id,
            event_time=when,
            ingested_at=when + timedelta(seconds=30),
            close=1.1 + i * 0.001,
            timeframe=timeframe,
        )
    session.commit()


class TestAges:
    def test_a_bar_that_closed_within_the_last_hour_is_fresh(self, session, instrument, provider):
        bars(session, instrument, provider, last=NOW - timedelta(hours=1, minutes=10))
        report = freshness.measure(session, now=NOW)

        assert report.fresh is True
        assert report.best_decision_age_bars is not None and report.best_decision_age_bars < 1.0
        assert report.sources[0].provider == "test"

    def test_a_source_hours_behind_is_stale(self, session, instrument, provider):
        bars(session, instrument, provider, last=NOW - timedelta(hours=9))
        report = freshness.measure(session, now=NOW)

        assert report.fresh is False
        assert report.stale_sources == ["test/H1"] if hasattr(report, "stale_sources") else True
        assert report.as_dict()["stale_sources"] == ["test/H1"]

    def test_nothing_written_is_unknown_not_fresh(self, session):
        report = freshness.measure(session, now=NOW)

        assert report.best_decision_age_bars is None
        assert report.fresh is False

    def test_a_fresh_daily_source_does_not_make_hourly_decisions_fresh(self, session, instrument, provider):
        bars(session, instrument, provider, last=NOW - timedelta(days=1), timeframe=Timeframe.D1)
        report = freshness.measure(session, now=NOW)

        assert report.decision_sources == []
        assert report.fresh is False
        assert report.sources[0].fresh is True  # the daily source itself is current
