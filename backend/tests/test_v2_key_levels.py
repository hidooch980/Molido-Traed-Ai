"""Market Key Levels: NY close, daily H/L reactions, round numbers, RESEARCH stubs."""

from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo

from app.agents.v2.key_levels.calendar import last_completed_close, to_ny
from app.agents.v2.key_levels.engine import KeyLevelsEngine
from app.agents.v2.key_levels.rounds import RoundNumberParams, nearby_round_numbers
from app.agents.v2.key_levels.stubs import valid_break_even_stub, weekly_map_stub
from app.agents.v2.rules import key_level_counts
from tests.v2_bars import dst_spring_weekend, ny, three_weekdays_oct2026

NY = ZoneInfo("America/New_York")


class TestPrevNyClose:
    def test_midweek_morning_uses_yesterdays_1700(self):
        bars = three_weekdays_oct2026()
        as_of = ny(2026, 10, 21, 10, 30)  # Wed morning, day still open
        report = KeyLevelsEngine().run(bars, as_of=as_of)
        assert to_ny(report.prev_ny_close_at) == ny(2026, 10, 20, 17)
        assert report.prev_ny_close is not None
        assert report.completed.complete
        assert report.completed.high == 2020.0
        assert report.completed.low == 1995.0
        assert not report.developing.complete

    def test_just_after_cutover_the_day_that_just_ended_is_previous(self):
        bars = three_weekdays_oct2026()
        as_of = ny(2026, 10, 21, 17, 1)
        report = KeyLevelsEngine().run(bars, as_of=as_of)
        assert to_ny(report.prev_ny_close_at) == ny(2026, 10, 21, 17)
        assert report.completed.high == 2030.0
        assert report.completed.low == 2000.0

    def test_weekend_walks_back_to_friday_close(self):
        # Saturday afternoon: last completed close is Friday 17:00.
        as_of = ny(2026, 10, 24, 14)
        assert last_completed_close(as_of) == ny(2026, 10, 23, 17)

    def test_dst_spring_forward_keeps_friday_as_last_weekend_close(self):
        bars = dst_spring_weekend()
        # Sunday 16:00 EDT (after the clock change): last close is Friday 17:00 EST.
        as_of = ny(2026, 3, 8, 16)
        report = KeyLevelsEngine().run(bars, as_of=as_of)
        close_at = to_ny(report.prev_ny_close_at)
        assert close_at == ny(2026, 3, 6, 17)
        assert close_at.utcoffset() == timedelta(hours=-5)  # EST
        # Monday afternoon after the spring-forward: still Friday until Mon 17:00.
        mon = KeyLevelsEngine().run(bars, as_of=ny(2026, 3, 9, 12))
        assert to_ny(mon.prev_ny_close_at) == ny(2026, 3, 6, 17)


class TestDailyReactions:
    def test_sweep_breakout_and_reversal_of_the_prior_high(self):
        bars = three_weekdays_oct2026()
        # Tuesday's completed high is 2020. Wednesday 10:00 (closes 11:00) trades 2030.
        as_of = ny(2026, 10, 21, 12)
        report = KeyLevelsEngine().run(bars, as_of=as_of)
        assert report.completed.high == 2020.0
        kinds = {(r.kind, r.side) for r in report.reactions}
        assert ("breakout", "high") in kinds


class TestRoundNumbers:
    def test_levels_sit_on_the_tick_grid_and_split_major_minor(self):
        params = RoundNumberParams(tick_size=0.00001, major_step=0.01000, minor_step=0.00100)
        levels = nearby_round_numbers(1.10320, params)
        assert levels
        assert all(abs(round(lv.price / params.tick_size) * params.tick_size - lv.price) < 1e-12
                   for lv in levels)
        kinds = {lv.kind for lv in levels}
        assert kinds == {"major", "minor"}
        majors = [lv.price for lv in levels if lv.kind == "major"]
        assert 1.10 in majors or any(abs(p - 1.10) < 1e-12 for p in majors)


class TestStubs:
    def test_weekly_map_and_valid_be_are_research_and_empty(self):
        report = KeyLevelsEngine().run(three_weekdays_oct2026(), as_of=ny(2026, 10, 21, 10))
        assert report.weekly_map.available is False and report.weekly_map.value is None
        assert report.valid_break_even.available is False and report.valid_break_even.value is None
        assert report.weekly_map.status.value == "RESEARCH"
        assert report.valid_break_even.status.value == "RESEARCH"
        assert "pivot" not in weekly_map_stub().reason.lower() or "not" in weekly_map_stub().reason.lower()
        assert valid_break_even_stub().sources_checked
        counts = key_level_counts()
        assert counts["RESEARCH"] >= 2 and counts["VERIFIED"] == 0
