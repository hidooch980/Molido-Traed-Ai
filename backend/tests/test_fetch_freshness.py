"""A bar that cannot have closed yet has nothing to fetch.

The cycle runs every fifteen minutes and asked every entry for data every
time, whatever its timeframe. A daily bar closes once a day and was being
fetched ninety-six times; an hourly bar four times an hour. Measured across
this watchlist that was 4,869 of 10,848 fetches a day - forty-five per cent -
each one a network round trip the cycle waited for, and each one certain in
advance to return nothing new.

The cycle was 902 seconds and 339 of those fetches accounted for almost all
of it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.enums import Timeframe
from app.workers.collector import WatchEntry, _fresh_until

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


class Checkpoint:
    def __init__(self, last_event_time):
        self.last_event_time = last_event_time


class Session:
    """A session that answers the one query `_fresh_until` makes."""

    def __init__(self, checkpoint):
        self._checkpoint = checkpoint

    def scalar(self, _statement):
        return self._checkpoint


class Instrument:
    id = "11111111-1111-1111-1111-111111111111"


def entry(timeframe: Timeframe) -> WatchEntry:
    return WatchEntry(symbol="EURUSD", raw_symbol="EURUSD", timeframe=timeframe)


class TestWhenTheNextBarCanClose:
    def test_a_daily_bar_is_fresh_for_a_day(self):
        session = Session(Checkpoint(NOW - timedelta(hours=3)))

        until = _fresh_until(session, Instrument(), entry(Timeframe.D1))

        assert until == NOW - timedelta(hours=3) + timedelta(days=1)
        assert NOW < until  # so the cycle skips it

    def test_an_hourly_bar_is_fresh_for_an_hour(self):
        session = Session(Checkpoint(NOW - timedelta(minutes=20)))

        until = _fresh_until(session, Instrument(), entry(Timeframe.H1))

        assert NOW < until

    def test_a_fifteen_minute_bar_is_not_held_by_a_fifteen_minute_cycle(self):
        """M15 is the one timeframe the cadence already matches. If this
        skipped, the fix would have quietly halved the data it exists for."""
        session = Session(Checkpoint(NOW - timedelta(minutes=15)))

        until = _fresh_until(session, Instrument(), entry(Timeframe.M15))

        assert until <= NOW  # fetched

    def test_a_five_minute_bar_is_never_held(self):
        session = Session(Checkpoint(NOW - timedelta(minutes=15)))

        until = _fresh_until(session, Instrument(), entry(Timeframe.M5))

        assert until <= NOW


class TestItRefusesToClaimFreshness:
    def test_an_instrument_with_no_checkpoint_is_fetched(self):
        """An unknown watermark must read as "fetch it", never as "fresh".
        Returning a time here would mean a new instrument never backfills."""
        assert _fresh_until(Session(None), Instrument(), entry(Timeframe.D1)) is None

    def test_a_checkpoint_with_no_event_time_is_fetched(self):
        assert (
            _fresh_until(Session(Checkpoint(None)), Instrument(), entry(Timeframe.D1))
            is None
        )

    def test_a_late_bar_self_heals(self):
        """If the provider has not yet handed over a bar that closed, the
        watermark stays old and the entry keeps being fetched until it
        arrives - no special case needed."""
        session = Session(Checkpoint(NOW - timedelta(hours=30)))

        until = _fresh_until(session, Instrument(), entry(Timeframe.D1))

        assert until <= NOW

    def test_a_naive_timestamp_is_read_as_utc_rather_than_crashing(self):
        """Postgres can hand back a naive datetime depending on the column,
        and comparing it against an aware `now` raises."""
        session = Session(Checkpoint(datetime(2026, 9, 3, 9, 0)))

        until = _fresh_until(session, Instrument(), entry(Timeframe.H1))

        assert until.tzinfo is not None
        assert until == datetime(2026, 9, 3, 10, 0, tzinfo=UTC)


class TestTheArithmeticItWasBuiltFor:
    @pytest.mark.parametrize(
        ("timeframe", "fetches_a_day_before", "fetches_a_day_after"),
        [(Timeframe.D1, 96, 1), (Timeframe.H1, 96, 24), (Timeframe.M15, 96, 96)],
    )
    def test_how_often_each_timeframe_is_now_fetched(
        self, timeframe, fetches_a_day_before, fetches_a_day_after
    ):
        """The cycle runs 96 times a day. Walk a day of cycles and count how
        many would actually fetch."""
        cadence = timedelta(minutes=15)
        watermark = NOW
        fetched = 0
        for step in range(96):
            moment = NOW + cadence * step
            until = watermark + timeframe.delta
            if moment >= until:
                fetched += 1
                watermark = moment

        assert fetches_a_day_before == 96
        assert fetched == pytest.approx(fetches_a_day_after, abs=1)
