"""Independent tests for stage 4: BTB retest, microchannel, SP/CH/TR."""

from __future__ import annotations

from app.agents.pro_btb.engine import select_breakout_leg
from app.agents.pro_btb.geometry import classify_window, microchannel
from app.agents.pro_btb.params import ProBtbParams
from app.agents.pro_btb.stages.bo_candle import validate_bo_candle
from app.agents.pro_btb.stages.retest import assess_retest, build_btb_zone
from app.agents.pro_btb.stages.strong_leg import assess_strong_leg
from app.agents.pro_btb.types import CycleLabel, Direction, PriceRange
from tests.pro_btb_bars import bear_bars, bull_bars, chop_bars, ohlc


class TestRetest:
    def test_zone_is_a_price_range(self):
        bars = bull_bars()
        bo = validate_bo_candle(bars, select_breakout_leg(bars))
        zone = build_btb_zone(bars, bo)
        assert isinstance(zone, PriceRange)
        assert zone.low <= zone.high
        assert zone.rule_id == "BTB_ZONE_IS_PRICE_RANGE"

    def test_no_bo_means_no_zone(self):
        leg = assess_strong_leg(chop_bars())
        bo = validate_bo_candle(chop_bars(), leg)
        result = assess_retest(chop_bars(), bo)
        assert result.zone is None and not result.returned

    def test_bull_price_returns_after_leaving_the_zone(self):
        bars = bull_bars()
        bo = validate_bo_candle(bars, select_breakout_leg(bars))
        result = assess_retest(bars, bo)
        assert result.returned
        assert result.return_index is not None and bo.bo_index is not None
        assert result.return_index > bo.bo_index
        assert result.zone is not None
        hit = bars[result.return_index]
        assert result.zone.intersects(hit.low, hit.high)
        # At least one bar between BO and the return left the zone.
        assert any(
            not result.zone.intersects(bars[i].low, bars[i].high)
            for i in range(bo.bo_index + 1, result.return_index)
        )

    def test_bear_price_returns_to_the_range(self):
        bars = bear_bars()
        bo = validate_bo_candle(bars, select_breakout_leg(bars))
        result = assess_retest(bars, bo)
        assert result.returned and result.zone is not None
        assert result.zone.low <= result.zone.high

    def test_microchannel_detected_on_bull_retest(self):
        bars = bull_bars()
        result = assess_retest(bars, validate_bo_candle(bars, select_breakout_leg(bars)))
        assert result.microchannel is True

    def test_microchannel_helper_bull_and_bear(self):
        rising = ohlc([(10, 12, 8, 11), (11, 13, 9, 12), (12, 14, 10, 13)])
        falling = ohlc([(14, 16, 12, 13), (13, 15, 11, 12), (12, 14, 10, 11)])
        assert microchannel(rising, Direction.BULL, 3)
        assert not microchannel(rising, Direction.BEAR, 3)
        assert microchannel(falling, Direction.BEAR, 3)
        assert not microchannel(falling, Direction.BULL, 3)

    def test_sp_ch_tr_classifier_on_synthetic_windows(self):
        params = ProBtbParams()
        spike = ohlc([
            (2000, 2002, 1999, 2001),
            (2001, 2010, 2000, 2009),
            (2009, 2022, 2008, 2021),
        ])
        channel = ohlc([
            (2000, 2004, 1999, 2003),
            (2002, 2007, 2001, 2006),
            (2005, 2010, 2004, 2009),
            (2008, 2013, 2007, 2012),
            (2011, 2016, 2010, 2015),
        ])
        trading_range = ohlc([
            (2000, 2010, 1990, 2008),
            (2008, 2011, 1991, 1993),
            (1993, 2010, 1990, 2007),
            (2007, 2011, 1991, 1994),
            (1994, 2010, 1990, 2006),
        ])
        last_atr = 4.0
        assert classify_window(spike, params, last_atr) is CycleLabel.SPIKE
        assert classify_window(channel, params, last_atr) is CycleLabel.CHANNEL
        assert classify_window(trading_range, params, last_atr) is CycleLabel.TRADING_RANGE
        assert classify_window(spike[:1], params, last_atr) is CycleLabel.UNKNOWN
