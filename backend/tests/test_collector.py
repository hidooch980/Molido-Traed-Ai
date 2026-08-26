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

    def test_empty_watchlist_is_refused(self):
        """An empty universe is a misconfiguration, not a valid choice.

        The compose file passes `${MOLIDO_WATCHLIST}`, so an unset variable
        arrives as an empty string rather than as an absent setting - which
        means the built-in default never applies. Returning no entries would
        start a collector that sweeps nothing and reports no failures.
        """
        with pytest.raises(ConfigurationError):
            parse_watchlist("")
        with pytest.raises(ConfigurationError):
            parse_watchlist("  , ,, ")

    def test_default_universe_can_form_a_cross_section(self):
        """The default must be able to learn, not merely to collect.

        The cross-section refuses to rank fewer than `MIN_CROSS_SECTION`
        instruments sharing one timestamp. A default below that floor produces
        a deployment that gathers bars perfectly and writes nothing to the
        journal, forever, with every visible signal reporting health - which is
        exactly what this deployment did with a four-symbol default.
        """
        from app.brain.crosssection import MIN_CROSS_SECTION
        from app.workers.watchlist import DEFAULT_WATCHLIST

        entries = parse_watchlist(DEFAULT_WATCHLIST)
        assert len(entries) >= MIN_CROSS_SECTION

        # Per timeframe, because the ranking happens within one. A universe of
        # forty split twenty-one ways clears the floor in aggregate and fails
        # it everywhere that matters.
        counts: dict[str, int] = {}
        for entry in entries:
            counts[entry.timeframe.value] = counts.get(entry.timeframe.value, 0) + 1
        assert max(counts.values()) >= MIN_CROSS_SECTION

        # And the floor must be carried by instruments that share a session.
        # Twenty names that are never open together cannot be ranked together,
        # so a universe padded to the floor with mismatched calendars passes a
        # count and still never produces a cross-section.
        currencies = [e for e in entries if e.raw_symbol.endswith("=X")]
        assert len(currencies) >= MIN_CROSS_SECTION

    def test_symbols_are_unique(self):
        """One canonical name, one provider symbol.

        The same instrument listed twice would be ranked against itself.
        """
        from app.workers.watchlist import DEFAULT_WATCHLIST

        entries = parse_watchlist(DEFAULT_WATCHLIST)
        keys = [e.key for e in entries]
        assert len(keys) == len(set(keys))


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

class TestEpisodeBuilding:
    """Phase 10 was built, covered by leakage tests, and never ran.

    The server held 597,760 bars and zero episodes. Nothing failed, because
    nothing asked: the builder had no caller outside its own suite. That is the
    second time this exact shape has turned up - symbol DNA was the first - and
    both were found by looking at the database rather than at the test results.

    Episodes are what the similarity and memory layers read, so an empty table
    does not break anything visibly. It makes a whole layer answer honestly and
    uselessly for every question it is asked, which is far quieter than a crash
    and lasts much longer.
    """

    @pytest.fixture(autouse=True)
    def _patch_session(self, session, monkeypatch):
        from contextlib import contextmanager

        @contextmanager
        def fake_scope():
            yield session

        monkeypatch.setattr(collector, "session_scope", fake_scope)
        monkeypatch.setattr(
            collector, "BACKFILL_DEPTH", {Timeframe.H1: timedelta(days=40)}
        )

    def test_the_worker_registers_the_job(self):
        """A function ARQ does not know about is a job that never runs, which
        is precisely how this stayed quiet for ten phases."""
        names = [f.__name__ for f in collector.WorkerSettings.functions]

        assert "build_episodes_job" in names

    def test_there_is_a_cron_entry_for_it(self):
        """Registered but never scheduled is the same silence wearing a
        different hat."""
        assert len(collector.WorkerSettings.cron_jobs) >= 3

    def test_it_does_not_share_an_hour_with_the_dna_sweep(self):
        """Both walk the entire watchlist. Two full sweeps at once on a
        two-core box starve the collection cycle that has to land on the
        minute."""
        assert collector.EPISODE_BUILD_HOUR != collector.DNA_REFRESH_HOUR

    def test_it_writes_episodes_for_a_collected_instrument(self, monkeypatch):
        provider = FakeProvider({"BTC-USD": recent_bars(900)})
        monkeypatch.setattr(collector, "_resolve_provider", lambda: provider)
        entries = parse_watchlist("BTCUSD:BTC-USD:H1")
        collector.run_cycle(entries)

        result = collector.build_episodes(entries)

        assert result["built"] > 0
        assert result["failures"] == []

    def test_the_episodes_are_readable_afterwards(self, monkeypatch, session):
        """Written is not the same as retrievable. The similarity layer reads
        them back through `query`, so that is what is asserted."""
        from app.services import episodes as episode_service
        from app.services.instruments import get_instrument_by_symbol

        provider = FakeProvider({"BTC-USD": recent_bars(900)})
        monkeypatch.setattr(collector, "_resolve_provider", lambda: provider)
        entries = parse_watchlist("BTCUSD:BTC-USD:H1")
        collector.run_cycle(entries)
        collector.build_episodes(entries)

        instrument = get_instrument_by_symbol(session, "BTCUSD")
        # `as_of` is not optional here on purpose: an episode is evidence only
        # if its outcome had resolved by the moment being asked about, and a
        # default of "now" would quietly hand a backtest tomorrow's answers.
        stored = episode_service.query(
            session,
            instrument.id,
            Timeframe.H1,
            datetime.now(UTC),
            limit=5,
        )

        assert stored

    def test_a_second_sweep_adds_nothing(self, monkeypatch):
        """Re-running must not double the library. Near-duplicate episodes make
        similarity search confidently wrong - it returns matches that are one
        moment counted twice."""
        provider = FakeProvider({"BTC-USD": recent_bars(900)})
        monkeypatch.setattr(collector, "_resolve_provider", lambda: provider)
        entries = parse_watchlist("BTCUSD:BTC-USD:H1")
        collector.run_cycle(entries)
        collector.build_episodes(entries)

        again = collector.build_episodes(entries)

        assert again["built"] == 0
        assert again["skipped_existing"] > 0

    def test_an_unknown_symbol_is_skipped_not_crashed(self):
        result = collector.build_episodes(parse_watchlist("NOSUCH:NOSUCH=X:H1"))

        assert result["built"] == 0
        assert result["failures"] == []

    def test_an_instrument_short_of_history_does_not_stop_the_sweep(self, monkeypatch):
        """One thin symbol must not cost the other forty-eight their episodes."""
        provider = FakeProvider({"BTC-USD": recent_bars(900), "THIN=X": recent_bars(5)})
        monkeypatch.setattr(collector, "_resolve_provider", lambda: provider)
        entries = parse_watchlist("THIN:THIN=X:H1,BTCUSD:BTC-USD:H1")
        collector.run_cycle(entries)

        result = collector.build_episodes(entries)

        assert result["built"] > 0


class TestProviderComparison:
    """The detector that had no caller.

    `detect_provider_conflicts` shipped in phase 3 and never ran once. Not
    because it was broken - because `evaluate_bars` walks a single normalised
    series and a conflict needs two, so no path existed from ingestion to it.
    The one issue in `DataQualityIssue` requiring a second opinion could not be
    raised by any code path in the application.

    That cost nothing while there was one provider. It costs a great deal the
    first time a second feed disagrees and nobody is looking.
    """

    @pytest.fixture(autouse=True)
    def _patch_session(self, session, monkeypatch):
        from contextlib import contextmanager

        @contextmanager
        def fake_scope():
            yield session

        monkeypatch.setattr(collector, "session_scope", fake_scope)

    def test_the_worker_registers_the_job(self):
        names = [f.__name__ for f in collector.WorkerSettings.functions]

        assert "compare_providers_job" in names

    def test_there_is_a_cron_entry_for_it(self):
        assert len(collector.WorkerSettings.cron_jobs) >= 5

    def test_each_sweep_runs_at_its_own_hour(self):
        """All three walk the whole watchlist. Stacking them on a two-core box
        starves the collection cycle that has to land on the minute."""
        hours = {
            collector.DNA_REFRESH_HOUR,
            collector.EPISODE_BUILD_HOUR,
            collector.CONFLICT_CHECK_HOUR,
        }

        assert len(hours) == 3

    def test_a_single_provider_is_reported_as_unchecked_not_clean(
        self, monkeypatch, session
    ):
        """The distinction the whole codebase turns on. One feed was not found
        to agree with itself; it was not checked, and folding those together is
        how an unmeasured system reports itself healthy."""
        provider = FakeProvider({"BTC-USD": recent_bars(200)})
        monkeypatch.setattr(collector, "_resolve_provider", lambda: provider)
        entries = parse_watchlist("BTCUSD:BTC-USD:H1")
        collector.run_cycle(entries)

        result = collector.compare_providers(entries)

        assert result["compared"] == 0
        assert result["single_provider"] == 1
        assert result["conflicts"] == 0

    def test_an_unknown_symbol_is_skipped_not_crashed(self):
        result = collector.compare_providers(parse_watchlist("NOSUCH:NOSUCH=X:H1"))

        assert result["failures"] == []


class TestEveryPublishedTimeframeIsRead:
    """The bridge published M15 for weeks and none of it reached the database:
    `ingest_broker_bars` called `ingest` with its default and the default was
    hourly. Nothing failed. The files were on disk, the table had no rows, and
    a query for them looked exactly like a feed that had never sent anything.
    """

    def test_all_four_timeframes_are_requested(self, monkeypatch):
        from app.workers import collector

        asked: list[str] = []

        def fake_ingest(session, timeframe=None):
            asked.append(timeframe.value if timeframe else "default")
            return {"recorded": 1}

        monkeypatch.setattr("app.workers.broker_bars.ingest", fake_ingest)

        report = collector.ingest_broker_bars()

        assert set(asked) == {"H1", "M15", "M5", "M1"}
        assert report["recorded"] == 4

    def test_the_hourly_bars_survive_a_broken_minute_file(self, monkeypatch):
        """H1 is what the live rule decides on. A malformed M1 file must not
        take the bars the account is trading on down with it."""
        from app.workers import collector

        def fake_ingest(session, timeframe=None):
            if timeframe and timeframe.value == "M1":
                raise ValueError("malformed row")
            return {"recorded": 7}

        monkeypatch.setattr("app.workers.broker_bars.ingest", fake_ingest)

        report = collector.ingest_broker_bars()

        assert report["by_timeframe"]["H1"]["recorded"] == 7
        assert report["by_timeframe"]["M1"]["recorded"] == 0
        assert "ValueError" in report["by_timeframe"]["M1"]["reason"]

    def test_the_hourly_timeframe_is_still_among_them(self):
        """The faster ones are for measuring. Dropping the one the live rule
        decides on while adding them would be a silent downgrade."""
        from app.core.enums import Timeframe
        from app.workers.collector import _broker_timeframes

        assert Timeframe.H1 in _broker_timeframes()


class TestWhichTimeframesTheRuleDecidesOn:
    """Adding a faster timeframe is how the forward test stops needing a year:
    the same ~6,573 instants arrive about twelve times sooner on M5. What must
    not happen is a typo in one environment variable quietly stopping the
    hourly decisions the account is actually trading on."""

    def test_the_default_is_hourly_only(self):
        from app.core.enums import Timeframe
        from app.workers.collector import _forward_timeframes

        assert _forward_timeframes() == (Timeframe.H1,)

    def test_a_faster_timeframe_can_be_added(self, monkeypatch):
        from app.core.config import get_settings
        from app.core.enums import Timeframe
        from app.workers.collector import _forward_timeframes

        monkeypatch.setattr(
            get_settings(), "forward_timeframes", "H1,M5", raising=False
        )

        assert _forward_timeframes() == (Timeframe.H1, Timeframe.M5)

    def test_hourly_survives_being_left_out(self, monkeypatch):
        """The live rule decides on it. A deployment that names only M5 has
        almost certainly not decided to stop trading hourly."""
        from app.core.config import get_settings
        from app.core.enums import Timeframe
        from app.workers.collector import _forward_timeframes

        monkeypatch.setattr(get_settings(), "forward_timeframes", "M5", raising=False)

        assert _forward_timeframes()[0] is Timeframe.H1

    def test_an_unreadable_name_is_dropped_and_the_rest_kept(self, monkeypatch):
        from app.core.config import get_settings
        from app.core.enums import Timeframe
        from app.workers.collector import _forward_timeframes

        monkeypatch.setattr(
            get_settings(), "forward_timeframes", "H1, M7 ,M5", raising=False
        )

        assert _forward_timeframes() == (Timeframe.H1, Timeframe.M5)

    def test_a_repeated_name_is_recorded_once(self, monkeypatch):
        """Twice through would write the same instant twice and inflate the
        very sample the whole measurement rests on."""
        from app.core.config import get_settings
        from app.workers.collector import _forward_timeframes

        monkeypatch.setattr(
            get_settings(), "forward_timeframes", "H1,M5,M5,H1", raising=False
        )

        assert len(_forward_timeframes()) == len(set(_forward_timeframes()))

    def test_an_empty_setting_still_decides(self, monkeypatch):
        from app.core.config import get_settings
        from app.core.enums import Timeframe
        from app.workers.collector import _forward_timeframes

        monkeypatch.setattr(get_settings(), "forward_timeframes", "", raising=False)

        assert _forward_timeframes() == (Timeframe.H1,)
