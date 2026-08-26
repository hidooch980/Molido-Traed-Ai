"""Point-in-time regression tests (spec §6, §58 "future leakage").

These are the load-bearing tests of this milestone. If any of them fails, every
backtest and training run built on top of the data layer is untrustworthy.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.enums import Timeframe
from app.core.errors import InsufficientDataError, ValidationFailedError
from app.services.point_in_time import (
    data_freshness_seconds,
    get_bars,
    is_training_eligible,
    latest_bar,
)
from tests.conftest import BASE_TIME, insert_bar


def _seed(session, instrument, provider, count=10, ingested_at=None):
    ingested_at = ingested_at or BASE_TIME
    for i in range(count):
        insert_bar(
            session,
            instrument.id,
            provider.id,
            event_time=BASE_TIME + timedelta(hours=i),
            ingested_at=ingested_at,
            close=1.1000 + i * 0.0001,
        )


def test_unclosed_bar_is_invisible(session, instrument, provider):
    """A bar that opened before as_of but has not closed is future data."""
    _seed(session, instrument, provider, count=5)
    # The 02:00 bar closes at 03:00; at 02:30 it still contains unseen prices.
    as_of = BASE_TIME + timedelta(hours=2, minutes=30)

    bars = get_bars(session, instrument.id, Timeframe.H1, as_of)

    assert [b.event_time for b in bars] == [BASE_TIME, BASE_TIME + timedelta(hours=1)]
    assert all(b.event_time + Timeframe.H1.delta <= as_of for b in bars)


def test_exact_close_boundary_is_visible(session, instrument, provider):
    """A bar closing exactly at as_of is knowable — the boundary is inclusive."""
    _seed(session, instrument, provider, count=5)
    as_of = BASE_TIME + timedelta(hours=1)

    bars = get_bars(session, instrument.id, Timeframe.H1, as_of)

    assert [b.event_time for b in bars] == [BASE_TIME]


def test_late_ingested_row_is_invisible(session, instrument, provider):
    """A bar backfilled after as_of must not appear, despite an old event_time."""
    insert_bar(
        session,
        instrument.id,
        provider.id,
        event_time=BASE_TIME,
        ingested_at=BASE_TIME + timedelta(days=30),  # learned a month later
        close=1.1000,
    )
    as_of = BASE_TIME + timedelta(hours=5)

    assert get_bars(session, instrument.id, Timeframe.H1, as_of) == []
    # ...and becomes visible once as_of passes the moment we learned it.
    later = get_bars(session, instrument.id, Timeframe.H1, BASE_TIME + timedelta(days=31))
    assert len(later) == 1


def test_revision_visible_only_after_it_was_known(session, instrument, provider):
    """The revision current *at as_of* wins, not the newest revision overall."""
    revised_at = BASE_TIME + timedelta(days=10)
    insert_bar(
        session, instrument.id, provider.id,
        event_time=BASE_TIME, ingested_at=BASE_TIME, close=1.1000, revision=1,
    )
    insert_bar(
        session, instrument.id, provider.id,
        event_time=BASE_TIME, ingested_at=revised_at, close=1.2000, revision=2,
    )

    before = get_bars(session, instrument.id, Timeframe.H1, BASE_TIME + timedelta(hours=2))
    after = get_bars(session, instrument.id, Timeframe.H1, revised_at + timedelta(hours=1))

    assert [b.revision for b in before] == [1]
    assert before[0].close == pytest.approx(1.1000)
    assert [b.revision for b in after] == [2]
    assert after[0].close == pytest.approx(1.2000)


def test_lookback_returns_most_recent_and_is_chronological(session, instrument, provider):
    _seed(session, instrument, provider, count=10)
    as_of = BASE_TIME + timedelta(hours=10)

    bars = get_bars(session, instrument.id, Timeframe.H1, as_of, lookback=3)

    assert len(bars) == 3
    assert bars == sorted(bars, key=lambda b: b.event_time)
    assert bars[-1].event_time == BASE_TIME + timedelta(hours=9)


def test_start_bound_is_inclusive(session, instrument, provider):
    _seed(session, instrument, provider, count=10)
    start = BASE_TIME + timedelta(hours=4)

    bars = get_bars(
        session, instrument.id, Timeframe.H1, BASE_TIME + timedelta(hours=10), start=start
    )

    assert bars[0].event_time == start


def test_naive_as_of_is_rejected(session, instrument, provider):
    with pytest.raises(ValidationFailedError):
        get_bars(session, instrument.id, Timeframe.H1, datetime(2024, 3, 4, 12, 0))


def test_min_bars_raises_instead_of_returning_short_series(session, instrument, provider):
    """Insufficient history is an explicit error, never a quietly short list."""
    _seed(session, instrument, provider, count=3)

    with pytest.raises(InsufficientDataError):
        get_bars(
            session,
            instrument.id,
            Timeframe.H1,
            BASE_TIME + timedelta(hours=3),
            min_bars=50,
        )


def test_training_gate_defaults_to_ineligible(session, instrument, provider):
    """An unevaluated dataset is not eligible; absence of evidence is not a pass."""
    _seed(session, instrument, provider, count=5)

    assert is_training_eligible(session, instrument.id, Timeframe.H1) is False
    with pytest.raises(InsufficientDataError):
        get_bars(
            session,
            instrument.id,
            Timeframe.H1,
            BASE_TIME + timedelta(hours=5),
            require_training_eligible=True,
        )


def test_latest_bar_and_freshness(session, instrument, provider):
    _seed(session, instrument, provider, count=5)
    now = BASE_TIME + timedelta(hours=6)

    bar = latest_bar(session, instrument.id, Timeframe.H1, now)
    freshness = data_freshness_seconds(session, instrument.id, Timeframe.H1, now=now)

    assert bar is not None
    assert bar.event_time == BASE_TIME + timedelta(hours=4)
    # newest close is at 05:00, "now" is 06:00 -> one hour stale
    assert freshness == pytest.approx(3600.0)


def test_freshness_is_none_without_data(session, instrument, provider):
    assert (
        data_freshness_seconds(
            session, instrument.id, Timeframe.H1, now=datetime.now(UTC)
        )
        is None
    )


class TestLookbackIsBoundedWithoutChangingTheAnswer:
    """`lookback` is pushed inside the window function for speed.

    A window function is computed over every row the WHERE admits before an
    outer LIMIT can discard one, so asking for two bars used to rank an
    instrument's whole history to return two - 3.4 seconds of a 7.5 second
    page. The query now narrows to the newest `lookback` *event times* first.

    Narrowing by event time rather than by row is the part that has to be
    right, because several providers can cover one timestamp and then the two
    numbers differ. These tests pin the cases where a row limit and a timestamp
    limit disagree.
    """

    def test_two_providers_on_one_timestamp_still_fill_the_lookback(
        self, session, instrument, provider
    ):
        """The newest event time carries two rows, so `lookback=2` is both of
        them - not one row each from the two newest timestamps."""
        from app.models.instruments import Provider

        second = Provider(code="second", name="Second feed", capabilities={"ohlcv": True})
        session.add(second)
        session.flush()

        for source in (provider, second):
            for i in range(3):
                insert_bar(
                    session,
                    instrument.id,
                    source.id,
                    event_time=BASE_TIME + timedelta(hours=i),
                    ingested_at=BASE_TIME,
                    close=1.1000 + i * 0.0001,
                )

        bars = get_bars(
            session,
            instrument.id,
            Timeframe.H1,
            BASE_TIME + timedelta(hours=4),
            lookback=2,
        )

        assert len(bars) == 2
        # Both from the newest visible timestamp, one per provider.
        assert len({bar.event_time for bar in bars}) == 1
        assert len({bar.provider_id for bar in bars}) == 2

    def test_a_revision_does_not_consume_a_lookback_slot(
        self, session, instrument, provider
    ):
        """Revisions share an event time. Counting them as separate slots would
        make `lookback=2` return one bar and one older copy of it."""
        _seed(session, instrument, provider, count=3)
        newest = BASE_TIME + timedelta(hours=2)
        insert_bar(
            session,
            instrument.id,
            provider.id,
            event_time=newest,
            ingested_at=BASE_TIME,
            close=9.9999,
            revision=2,
        )

        bars = get_bars(
            session, instrument.id, Timeframe.H1, BASE_TIME + timedelta(hours=4), lookback=2
        )

        assert len(bars) == 2
        assert [bar.event_time for bar in bars] == [
            BASE_TIME + timedelta(hours=1),
            newest,
        ]
        assert bars[-1].close == pytest.approx(9.9999)

    def test_the_bound_respects_the_same_visibility_rules(
        self, session, instrument, provider
    ):
        """The horizon that narrows the scan must not see a row the caller
        cannot. If it did, an unknown-yet bar would occupy a slot and push a
        visible one out of the answer."""
        _seed(session, instrument, provider, count=3)
        # Known only later - invisible at the instant asked about.
        insert_bar(
            session,
            instrument.id,
            provider.id,
            event_time=BASE_TIME + timedelta(hours=3),
            ingested_at=BASE_TIME + timedelta(days=30),
            close=5.5555,
        )

        bars = get_bars(
            session, instrument.id, Timeframe.H1, BASE_TIME + timedelta(hours=5), lookback=2
        )

        assert len(bars) == 2
        assert all(bar.close != pytest.approx(5.5555) for bar in bars)
        assert bars[-1].event_time == BASE_TIME + timedelta(hours=2)

    def test_asking_for_more_than_exists_returns_what_exists(
        self, session, instrument, provider
    ):
        _seed(session, instrument, provider, count=3)

        bars = get_bars(
            session, instrument.id, Timeframe.H1, BASE_TIME + timedelta(hours=9), lookback=50
        )

        assert len(bars) == 3

    def test_a_start_bound_and_a_lookback_together_still_agree(
        self, session, instrument, provider
    ):
        _seed(session, instrument, provider, count=6)

        bars = get_bars(
            session,
            instrument.id,
            Timeframe.H1,
            BASE_TIME + timedelta(hours=9),
            start=BASE_TIME + timedelta(hours=3),
            lookback=2,
        )

        assert [bar.event_time for bar in bars] == [
            BASE_TIME + timedelta(hours=4),
            BASE_TIME + timedelta(hours=5),
        ]
