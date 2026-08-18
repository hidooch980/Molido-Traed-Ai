"""Folding the hourly series into daily bars, and the three ways that lies.

The one timeframe with a measured edge has no live feed: the deep-history
provider stops on 2025-12-31 and serves nothing after it. The hourly series is
current, and twenty-four of its bars are a daily one - so the daily series is
built rather than fetched.

Every test here is about a bar that would look real and be wrong: a day that
has not finished, a day that barely traded, and a derived row that cannot be
told from an observed one.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.workers.aggregate import (
    DERIVED_PROVIDER,
    MIN_HOURS_PER_DAY,
    daily_from_hourly,
)

TODAY = date(2026, 8, 18)


def hours(day: int, count: int, *, base: float = 1.1000, step: float = 0.001):
    """`count` hourly bars on `day`, each a little higher than the last."""
    return [
        (
            datetime(2026, 8, day, hour, tzinfo=UTC),
            base + hour * step,
            base + hour * step + 0.0010,
            base + hour * step - 0.0010,
            base + hour * step + 0.0005,
        )
        for hour in range(count)
    ]


class TestTheBarDescribesTheDayAsItWasTraded:
    def test_a_full_day_folds_into_one_bar(self):
        built = daily_from_hourly(hours(17, 24), today=TODAY)

        assert len(built) == 1
        assert built[0]["event_time"] == datetime(2026, 8, 17, tzinfo=UTC)

    def test_the_open_is_the_first_hour_s_open(self):
        source = hours(17, 24)

        built = daily_from_hourly(source, today=TODAY)

        assert built[0]["open"] == source[0][1]

    def test_the_close_is_the_last_hour_s_close(self):
        source = hours(17, 24)

        built = daily_from_hourly(source, today=TODAY)

        assert built[0]["close"] == source[-1][4]

    def test_the_high_and_low_span_every_hour(self):
        source = hours(17, 24)

        built = daily_from_hourly(source, today=TODAY)

        assert built[0]["high"] == max(hour[2] for hour in source)
        assert built[0]["low"] == min(hour[3] for hour in source)

    def test_unordered_input_still_opens_and_closes_correctly(self):
        """Rows arrive from a query, and a query without an order by is not
        ordered. Sorting by the clock rather than by arrival is what makes
        the open the open."""
        source = hours(17, 24)

        forwards = daily_from_hourly(source, today=TODAY)
        backwards = daily_from_hourly(list(reversed(source)), today=TODAY)

        assert forwards == backwards

    def test_several_days_fold_separately(self):
        built = daily_from_hourly(hours(15, 24) + hours(16, 24), today=TODAY)

        assert [bar["event_time"].date() for bar in built] == [
            date(2026, 8, 15),
            date(2026, 8, 16),
        ]


class TestAnUnfinishedDayIsNotABar:
    """A partial day emitted as closed is the same error as reading a series
    at "now" rather than at the decision instant: the high and the low keep
    moving after the rule has looked at them."""

    def test_today_is_excluded_however_many_hours_it_has(self):
        built = daily_from_hourly(hours(18, 23), today=TODAY)

        assert built == []

    def test_today_is_excluded_beside_a_finished_day(self):
        built = daily_from_hourly(hours(17, 24) + hours(18, 23), today=TODAY)

        assert [bar["event_time"].date() for bar in built] == [date(2026, 8, 17)]

    def test_a_future_day_is_excluded_too(self):
        """A clock ahead of the data is a real condition, and a bar from it
        would be a bar from a day nobody has traded."""
        built = daily_from_hourly(hours(19, 24), today=TODAY)

        assert built == []


class TestAThinDayIsUnmeasuredRatherThanQuiet:
    """A day holding three bars has a high and a low and they describe three
    hours. Ranked against instruments that had a full session, the difference
    reads as signal."""

    def test_a_day_below_the_minimum_is_dropped(self):
        built = daily_from_hourly(hours(17, 3), today=TODAY)

        assert built == []

    def test_a_day_at_the_minimum_is_kept(self):
        built = daily_from_hourly(hours(17, MIN_HOURS_PER_DAY), today=TODAY)

        assert len(built) == 1

    def test_the_minimum_allows_a_short_friday(self):
        """The FX week is not twenty-four hours everywhere, so this has to sit
        well under a full day or it drops every Friday."""
        assert MIN_HOURS_PER_DAY <= 16

    def test_the_minimum_is_far_above_a_gap(self):
        assert MIN_HOURS_PER_DAY >= 6

    def test_the_hour_count_travels_with_the_bar(self):
        """So the caller can score it rather than take it at face value."""
        built = daily_from_hourly(hours(17, 20), today=TODAY)

        assert built[0]["hours"] == 20


class TestADerivedRowSaysSo:
    def test_it_is_written_under_its_own_provider(self):
        """Not the deep-history one. Mixing a fetched series with a derived
        one makes the twenty-one year measurement irreproducible."""
        assert DERIVED_PROVIDER == "aggregated"

    def test_the_provider_is_not_a_real_feed_name(self):
        for feed in ("yfinance", "dukascopy", "metatrader"):
            assert DERIVED_PROVIDER != feed


class TestEmptyInput:
    def test_no_bars_builds_nothing(self):
        assert daily_from_hourly([], today=TODAY) == []

    def test_it_does_not_raise_on_a_single_hour(self):
        assert daily_from_hourly(hours(17, 1), today=TODAY) == []
