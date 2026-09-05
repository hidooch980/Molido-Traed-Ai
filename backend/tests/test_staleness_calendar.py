"""A shut market is not a dead feed.

Every Saturday at 02:45 UTC the collector reported every instrument on every
timeframe as CRITICAL stale. The cause was a seam between two correct pieces:
the sweep skips a market only once it has been closed for six hours -
deliberately, because a session's final bars often arrive late - and the
staleness check inside that grace window measured wall-clock age against a
market that had been shut since Friday and was behaving exactly as it should.

The cost was not noise. Nothing in this codebase resolves a data-quality
finding, and one unresolved error-level finding blocks its dataset's training
eligibility permanently, so each weekend spent eligibility that could never
be won back.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

from app.core.enums import Timeframe
from app.services import data_quality
from app.services.sessions import SessionCalendar, TradingWindow

#: Friday 21:00 UTC, the weekly close.
CLOSE = datetime(2026, 9, 4, 21, 0, tzinfo=UTC)


def forex_calendar() -> SessionCalendar:
    """Open Sunday 21:00 through Friday 21:00, shut over the weekend."""
    windows = [
        TradingWindow(day=day, open=time(0, 0), close=time(23, 59))
        for day in range(0, 4)  # Monday-Thursday, whole day
    ]
    windows.append(TradingWindow(day=4, open=time(0, 0), close=time(21, 0)))  # Friday
    windows.append(TradingWindow(day=6, open=time(21, 0), close=time(23, 59)))  # Sunday
    return SessionCalendar(timezone="UTC", windows=windows, holidays={})


class TestTheWeekendIsNotAnOutage:
    def test_the_saturday_false_positive_is_gone(self):
        """The exact case that fired: 02:45 on Saturday, five and three
        quarter hours after the close."""
        finding = data_quality.check_staleness(
            CLOSE,
            Timeframe.H1,
            now=datetime(2026, 9, 5, 2, 45, tzinfo=UTC),
            calendar=forex_calendar(),
        )

        assert finding is None

    def test_it_stays_quiet_all_weekend(self):
        """Not just at the moment the grace window ends. The market is shut
        until Sunday evening and none of it is the feed's doing."""
        for hours in (6, 12, 24, 36, 44):
            finding = data_quality.check_staleness(
                CLOSE,
                Timeframe.H1,
                now=CLOSE + timedelta(hours=hours),
                calendar=forex_calendar(),
            )

            assert finding is None, f"fired {hours}h after the close"

    def test_a_feed_that_dies_while_the_market_trades_still_fires(self):
        """The check must still do its job. This is the defect the whole
        detector exists for: bars stop arriving during a session, and none of
        the other detectors can see bars that never came."""
        midweek = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)  # Wednesday
        finding = data_quality.check_staleness(
            midweek,
            Timeframe.H1,
            now=midweek + timedelta(hours=8),
            calendar=forex_calendar(),
        )

        assert finding is not None
        assert "open bars missed" in (finding.observed or "")

    def test_a_feed_dead_across_the_weekend_fires_once_the_market_reopens(self):
        """Silence over a weekend is expected; silence into Monday is not."""
        finding = data_quality.check_staleness(
            CLOSE,
            Timeframe.H1,
            now=datetime(2026, 9, 7, 12, 0, tzinfo=UTC),  # Monday midday
            calendar=forex_calendar(),
        )

        assert finding is not None

    def test_a_gap_no_market_could_explain_fires_without_walking_the_calendar(self):
        """No exchange shuts for ten days. Past that the feed is the
        explanation whatever the schedule says - and it also bounds the walk,
        which would otherwise step a dead M1 feed a minute at a time across
        however long it has been dead."""
        finding = data_quality.check_staleness(
            CLOSE,
            Timeframe.M1,
            now=CLOSE + data_quality.MAX_PLAUSIBLE_CLOSURE + timedelta(days=1),
            calendar=forex_calendar(),
        )

        assert finding is not None
        assert "old" in (finding.observed or "")


class TestNothingChangesWithoutACalendar:
    """Every existing caller passes none, and none of them should shift."""

    def test_wall_clock_behaviour_is_kept_exactly(self):
        stale = data_quality.check_staleness(
            CLOSE, Timeframe.H1, now=CLOSE + timedelta(hours=6)
        )
        fresh = data_quality.check_staleness(
            CLOSE, Timeframe.H1, now=CLOSE + timedelta(hours=1)
        )

        assert stale is not None
        assert fresh is None

    def test_no_data_at_all_is_still_critical_either_way(self):
        with_calendar = data_quality.check_staleness(
            None, Timeframe.H1, now=CLOSE, calendar=forex_calendar()
        )
        without = data_quality.check_staleness(None, Timeframe.H1, now=CLOSE)

        assert with_calendar is not None
        assert without is not None

    def test_a_fresh_feed_is_never_walked(self):
        """The cheap wall-clock test decides the ordinary case. Market-open
        time cannot exceed wall-clock time, so inside the wall-clock limit is
        inside the calendar limit, and a calendar that raised here would be a
        calendar nobody needed to consult."""

        class Exploding:
            def is_open(self, _moment):
                raise AssertionError("the calendar was consulted unnecessarily")

        assert (
            data_quality.check_staleness(
                CLOSE, Timeframe.H1, now=CLOSE + timedelta(minutes=30), calendar=Exploding()
            )
            is None
        )
