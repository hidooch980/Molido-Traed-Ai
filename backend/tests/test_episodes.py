"""Episode tests (phase 10).

An episode joins state-before to outcome-after across one timestamp. Every
test here exists to stop that join leaking backwards — a leak that a backtest
cannot detect, because the backtest is the thing being fooled.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.enums import Timeframe
from app.core.errors import InsufficientDataError, ValidationFailedError
from app.models.episodes import Episode
from app.services import episodes
from app.services.point_in_time import get_bars
from tests.conftest import BASE_TIME, insert_bar


def after(count: int) -> datetime:
    return BASE_TIME + timedelta(hours=count)


def seed(session, instrument, provider, count, *, drift=0.0002, price=1.10):
    for i in range(count):
        close = price + i * drift
        insert_bar(
            session,
            instrument.id,
            provider.id,
            event_time=BASE_TIME + timedelta(hours=i),
            ingested_at=BASE_TIME,
            close=round(close, 8),
            open_=round(close - drift, 8),
        )


# ------------------------------------------------------------ the maturity rule
class TestMaturity:
    def test_immature_episodes_are_not_built(self, session, instrument, provider):
        """The last `horizon` bars are not episodes yet — their future is unwritten."""
        seed(session, instrument, provider, 300)

        result = episodes.build(
            session,
            instrument.id,
            Timeframe.H1,
            start=BASE_TIME + timedelta(hours=100),
            end=after(300),
            horizon_bars=24,
            as_of=after(300),
        )

        assert result.built > 0
        assert result.skipped_immature >= 24

    def test_outcome_ready_at_is_after_the_event(self, session, instrument, provider):
        seed(session, instrument, provider, 300)
        episodes.build(
            session, instrument.id, Timeframe.H1,
            start=after(100), end=after(200), horizon_bars=24, as_of=after(300),
        )

        row = session.scalars(select_all()).first()

        assert row.outcome_ready_at > row.event_time
        assert row.outcome_ready_at == row.event_time + timedelta(hours=25)

    def test_query_hides_episodes_whose_window_is_still_open(
        self, session, instrument, provider
    ):
        """The core leakage guard.

        An episode at T with a 24-bar horizon is not evidence until T+25h. A
        decision made at T+5h must not see it — its outcome had not happened.
        """
        seed(session, instrument, provider, 300)
        episodes.build(
            session, instrument.id, Timeframe.H1,
            start=after(100), end=after(200), horizon_bars=24, as_of=after(300),
        )

        first = session.scalars(select_all()).first()
        just_after_event = first.event_time + timedelta(hours=5)

        visible = episodes.query(session, instrument.id, Timeframe.H1, just_after_event)

        assert all(e.outcome_ready_at <= just_after_event for e in visible)
        assert first.id not in {e.id for e in visible}

    def test_maturity_gate_in_isolation(self, session, instrument):
        """Two episodes, identical but for maturity.

        `query` applies two independent filters — outcome maturity and
        `computed_at`. Built episodes always carry `computed_at = now`, which
        would mask the maturity filter in any fixture dated in the past. These
        rows are written by hand so the maturity rule is the only thing under
        test.
        """
        long_ago = BASE_TIME - timedelta(days=1)
        matured = Episode(
            instrument_id=instrument.id,
            timeframe=Timeframe.H1,
            event_time=after(10),
            horizon_bars=24,
            outcome_ready_at=after(35),
            computed_at=long_ago,
            entry_price=1.10,
        )
        still_open = Episode(
            instrument_id=instrument.id,
            timeframe=Timeframe.H1,
            event_time=after(20),
            horizon_bars=24,
            outcome_ready_at=after(45),
            computed_at=long_ago,
            entry_price=1.10,
        )
        session.add_all([matured, still_open])
        session.flush()

        # At hour 40: the first window has closed, the second has not.
        visible = {e.id for e in episodes.query(
            session, instrument.id, Timeframe.H1, after(40)
        )}

        assert matured.id in visible
        assert still_open.id not in visible, "an open window is not evidence"

    def test_query_reveals_a_built_episode_once_everything_has_settled(
        self, session, instrument, provider
    ):
        seed(session, instrument, provider, 300)
        episodes.build(
            session, instrument.id, Timeframe.H1,
            start=after(100), end=after(200), horizon_bars=24, as_of=after(300),
        )
        first = session.scalars(select_all()).first()

        visible = episodes.query(
            session, instrument.id, Timeframe.H1, datetime.now(UTC)
        )

        assert first.id in {e.id for e in visible}

    def test_query_respects_computed_at(self, session, instrument, provider):
        """An episode built today is not evidence for a decision replayed last year."""
        seed(session, instrument, provider, 300)
        episodes.build(
            session, instrument.id, Timeframe.H1,
            start=after(100), end=after(200), horizon_bars=24, as_of=after(300),
        )

        # computed_at is "now" (2026); an as_of in the fixture's 2024 predates it.
        visible = episodes.query(session, instrument.id, Timeframe.H1, after(400))

        assert visible == []

    def test_naive_as_of_is_refused(self, session, instrument, provider):
        with pytest.raises(ValidationFailedError):
            episodes.query(
                session, instrument.id, Timeframe.H1, datetime(2024, 3, 4, 12, 0)
            )


def select_all():
    from sqlalchemy import select

    return select(Episode).order_by(Episode.event_time)


# ---------------------------------------------------------------- state half
class TestStateIsPastOnly:
    def test_features_cannot_see_the_future(self, session, instrument, provider):
        """Rebuild after adding absurd future bars; the snapshot must not move."""
        seed(session, instrument, provider, 300)
        episodes.build(
            session, instrument.id, Timeframe.H1,
            start=after(100), end=after(150), horizon_bars=24,
            as_of=after(300), feature_names=["sma_20"],
        )
        before = {
            e.event_time: dict(e.features) for e in session.scalars(select_all())
        }

        for i in range(300, 500):
            insert_bar(
                session, instrument.id, provider.id,
                event_time=BASE_TIME + timedelta(hours=i),
                ingested_at=BASE_TIME, close=99.0,
            )
        episodes.build(
            session, instrument.id, Timeframe.H1,
            start=after(100), end=after(150), horizon_bars=24,
            as_of=after(500), feature_names=["sma_20"], recompute=True,
        )
        after_rebuild = {
            e.event_time: dict(e.features) for e in session.scalars(select_all())
        }

        assert before == after_rebuild

    def test_session_labels_are_recorded(self, session, instrument, provider):
        seed(session, instrument, provider, 300)
        episodes.build(
            session, instrument.id, Timeframe.H1,
            start=after(100), end=after(150), horizon_bars=24, as_of=after(300),
        )

        row = session.scalars(select_all()).first()

        assert isinstance(row.session_labels, list)
        assert row.session_labels


# -------------------------------------------------------------- outcome half
class TestOutcome:
    def _bars(self, session, instrument, provider, closes):
        for i, close in enumerate(closes):
            insert_bar(
                session, instrument.id, provider.id,
                event_time=BASE_TIME + timedelta(hours=i),
                ingested_at=BASE_TIME, close=close,
            )
        return get_bars(session, instrument.id, Timeframe.H1, after(len(closes)),
                        lookback=len(closes) + 10)

    def test_excursions_use_highs_and_lows_not_closes(
        self, session, instrument, provider
    ):
        """A move that touched and retraced still happened."""
        bars = self._bars(session, instrument, provider, [1.0, 1.0, 1.0])
        entry, forward = bars[0], bars[1:]
        # The fixture puts a +/-0.001 wick on every bar, so a flat close series
        # still has real excursions.

        up, down, fwd, _, _ = episodes.measure_outcome(entry, forward, Timeframe.H1)

        assert up > 0, "the wick above the flat close is a real excursion"
        assert down < 0
        assert fwd == pytest.approx(0.0, abs=1e-9)

    def test_up_and_down_are_both_recorded(self, session, instrument, provider):
        bars = self._bars(session, instrument, provider, [1.0, 1.1, 0.9, 1.0])

        up, down, fwd, to_up, to_down = episodes.measure_outcome(
            bars[0], bars[1:], Timeframe.H1
        )

        assert up == pytest.approx(0.101, abs=0.002)  # 1.1 + wick
        assert down == pytest.approx(-0.101, abs=0.002)  # 0.9 - wick
        assert to_up == 1
        assert to_down == 2

    def test_outcome_is_direction_agnostic(self, session, instrument, provider):
        """No MFE/MAE here: favourable is undefined without a decision."""
        seed(session, instrument, provider, 300)
        episodes.build(
            session, instrument.id, Timeframe.H1,
            start=after(100), end=after(150), horizon_bars=24, as_of=after(300),
        )
        row = session.scalars(select_all()).first()

        assert row.max_up_pct is not None
        assert row.max_down_pct is not None
        # Reserved for the phases that can actually fill them.
        assert row.decision is None
        assert row.strategy is None
        assert row.regime is None
        assert row.r_multiple is None


# ------------------------------------------------------------------ building
class TestBuilding:
    def test_rebuild_is_idempotent(self, session, instrument, provider):
        seed(session, instrument, provider, 300)
        window = dict(
            start=after(100), end=after(200), horizon_bars=24, as_of=after(300)
        )

        first = episodes.build(session, instrument.id, Timeframe.H1, **window)
        second = episodes.build(session, instrument.id, Timeframe.H1, **window)

        assert first.built > 0
        assert second.built == 0
        assert second.skipped_existing == first.built

    def test_step_thins_near_duplicate_episodes(self, session, instrument, provider):
        """Consecutive bars make near-identical episodes; similarity search
        would then find one moment counted many times."""
        seed(session, instrument, provider, 300)

        dense = episodes.build(
            session, instrument.id, Timeframe.H1,
            start=after(100), end=after(200), horizon_bars=24, as_of=after(300),
        )
        session.query(Episode).delete()
        sparse = episodes.build(
            session, instrument.id, Timeframe.H1,
            start=after(100), end=after(200), horizon_bars=24, as_of=after(300), step=6,
        )

        assert sparse.built < dense.built
        assert sparse.built >= dense.built // 8

    def test_invalid_arguments_are_refused(self, session, instrument, provider):
        seed(session, instrument, provider, 100)

        with pytest.raises(ValidationFailedError):
            episodes.build(
                session, instrument.id, Timeframe.H1,
                start=after(10), end=after(50), horizon_bars=0,
            )
        with pytest.raises(ValidationFailedError):
            episodes.build(
                session, instrument.id, Timeframe.H1,
                start=after(50), end=after(10), horizon_bars=24,
            )

    def test_no_bars_is_a_clear_error(self, session, instrument, provider):
        with pytest.raises(InsufficientDataError):
            episodes.build(
                session, instrument.id, Timeframe.H1,
                start=after(10), end=after(50), horizon_bars=24, as_of=after(100),
            )


# -------------------------------------------------------------- distribution
class TestDistribution:
    def test_small_sample_reports_insufficient(self):
        result = episodes.outcome_distribution([])

        assert result["sufficient"] is False
        assert "fewer than 20" in result["reason"]

    def test_distribution_summarises_a_real_sample(self, session, instrument, provider):
        seed(session, instrument, provider, 300)
        episodes.build(
            session, instrument.id, Timeframe.H1,
            start=after(100), end=after(250), horizon_bars=24, as_of=after(300),
        )
        rows = list(session.scalars(select_all()))

        result = episodes.outcome_distribution(rows)

        assert result["sufficient"] is True
        assert result["count"] == len(rows)
        # A monotonic rise: every forward window closed higher.
        assert result["positive_share"] == pytest.approx(1.0)

    def test_coverage_reports_what_exists(self, session, instrument, provider):
        seed(session, instrument, provider, 300)
        episodes.build(
            session, instrument.id, Timeframe.H1,
            start=after(100), end=after(200), horizon_bars=24, as_of=after(300),
        )

        stats = episodes.coverage(session, instrument.id, Timeframe.H1)

        assert stats["episodes"] > 0
        assert stats["matured"] == stats["episodes"]
