"""Config redaction, log scrubbing, safe mode, and the CSV provider."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import Settings, _redact_dsn
from app.core.enums import Timeframe
from app.core.errors import ProviderError, SafeModeError
from app.core.logging import _scrub
from app.core.safe_mode import SafeMode, SafeModeReason
from app.providers.csv_provider import CsvProvider
from app.providers.registry import clear, get_provider, register, registered_codes
from app.seed.demo_data import demo_window, generate_csv


def test_dsn_credentials_are_redacted():
    dsn = "postgresql+psycopg://user:hunter2@db.internal:5432/molido"

    redacted = _redact_dsn(dsn)

    assert "hunter2" not in redacted
    assert "db.internal:5432/molido" in redacted


def test_safe_summary_never_exposes_credentials():
    settings = Settings(database_url="postgresql+psycopg://u:secret@host/db")

    summary = settings.safe_summary()

    assert "secret" not in str(summary)


def test_log_scrubbing_masks_sensitive_keys():
    scrubbed = _scrub(
        {"user": "ali", "password": "hunter2", "nested": {"api_key": "abc", "symbol": "EURUSD"}}
    )

    assert scrubbed["password"] == "***"
    assert scrubbed["nested"]["api_key"] == "***"
    assert scrubbed["nested"]["symbol"] == "EURUSD"


class TestSafeMode:
    def setup_method(self):
        SafeMode.reset_for_tests()

    def teardown_method(self):
        SafeMode.reset_for_tests()

    def test_blocks_risk_increase_when_engaged(self):
        SafeMode.engage(SafeModeReason.BROKER_UNCERTAINTY, "position mismatch")

        with pytest.raises(SafeModeError):
            SafeMode.assert_can_increase_risk()

    def test_lifts_only_when_every_reason_is_cleared(self):
        SafeMode.engage(SafeModeReason.BROKER_UNCERTAINTY)
        SafeMode.engage(SafeModeReason.CRITICAL_DATA_FAILURE)

        SafeMode.clear(SafeModeReason.BROKER_UNCERTAINTY)
        assert SafeMode.state().active is True

        SafeMode.clear(SafeModeReason.CRITICAL_DATA_FAILURE)
        assert SafeMode.state().active is False
        SafeMode.assert_can_increase_risk()  # no longer raises


def test_registry_round_trip():
    clear()
    provider = CsvProvider("data/providers/csv")
    register(provider)

    assert "csv" in registered_codes()
    assert get_provider("csv") is provider
    clear()


def test_csv_provider_reads_generated_demo_data(tmp_path):
    defects = generate_csv(tmp_path)
    start, end = demo_window()
    provider = CsvProvider(tmp_path)

    bars = provider.fetch_ohlcv("EURUSD", Timeframe.H1, start, end)
    symbols = provider.list_symbols()

    # ~30 calendar days of H1 minus weekends: the generator follows the FX
    # calendar, so a continuous 720 would mean it was emitting closed-market bars.
    assert 450 < len(bars) < 600
    assert symbols[0].raw_symbol == "EURUSD"
    assert symbols[0].quote_currency == "USD"
    # The generator reports what it corrupted; the file must actually miss them.
    times = {b.event_time for b in bars}
    for i in range(defects.missing_count):
        assert defects.missing_from + timedelta(hours=i) not in times


def test_csv_provider_respects_the_requested_window(tmp_path):
    generate_csv(tmp_path)
    start, _ = demo_window()
    provider = CsvProvider(tmp_path)

    bars = provider.fetch_ohlcv(
        "EURUSD", Timeframe.H1, start + timedelta(hours=10), start + timedelta(hours=20)
    )

    assert len(bars) == 10
    assert all(start + timedelta(hours=10) <= b.event_time < start + timedelta(hours=20)
               for b in bars)


def test_csv_provider_reports_missing_data_clearly(tmp_path):
    provider = CsvProvider(tmp_path)

    with pytest.raises(ProviderError):
        provider.fetch_ohlcv("NOPE", Timeframe.H1, datetime.now(UTC) - timedelta(days=1),
                             datetime.now(UTC))
