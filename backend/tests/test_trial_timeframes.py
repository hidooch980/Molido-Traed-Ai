"""Trial periods must reach collection and retain their native durations."""
from datetime import timedelta
from pathlib import Path

from app.core.config import get_settings
from app.core.enums import Timeframe
from app.models.journal import SOURCE_BROKER
from app.providers.yfinance_provider import YFinanceProvider
from app.workers import collector

PERIODS = (Timeframe.M1, Timeframe.M5, Timeframe.M10, Timeframe.M15, Timeframe.M30)


def test_ten_minute_duration_is_not_fifteen_minutes():
    assert Timeframe("M10").delta == timedelta(minutes=10)


def test_trial_broker_periods_are_explicit_and_deduplicated(monkeypatch):
    monkeypatch.setattr(get_settings(), "broker_timeframes", "M1,M5,M10,M15,M30,M10,typo")
    assert collector._broker_timeframes() == (Timeframe.H1, *PERIODS)


def test_default_keeps_existing_broker_workload(monkeypatch):
    monkeypatch.setattr(get_settings(), "broker_timeframes", "H1,M15,M5")
    assert collector._broker_timeframes() == (Timeframe.H1, Timeframe.M15, Timeframe.M5)


def test_empty_broker_periods_keep_hourly_clock_reference(monkeypatch):
    monkeypatch.setattr(get_settings(), "broker_timeframes", "")
    assert collector._broker_timeframes() == (Timeframe.H1,)


def test_all_five_trial_periods_can_be_recorded(monkeypatch):
    monkeypatch.setattr(get_settings(), "forward_timeframes", "M1,M5,M10,M15,M30")
    assert collector._forward_timeframes() == (Timeframe.H1, *PERIODS)


def test_ten_minute_forward_record_never_uses_yahoo():
    assert collector._sources_for(Timeframe.M10) == (SOURCE_BROKER,)


def test_yahoo_does_not_advertise_fabricated_ten_minute_bars():
    assert Timeframe.M10 not in YFinanceProvider().capabilities().supported_timeframes


def test_trial_export_is_opt_in_and_exports_native_periods():
    # The MQL compiler is not available here; this contract check complements
    # the required MetaEditor compile and live terminal smoke test.
    source = (Path(__file__).parents[2] / "infra/mql5/MolidoBridge.mq5").read_text()
    assert "input bool PublishTrialTimeframes = false;" in source
    block = source.split("if(PublishTrialTimeframes)", 1)[1].split("cursor =", 1)[0]
    for name in ("M1", "M10", "M30"):
        assert f"WriteBars(name, PERIOD_{name});" in block
    assert 'case PERIOD_M10: return "M10";' in source
