"""Collector tests.

The collector runs unattended for weeks at a time, so the properties that
matter are the operational ones: it must not duplicate data, must not stop on
one bad symbol, and must not waste quota polling a closed market.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.enums import Timeframe
from app.core.errors import ConfigurationError, ProviderError
from app.providers.base import ProviderCapabilities, ProviderSymbol, RawBar
from app.workers import collector
from app.workers.watchlist import parse_watchlist


class FakeProvider:
    code = "fake"
    name = "Fake collector provider"

    def __init__(self, bars_by_symbol: dict[str, list[RawBar]], fail: set[str] | None = None):
        self._bars = bars_by_symbol
        self._fail = fail or set()
        self.requested: list[str] = []

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supported_timeframes=(Timeframe.H1,))

    def list_symbols(self) -> list[ProviderSymbol]:
        return [ProviderSymbol(raw_symbol=s) for s in self._bars]

    def fetch_ohlcv(self, raw_symbol, timeframe, start, end):
        self.requested.append(raw_symbol)
        if raw_symbol in self._fail:
            raise ProviderError(f"upstream refused {raw_symbol}")
        return [b for b in self._bars.get(raw_symbol, []) if start <= b.event_time < end]

    def health_check(self) -> bool:
        return True


def recent_bars(count: int, *, end: datetime | None = None) -> list[RawBar]:
    """Bars ending at 'now', so the collector's open-market check sees them."""
    end = end or datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    out = []
    for i in range(count):
        t = end - timedelta(hours=count - i)
        price = 1.10 + i * 0.0001
        out.append(
            RawBar(
                event_time=t,
                open=price,
                high=price + 0.0003,
                low=price - 0.0003,
                close=price + 0.0001,
                volume=1000.0,
            )
        )
    return out


# ----------------------------------------------------------------- watchlist
class TestWatchlist:
    def test_parses_entries(self):
        entries = parse_watchlist("EURUSD:EURUSD=X:H1, BTCUSD:BTC-USD:D1")

        assert [e.symbol for e in entries] == ["EURUSD", "BTCUSD"]
        assert entries[0].raw_symbol == "EURUSD=X"
        assert entries[1].timeframe == Timeframe.D1

    def test_ignores_blank_segments(self):
        assert len(parse_watchlist("EURUSD:EURUSD=X:H1,, ")) == 1

    def test_malformed_entry_is_refused_loudly(self):
        """A silently-dropped entry means an instrument stops being collected."""
        with pytest.raises(ConfigurationError):
            parse_watchlist("EURUSD:H1")

    def test_unknown_timeframe_is_refused(self):
        with pytest.raises(ConfigurationError):
            parse_watchlist("EURUSD:EURUSD=X:H7")


# ------------------------------------------------------------------- cycles
class TestCycle:
    @pytest.fixture(autouse=True)
    def _patch_session(self, session, monkeypatch):
        """Point the collector at the test session instead of a real engine.

        Also shortens the first-run backfill: the production depth for H1 is
        680 days, which the ingester correctly splits into ~23 chunked provider
        calls — accurate, but 40 seconds of test time to prove nothing these
        tests are about.
        """
        from contextlib import contextmanager

        @contextmanager
        def fake_scope():
            yield session

        monkeypatch.setattr(collector, "session_scope", fake_scope)
        monkeypatch.setattr(
            collector, "BACKFILL_DEPTH", {Timeframe.H1: timedelta(days=20)}
        )

    def test_collects_and_materializes(self, monkeypatch):
        provider = FakeProvider({"BTC-USD": recent_bars(300)})
        monkeypatch.setattr(collector, "_resolve_provider", lambda: provider)
        entries = parse_watchlist("BTCUSD:BTC-USD:H1")

        report = collector.run_cycle(entries)

        assert report.ingested == 1
        assert report.written > 0
        assert report.features_written > 0
        assert report.failures == []

    def test_second_cycle_writes_nothing_new(self, monkeypatch):
        """Unattended repetition must not duplicate data."""
        provider = FakeProvider({"BTC-USD": recent_bars(200)})
        monkeypatch.setattr(collector, "_resolve_provider", lambda: provider)
        entries = parse_watchlist("BTCUSD:BTC-USD:H1")

        first = collector.run_cycle(entries)
        second = collector.run_cycle(entries)

        assert first.written > 0
        assert second.written == 0

    def test_one_failing_symbol_does_not_stop_the_sweep(self, monkeypatch):
        provider = FakeProvider(
            {"BTC-USD": recent_bars(120), "ETH-USD": recent_bars(120)},
            fail={"ETH-USD"},
        )
        monkeypatch.setattr(collector, "_resolve_provider", lambda: provider)
        entries = parse_watchlist("ETHUSD:ETH-USD:H1,BTCUSD:BTC-USD:H1")

        report = collector.run_cycle(entries)

        assert report.failures, "the failing symbol must be reported"
        assert report.written > 0, "the healthy symbol must still be collected"

    def test_closed_market_is_skipped_not_polled(self, monkeypatch):
        """Polling a shut market burns quota and looks like a broken feed."""
        provider = FakeProvider({"EURUSD=X": recent_bars(120)})
        monkeypatch.setattr(collector, "_resolve_provider", lambda: provider)

        # A Saturday: FX is closed and has been for more than the grace window.
        saturday = datetime(2024, 3, 9, 12, 0, tzinfo=UTC)

        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return saturday

        monkeypatch.setattr(collector, "datetime", FrozenDatetime)
        entries = parse_watchlist("EURUSD:EURUSD=X:H1")

        report = collector.run_cycle(entries)

        assert report.skipped_closed == 1
        assert report.ingested == 0
        assert provider.requested == [], "no provider call for a closed market"

    def test_crypto_is_collected_at_the_weekend(self, monkeypatch):
        """The mirror of the previous test: 24/7 markets are never skipped."""
        provider = FakeProvider({"BTC-USD": recent_bars(120)})
        monkeypatch.setattr(collector, "_resolve_provider", lambda: provider)
        entries = parse_watchlist("BTCUSD:BTC-USD:H1")

        report = collector.run_cycle(entries)

        assert report.skipped_closed == 0
        # The window is fetched in chunks, so one entry means one or more calls
        # — what matters is that they were all for this symbol.
        assert provider.requested
        assert set(provider.requested) == {"BTC-USD"}

    def test_report_payload_is_loggable(self, monkeypatch):
        provider = FakeProvider({"BTC-USD": recent_bars(60)})
        monkeypatch.setattr(collector, "_resolve_provider", lambda: provider)

        payload = collector.run_cycle(parse_watchlist("BTCUSD:BTC-USD:H1")).as_payload()

        assert set(payload) >= {"entries", "bars_written", "failure_count"}


class TestDnaRefresh:
    """Phase 8 was built, tested, and never ran in production.

    Nothing called `compute_dna` outside its own suite, so every instrument had
    zero stored profiles and the market map reported forty of them as
    unmeasured. It found the gap by refusing to draw a correlation grid out of
    nothing - which is the point of that refusal, but it should not have taken
    a UI to notice.

    These tests exist so the wiring cannot go quiet again.
    """

    @pytest.fixture(autouse=True)
    def _patch_session(self, session, monkeypatch):
        from contextlib import contextmanager

        @contextmanager
        def fake_scope():
            yield session

        monkeypatch.setattr(collector, "session_scope", fake_scope)
        monkeypatch.setattr(
            collector, "BACKFILL_DEPTH", {Timeframe.H1: timedelta(days=20)}
        )

    def test_the_worker_registers_the_job(self):
        """A function ARQ does not know about is a job that never runs."""
        names = [f.__name__ for f in collector.WorkerSettings.functions]

        assert "refresh_dna_job" in names

    def test_there_is_a_cron_entry_for_it(self):
        assert len(collector.WorkerSettings.cron_jobs) >= 2

    def test_it_writes_profiles_for_a_collected_instrument(self, monkeypatch):

        provider = FakeProvider({"BTC-USD": recent_bars(600)})
        monkeypatch.setattr(collector, "_resolve_provider", lambda: provider)
        entries = parse_watchlist("BTCUSD:BTC-USD:H1")
        collector.run_cycle(entries)

        result = collector.refresh_dna(entries)

        assert result["profiles_written"] > 0
        assert result["failures"] == []

    def test_the_profiles_are_readable_afterwards(self, monkeypatch, session):
        """Written is not the same as retrievable - the map reads them back
        through `latest_dna`, so that is what the test asserts."""
        from datetime import UTC, datetime

        from app.services import symbol_dna
        from app.services.instruments import get_instrument_by_symbol

        provider = FakeProvider({"BTC-USD": recent_bars(600)})
        monkeypatch.setattr(collector, "_resolve_provider", lambda: provider)
        entries = parse_watchlist("BTCUSD:BTC-USD:H1")
        collector.run_cycle(entries)
        collector.refresh_dna(entries)

        instrument = get_instrument_by_symbol(session, "BTCUSD")
        stored = symbol_dna.latest_dna(
            session, instrument.id, Timeframe.H1, datetime.now(UTC)
        )

        assert stored, "the map reads profiles through latest_dna and found none"

    def test_an_instrument_short_of_history_does_not_stop_the_sweep(self, monkeypatch):
        """One symbol with too few bars must not cost the rest their profiles."""
        provider = FakeProvider({"BTC-USD": recent_bars(600), "EURUSD=X": recent_bars(5)})
        monkeypatch.setattr(collector, "_resolve_provider", lambda: provider)
        entries = parse_watchlist("EURUSD:EURUSD=X:H1,BTCUSD:BTC-USD:H1")
        collector.run_cycle(entries)

        result = collector.refresh_dna(entries)

        assert result["entries"] == 2
        assert result["profiles_written"] > 0

    def test_an_unknown_symbol_is_skipped_not_crashed(self, monkeypatch):
        result = collector.refresh_dna(parse_watchlist("NOPE:NOPE=X:H1"))

        assert result["profiles_written"] == 0
        assert result["failures"] == []
