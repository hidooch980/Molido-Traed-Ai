"""Feature store tests (phase 7).

The load-bearing property: a feature computed live and the same feature
recomputed later must be identical, and neither may see a bar that had not
closed or was not yet known. If these fail, every model trained on this data
is learning from the future.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from app.core.enums import Timeframe
from app.core.errors import InsufficientDataError, ValidationFailedError
from app.features import base as registry
from app.features.base import FeatureSpec
from app.services import feature_store
from app.services.point_in_time import BarView
from tests.conftest import BASE_TIME, insert_bar


def seed(session, instrument, provider, count=120, ingested_at=None, price=1.1000):
    ingested_at = ingested_at or BASE_TIME
    for i in range(count):
        insert_bar(
            session,
            instrument.id,
            provider.id,
            event_time=BASE_TIME + timedelta(hours=i),
            ingested_at=ingested_at,
            close=price + i * 0.0002,
        )


def now() -> datetime:
    """Fresh each call.

    A module-level constant would be captured at import time, i.e. *before*
    the features under test are computed - and `read_materialized` would
    correctly hide them, which looks like a bug in the store rather than in
    the test.
    """
    return datetime.now(UTC)


# ------------------------------------------------------------------ registry
class TestRegistry:
    def test_builtins_are_registered(self):
        names = registry.names()

        assert "rsi_14" in names
        assert "atr_14" in names
        assert "sma_20" in names

    def test_every_spec_declares_a_version_and_lookback(self):
        for spec in registry.all_specs():
            assert spec.version >= 1
            assert spec.lookback >= 0
            assert spec.description, f"{spec.name} has no description"

    def test_unknown_feature_is_a_clear_error(self):
        from app.core.errors import ConfigurationError

        with pytest.raises(ConfigurationError):
            registry.get("does_not_exist")

    def test_registering_the_same_version_twice_is_refused(self):
        """Changing the maths without bumping the version is the bug this catches."""
        from app.core.errors import ConfigurationError

        spec = FeatureSpec(name="dupe_test", version=1, lookback=0, fn=lambda bars: 1.0)
        registry.register(spec)
        try:
            with pytest.raises(ConfigurationError):
                registry.register(spec)
        finally:
            registry._REGISTRY.pop("dupe_test", None)

    def test_spec_refuses_a_short_window(self):
        spec = registry.get("sma_20")
        bars = [_bar(i) for i in range(5)]

        with pytest.raises(InsufficientDataError):
            spec.compute(bars)


def _bar(i: int, close: float = 1.1) -> BarView:
    import uuid

    return BarView(
        instrument_id=uuid.uuid4(),
        provider_id=uuid.uuid4(),
        timeframe=Timeframe.H1,
        event_time=BASE_TIME + timedelta(hours=i),
        open=close,
        high=close + 0.001,
        low=close - 0.001,
        close=close,
        volume=1000.0,
        tick_volume=None,
        spread=None,
        revision=1,
        ingested_at=BASE_TIME,
        quality_score=1.0,
    )


# ---------------------------------------------------------------- indicators
class TestIndicatorMaths:
    def test_sma_is_the_mean_of_the_window(self):
        bars = [_bar(i, close=float(i)) for i in range(20)]

        assert registry.get("sma_20").compute(bars) == pytest.approx(9.5)

    def test_rsi_is_100_for_an_unbroken_rally(self):
        bars = [_bar(i, close=1.0 + i * 0.01) for i in range(15)]

        assert registry.get("rsi_14").compute(bars) == pytest.approx(100.0)

    def test_rsi_is_neutral_for_a_flat_market(self):
        """A flat window has no gains and no losses — 50, not a divide by zero."""
        bars = [_bar(i, close=1.0) for i in range(15)]

        assert registry.get("rsi_14").compute(bars) == pytest.approx(50.0)

    def test_position_in_range_is_bounded(self):
        bars = [_bar(i, close=1.0 + i * 0.01) for i in range(20)]

        value = registry.get("position_in_range_20").compute(bars)

        assert 0.0 <= value <= 1.0

    def test_position_in_range_is_none_for_a_flat_window(self):
        """A window with no range has no position in it — None, not 0.5."""
        bars = [_bar(i, close=1.0) for i in range(20)]
        for bar in bars:
            object.__setattr__(bar, "high", 1.0)
            object.__setattr__(bar, "low", 1.0)

        assert registry.get("position_in_range_20").compute(bars) is None

    def test_log_return_matches_the_definition(self):
        bars = [_bar(0, close=1.0), _bar(1, close=1.1)]

        assert registry.get("return_1").compute(bars) == pytest.approx(math.log(1.1))

    def test_atr_pct_is_scale_free(self):
        """The same shape at a different price level gives the same ATR%."""
        cheap = [_bar(i, close=1.0) for i in range(15)]
        rich = [_bar(i, close=100.0) for i in range(15)]
        for bar in cheap:
            object.__setattr__(bar, "high", 1.01)
            object.__setattr__(bar, "low", 0.99)
        for bar in rich:
            object.__setattr__(bar, "high", 101.0)
            object.__setattr__(bar, "low", 99.0)

        spec = registry.get("atr_14_pct")
        assert spec.compute(cheap) == pytest.approx(spec.compute(rich), rel=1e-9)


# ------------------------------------------------------- point-in-time rules
class TestPointInTime:
    def test_compute_uses_only_closed_and_known_bars(self, session, instrument, provider):
        seed(session, instrument, provider, count=60)
        as_of = BASE_TIME + timedelta(hours=30)

        row = feature_store.compute_at(
            session, instrument.id, Timeframe.H1, as_of, feature_names=["sma_20"]
        )

        # The bar opening at 29:00 closes at 30:00 -> it is the newest visible.
        assert row.event_time == BASE_TIME + timedelta(hours=29)

    def test_a_later_recompute_gives_the_same_number(self, session, instrument, provider):
        """Reproducibility: the defining property of a feature store."""
        seed(session, instrument, provider, count=80)
        as_of = BASE_TIME + timedelta(hours=40)
        names = ["sma_20", "rsi_14", "atr_14", "ema_20"]

        live = feature_store.compute_at(
            session, instrument.id, Timeframe.H1, as_of, feature_names=names
        )
        # Simulate "much later": more history now exists, but as_of is unchanged.
        replay = feature_store.compute_at(
            session, instrument.id, Timeframe.H1, as_of, feature_names=names
        )

        assert live.values == replay.values

    def test_future_bars_cannot_influence_a_past_feature(
        self, session, instrument, provider
    ):
        """Add wildly different future bars; the past value must not move."""
        seed(session, instrument, provider, count=40)
        as_of = BASE_TIME + timedelta(hours=30)
        before = feature_store.compute_at(
            session, instrument.id, Timeframe.H1, as_of, feature_names=["sma_20"]
        )

        for i in range(40, 80):
            insert_bar(
                session,
                instrument.id,
                provider.id,
                event_time=BASE_TIME + timedelta(hours=i),
                ingested_at=BASE_TIME,
                close=99.0,  # absurd, to make any leak obvious
            )

        after = feature_store.compute_at(
            session, instrument.id, Timeframe.H1, as_of, feature_names=["sma_20"]
        )

        assert before.values["sma_20"] == after.values["sma_20"]

    def test_insufficient_history_raises_rather_than_warming_up_silently(
        self, session, instrument, provider
    ):
        seed(session, instrument, provider, count=5)

        with pytest.raises(InsufficientDataError):
            feature_store.compute_at(
                session,
                instrument.id,
                Timeframe.H1,
                BASE_TIME + timedelta(hours=5),
                feature_names=["sma_20"],
            )

    def test_one_short_feature_does_not_void_the_row(self, session, instrument, provider):
        """A long-lookback feature reports None; the short ones still compute."""
        seed(session, instrument, provider, count=30)

        row = feature_store.compute_at(
            session,
            instrument.id,
            Timeframe.H1,
            BASE_TIME + timedelta(hours=25),
            feature_names=["bar_range_pct", "ema_20"],
        )

        assert row.values["bar_range_pct"] is not None
        assert row.values["ema_20"] is None

    def test_naive_as_of_is_refused(self, session, instrument, provider):
        with pytest.raises(ValidationFailedError):
            feature_store.compute_at(
                session, instrument.id, Timeframe.H1, datetime(2024, 3, 4, 12, 0)
            )


# -------------------------------------------------------------- materialize
class TestMaterialize:
    def test_writes_values_for_each_bar(self, session, instrument, provider):
        seed(session, instrument, provider, count=80)

        result = feature_store.materialize(
            session,
            instrument.id,
            Timeframe.H1,
            start=BASE_TIME + timedelta(hours=40),
            end=BASE_TIME + timedelta(hours=60),
            feature_names=["sma_20", "rsi_14"],
        )

        assert result.bars_processed == 20
        assert result.values_written == 40  # 20 bars x 2 features

    def test_is_idempotent(self, session, instrument, provider):
        seed(session, instrument, provider, count=80)
        window = {
            "start": BASE_TIME + timedelta(hours=40),
            "end": BASE_TIME + timedelta(hours=60),
            "feature_names": ["sma_20"],
        }

        first = feature_store.materialize(session, instrument.id, Timeframe.H1, **window)
        second = feature_store.materialize(session, instrument.id, Timeframe.H1, **window)

        assert first.values_written == 20
        assert second.values_written == 0
        assert second.values_skipped == 20

    def test_materialized_matches_live_computation(self, session, instrument, provider):
        """The stored value and the on-demand value must not drift apart."""
        seed(session, instrument, provider, count=80)
        target = BASE_TIME + timedelta(hours=59)

        feature_store.materialize(
            session,
            instrument.id,
            Timeframe.H1,
            start=BASE_TIME + timedelta(hours=40),
            end=BASE_TIME + timedelta(hours=60),
            feature_names=["sma_20", "rsi_14", "atr_14"],
        )
        stored = feature_store.read_materialized(
            session, instrument.id, Timeframe.H1, now(), lookback=1
        )
        live = feature_store.compute_at(
            session,
            instrument.id,
            Timeframe.H1,
            target + Timeframe.H1.delta,
            feature_names=["sma_20", "rsi_14", "atr_14"],
        )

        assert stored[-1].event_time == live.event_time
        for name, value in live.values.items():
            assert stored[-1].values[name] == pytest.approx(value, rel=1e-9)

    def test_warmup_history_is_used_for_the_first_bar(self, session, instrument, provider):
        """The first materialized bar must be as well-informed as the last."""
        seed(session, instrument, provider, count=120)
        start = BASE_TIME + timedelta(hours=60)

        feature_store.materialize(
            session,
            instrument.id,
            Timeframe.H1,
            start=start,
            end=start + timedelta(hours=10),
            feature_names=["sma_20"],
        )
        rows = feature_store.read_materialized(
            session, instrument.id, Timeframe.H1, now(), feature_names=["sma_20"]
        )

        assert rows[0].event_time == start
        assert rows[0].values["sma_20"] is not None

    def test_read_respects_computed_at(self, session, instrument, provider):
        """A feature computed after as_of is invisible, like a late bar."""
        seed(session, instrument, provider, count=80)
        feature_store.materialize(
            session,
            instrument.id,
            Timeframe.H1,
            start=BASE_TIME + timedelta(hours=40),
            end=BASE_TIME + timedelta(hours=60),
            feature_names=["sma_20"],
        )

        # computed_at is "now"; an as_of in 2024 predates it.
        rows = feature_store.read_materialized(
            session, instrument.id, Timeframe.H1, BASE_TIME + timedelta(hours=70)
        )

        assert rows == []

    def test_coverage_reports_what_exists(self, session, instrument, provider):
        seed(session, instrument, provider, count=80)
        feature_store.materialize(
            session,
            instrument.id,
            Timeframe.H1,
            start=BASE_TIME + timedelta(hours=40),
            end=BASE_TIME + timedelta(hours=60),
            feature_names=["sma_20", "rsi_14"],
        )

        stats = feature_store.coverage(session, instrument.id, Timeframe.H1)

        assert stats.values == 40
        assert stats.features == 2

    def test_as_of_selects_the_data_vintage(self, session, instrument, provider):
        """`as_of` chooses which revision vintage to build from, not the range.

        A backfill asked to use pre-revision knowledge must produce the
        pre-revision number, even though a newer bar exists today.
        """
        seed(session, instrument, provider, count=60)
        revised_at = BASE_TIME + timedelta(days=30)
        # A correction to one bar inside the window, learned much later.
        insert_bar(
            session,
            instrument.id,
            provider.id,
            event_time=BASE_TIME + timedelta(hours=45),
            ingested_at=revised_at,
            close=50.0,
            revision=2,
        )
        window = {
            "start": BASE_TIME + timedelta(hours=50),
            "end": BASE_TIME + timedelta(hours=52),
            "feature_names": ["sma_20"],
        }

        feature_store.materialize(
            session,
            instrument.id,
            Timeframe.H1,
            as_of=BASE_TIME + timedelta(hours=55),  # before the revision landed
            **window,
        )
        original = feature_store.read_materialized(
            session, instrument.id, Timeframe.H1, now(), feature_names=["sma_20"]
        )[0].values["sma_20"]

        feature_store.materialize(
            session,
            instrument.id,
            Timeframe.H1,
            as_of=revised_at + timedelta(hours=1),  # after it landed
            recompute=True,
            **window,
        )
        revised = feature_store.read_materialized(
            session, instrument.id, Timeframe.H1, now(), feature_names=["sma_20"]
        )[0].values["sma_20"]

        assert original != revised
        assert revised > original, "the 50.0 correction lifts the average"

    def test_empty_range_is_an_explicit_error(self, session, instrument, provider):
        with pytest.raises(InsufficientDataError):
            feature_store.materialize(
                session,
                instrument.id,
                Timeframe.H1,
                start=BASE_TIME,
                end=BASE_TIME + timedelta(hours=10),
                feature_names=["sma_20"],
            )

    def test_reversed_window_is_refused(self, session, instrument, provider):
        seed(session, instrument, provider, count=30)

        with pytest.raises(ValidationFailedError):
            feature_store.materialize(
                session,
                instrument.id,
                Timeframe.H1,
                start=BASE_TIME + timedelta(hours=20),
                end=BASE_TIME,
                feature_names=["sma_20"],
            )
