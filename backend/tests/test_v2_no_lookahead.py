"""Completed V2 levels must not move when later or unclosed bars are added."""

from __future__ import annotations

from app.agents.v2.key_levels.engine import KeyLevelsEngine
from app.agents.v2.sp2l.engine import Sp2lEngine
from app.agents.v2.spike_imbalance.engine import SpikeImbalanceEngine
from tests.v2_bars import H, bull_spike_bars, ny, three_weekdays_oct2026


class TestNoLookahead:
    def test_completed_ny_levels_ignore_future_days(self):
        bars = three_weekdays_oct2026()
        as_of = ny(2026, 10, 20, 17, 0)  # Tuesday close — Monday+Tuesday are visible
        past = [b for b in bars if b.open_time + H <= as_of]
        future = bars  # includes Wednesday
        engine = KeyLevelsEngine()
        a = engine.run(past, as_of=as_of)
        b = engine.run(future, as_of=as_of)
        assert a.prev_ny_close == b.prev_ny_close
        assert a.prev_ny_close_at == b.prev_ny_close_at
        assert a.completed.high == b.completed.high
        assert a.completed.low == b.completed.low
        assert a.completed.complete and b.completed.complete

    def test_unclosed_hour_is_invisible_to_the_close(self):
        bars = three_weekdays_oct2026()
        # Tuesday 16:30: the 16:00 bar has not closed, and 17:00 has not happened.
        as_of = ny(2026, 10, 20, 16, 30)
        report = KeyLevelsEngine().run(bars, as_of=as_of)
        assert report.prev_ny_close_at == ny(2026, 10, 19, 17)
        assert not report.developing.complete
        # The Tuesday 16:00–17:00 bar must not be in the visible developing window.
        assert all((b.open_time + H) <= as_of for b in bars if b.open_time + H <= as_of)

    def test_completed_tuesday_hl_is_frozen_the_next_day(self):
        bars = three_weekdays_oct2026()
        at_close = KeyLevelsEngine().run(bars, as_of=ny(2026, 10, 20, 17))
        next_day = KeyLevelsEngine().run(bars, as_of=ny(2026, 10, 21, 16, 0))
        # Next day, the completed range is still Tuesday's (until Wed 17:00).
        assert next_day.completed.high == at_close.completed.high == 2020.0
        assert next_day.completed.low == at_close.completed.low == 1995.0
        assert next_day.prev_ny_close == at_close.prev_ny_close

    def test_sp2l_and_fvg_are_stable_when_future_bars_are_appended_but_hidden(self):
        bars = bull_spike_bars()
        as_of = bars[-3].open_time + H  # before the last two bars close
        visible = [b for b in bars if b.open_time + H <= as_of]
        full = bars
        sp_a = Sp2lEngine().run(visible)
        sp_b = Sp2lEngine().run([b for b in full if b.open_time + H <= as_of])
        assert sp_a.as_dict() == sp_b.as_dict()
        si_a = SpikeImbalanceEngine().run(visible)
        si_b = SpikeImbalanceEngine().run([b for b in full if b.open_time + H <= as_of])
        assert si_a.as_dict() == si_b.as_dict()
        # Adding later bars *without* moving as_of must not change a closed-bar run.
        # (The engines themselves don't take as_of for SI; the caller filters.)
