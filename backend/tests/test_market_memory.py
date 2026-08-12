"""Market memory tests (phase 9).

Memory summarises a window. The properties that matter: it cannot see past its
cutoff, it refuses to speak on too little evidence, and its "trend" label is
earned rather than assumed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.enums import Timeframe
from app.core.errors import ValidationFailedError
from app.services import market_memory
from app.services.market_memory import MemoryHorizon
from app.services.point_in_time import get_bars
from tests.conftest import BASE_TIME, insert_bar


def now() -> datetime:
    return datetime.now(UTC)


def after(count: int) -> datetime:
    """Cutoff just past `count` seeded hourly bars.

    Memory windows are *durations* ending at the cutoff, so reading with
    `now()` against 2024 fixture data correctly finds an empty window. Tests
    about measurement must therefore stand where the data is.
    """
    return BASE_TIME + timedelta(hours=count)


def seed(session, instrument, provider, count, *, drift=0.0002, start=None, price=1.10):
    start = start or BASE_TIME
    for i in range(count):
        close = price + i * drift
        insert_bar(
            session,
            instrument.id,
            provider.id,
            event_time=start + timedelta(hours=i),
            ingested_at=BASE_TIME,
            close=round(close, 8),
            open_=round(close - drift, 8),
        )


def seed_noise(session, instrument, provider, count, *, start=None, price=1.10, step=0.002):
    """Alternating up/down: real movement, no net direction."""
    start = start or BASE_TIME
    for i in range(count):
        close = price + (step if i % 2 == 0 else 0.0)
        insert_bar(
            session,
            instrument.id,
            provider.id,
            event_time=start + timedelta(hours=i),
            ingested_at=BASE_TIME,
            close=round(close, 8),
            open_=round(price, 8),
        )


# ------------------------------------------------------------------ horizons
class TestHorizons:
    def test_all_three_are_always_present(self, session, instrument, provider):
        """A missing key would look like a horizon nobody asked for."""
        seed(session, instrument, provider, 60)

        memory = market_memory.recall_all(
            session, instrument.id, Timeframe.H1, after(60)
        )

        assert set(memory) == set(MemoryHorizon)

    def test_thin_horizon_is_named_not_faked(self, session, instrument, provider):
        # 60 H1 bars: enough for short (20), not for medium (100) or long (250).
        seed(session, instrument, provider, 60)

        memory = market_memory.recall_all(
            session, instrument.id, Timeframe.H1, after(60)
        )

        assert memory[MemoryHorizon.SHORT].available is True
        assert memory[MemoryHorizon.MEDIUM].available is False
        assert "needs 100 bars" in memory[MemoryHorizon.MEDIUM].reason

    def test_short_horizon_looks_back_only_three_days(self, session, instrument, provider):
        """The window is a duration, not 'everything stored'."""
        seed(session, instrument, provider, 500)
        cutoff = BASE_TIME + timedelta(hours=500)

        snap = market_memory.recall(
            session, instrument.id, Timeframe.H1, cutoff, MemoryHorizon.SHORT
        )

        assert snap.available
        assert snap.bars <= 73  # 3 days of H1, plus the boundary bar
        assert snap.window_start >= cutoff - timedelta(days=3, hours=1)

    def test_empty_window_is_reported(self, session, instrument, provider):
        seed(session, instrument, provider, 300)
        # A cutoff long after the data ends: the 3-day window contains nothing.
        far_future = BASE_TIME + timedelta(days=400)

        snap = market_memory.recall(
            session, instrument.id, Timeframe.H1, far_future, MemoryHorizon.SHORT
        )

        assert snap.available is False
        assert snap.reason == "no bars in the window"

    def test_naive_as_of_is_refused(self, session, instrument, provider):
        with pytest.raises(ValidationFailedError):
            market_memory.recall(
                session,
                instrument.id,
                Timeframe.H1,
                datetime(2024, 3, 4, 12, 0),
                MemoryHorizon.SHORT,
            )

    def test_calendar_timeframes_are_refused(self, session, instrument, provider):
        with pytest.raises(ValidationFailedError):
            market_memory.recall(
                session, instrument.id, Timeframe.MN1, now(), MemoryHorizon.LONG
            )


# ------------------------------------------------------------- point-in-time
class TestPointInTime:
    def test_future_bars_cannot_change_a_past_memory(self, session, instrument, provider):
        seed(session, instrument, provider, 200)
        cutoff = BASE_TIME + timedelta(hours=200)
        before = market_memory.recall(
            session, instrument.id, Timeframe.H1, cutoff, MemoryHorizon.SHORT
        ).as_dict()

        for i in range(200, 400):
            insert_bar(
                session,
                instrument.id,
                provider.id,
                event_time=BASE_TIME + timedelta(hours=i),
                ingested_at=BASE_TIME,
                close=99.0,
            )

        after = market_memory.recall(
            session, instrument.id, Timeframe.H1, cutoff, MemoryHorizon.SHORT
        ).as_dict()

        assert before == after


# --------------------------------------------------------------- measurements
class TestMeasurements:
    def test_rising_market_is_labelled_up(self, session, instrument, provider):
        seed(session, instrument, provider, 200)

        snap = market_memory.recall(
            session, instrument.id, Timeframe.H1, after(200), MemoryHorizon.SHORT
        )

        assert snap.trend == "up"
        assert snap.return_pct > 0
        assert snap.trend_strength > 1.0

    def test_falling_market_is_labelled_down(self, session, instrument, provider):
        seed(session, instrument, provider, 200, drift=-0.0002, price=1.30)

        snap = market_memory.recall(
            session, instrument.id, Timeframe.H1, after(200), MemoryHorizon.SHORT
        )

        assert snap.trend == "down"
        assert snap.return_pct < 0

    def test_choppy_market_is_sideways_not_a_weak_trend(
        self, session, instrument, provider
    ):
        """Movement without direction must not be dressed up as a trend."""
        seed_noise(session, instrument, provider, 200)

        snap = market_memory.recall(
            session, instrument.id, Timeframe.H1, after(200), MemoryHorizon.SHORT
        )

        assert snap.trend == "sideways"
        assert abs(snap.trend_strength) < 1.0

    def test_position_in_range_is_one_at_a_new_high(self, session, instrument, provider):
        seed(session, instrument, provider, 200)

        snap = market_memory.recall(
            session, instrument.id, Timeframe.H1, after(200), MemoryHorizon.SHORT
        )

        # Not exactly 1.0: the last bar's own upper wick sits above its close,
        # and over a 72-bar window that wick is a real fraction of the range.
        assert snap.position_in_range > 0.9
        assert snap.bars_since_high == 0

    def test_position_in_range_is_zero_at_a_new_low(self, session, instrument, provider):
        seed(session, instrument, provider, 200, drift=-0.0002, price=1.30)

        snap = market_memory.recall(
            session, instrument.id, Timeframe.H1, after(200), MemoryHorizon.SHORT
        )

        # Mirror of the high case: the last bar's lower wick keeps the close
        # just off the window's absolute low.
        assert snap.position_in_range < 0.1
        assert snap.bars_since_low == 0

    def test_drawdown_is_measured_not_assumed(self, session, instrument, provider):
        """Up 100 bars, then down 50: the drawdown is the round trip."""
        for i in range(100):
            close = 1.10 + i * 0.001
            insert_bar(
                session, instrument.id, provider.id,
                event_time=BASE_TIME + timedelta(hours=i),
                ingested_at=BASE_TIME, close=round(close, 8),
            )
        peak = 1.10 + 99 * 0.001
        for i in range(100, 150):
            close = peak - (i - 99) * 0.001
            insert_bar(
                session, instrument.id, provider.id,
                event_time=BASE_TIME + timedelta(hours=i),
                ingested_at=BASE_TIME, close=round(close, 8),
            )

        bars = get_bars(session, instrument.id, Timeframe.H1, after(200), lookback=500)
        snap = market_memory.summarise(MemoryHorizon.SHORT, bars)

        assert snap.max_drawdown_pct == pytest.approx(50 * 0.001 / peak, rel=0.02)
        assert snap.bars_since_high == 50

    def test_flat_market_has_no_position_in_range(self, session, instrument, provider):
        """A window with no range has no position in it — None, not 0.5."""
        for i in range(60):
            insert_bar(
                session,
                instrument.id,
                provider.id,
                event_time=BASE_TIME + timedelta(hours=i),
                ingested_at=BASE_TIME,
                close=1.10,
            )
        bars = get_bars(session, instrument.id, Timeframe.H1, after(60), lookback=100)
        # Collapse the wicks the fixture adds, so the window is genuinely flat.
        for bar in bars:
            object.__setattr__(bar, "high", 1.10)
            object.__setattr__(bar, "low", 1.10)

        snap = market_memory.summarise(MemoryHorizon.SHORT, bars)

        assert snap.position_in_range is None
        assert snap.max_drawdown_pct == 0.0


def test_summarise_refuses_a_short_window():
    snap = market_memory.summarise(MemoryHorizon.LONG, [])

    assert snap.available is False
    assert "needs 250 bars" in snap.reason


# ----------------------------------------------------------------- agreement
class TestAgreement:
    def _snap(self, horizon, trend):
        return market_memory.MemorySnapshot(
            horizon=horizon, available=True, trend=trend, trend_strength=2.0
        )

    def test_aligned_horizons_are_reported_as_aligned(self):
        result = market_memory.agreement(
            {
                MemoryHorizon.SHORT: self._snap(MemoryHorizon.SHORT, "up"),
                MemoryHorizon.MEDIUM: self._snap(MemoryHorizon.MEDIUM, "up"),
                MemoryHorizon.LONG: self._snap(MemoryHorizon.LONG, "up"),
            }
        )

        assert result["aligned"] is True
        assert result["direction"] == "up"

    def test_conflict_is_named_not_resolved(self):
        """A short-term move against the long trend is a fact, not a verdict."""
        result = market_memory.agreement(
            {
                MemoryHorizon.SHORT: self._snap(MemoryHorizon.SHORT, "down"),
                MemoryHorizon.LONG: self._snap(MemoryHorizon.LONG, "up"),
            }
        )

        assert result["aligned"] is False
        assert result["direction"] is None
        assert set(result["conflict"]) == {"short", "long"}

    def test_sideways_horizons_do_not_count_as_direction(self):
        result = market_memory.agreement(
            {
                MemoryHorizon.SHORT: self._snap(MemoryHorizon.SHORT, "sideways"),
                MemoryHorizon.LONG: self._snap(MemoryHorizon.LONG, "up"),
            }
        )

        assert result["aligned"] is None
        assert "not enough directional horizons" in result["note"]
