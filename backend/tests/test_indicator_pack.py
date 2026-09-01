"""The classic-indicator pack: state descriptors, not signals."""

import uuid
from datetime import UTC, datetime, timedelta

from app.core.enums import Timeframe
from app.features import all_specs
from app.services.point_in_time import BarView

START = datetime(2026, 1, 1, tzinfo=UTC)


def bars(count, *, drift=0.1, base=100.0):
    return [
        BarView(
            instrument_id=uuid.uuid4(),
            provider_id=uuid.uuid4(),
            timeframe=Timeframe.H1,
            event_time=START + timedelta(hours=i),
            open=base + i * drift,
            high=base + i * drift + 1.0,
            low=base + i * drift - 1.0,
            close=base + i * drift + 0.5,
            volume=1000.0,
            tick_volume=None,
            spread=None,
            revision=1,
            ingested_at=START,
            quality_score=1.0,
        )
        for i in range(count)
    ]


SPECS = {s.name: s for s in all_specs()}


class TestTheClassicPack:
    def test_every_new_indicator_computes_on_a_plain_series(self):
        window = bars(260)
        for name in (
            "macd_hist_12_26_9", "bollinger_position_20", "bollinger_width_20",
            "stochastic_k_14", "adx_14", "sma_50", "sma_200",
            "sma_50_over_200", "roc_20", "donchian_position_55",
        ):
            value = SPECS[name].compute(window)
            assert value is not None, name

    def test_bounded_indicators_stay_in_their_bounds(self):
        window = bars(260)
        for name, low, high in (
            ("stochastic_k_14", 0.0, 100.0),
            ("adx_14", 0.0, 100.0),
            ("donchian_position_55", 0.0, 1.0),
        ):
            value = SPECS[name].compute(window)
            assert low <= value <= high, (name, value)

    def test_a_rising_series_reads_as_risen(self):
        window = bars(260)
        assert SPECS["sma_50_over_200"].compute(window) > 1
        assert SPECS["roc_20"].compute(window) > 0
        assert SPECS["donchian_position_55"].compute(window) > 0.8

    def test_a_flat_series_does_not_divide_by_zero(self):
        window = bars(260, drift=0.0)
        assert SPECS["bollinger_position_20"].compute(window) == 0.5
        assert SPECS["donchian_position_55"].compute(window) is not None
