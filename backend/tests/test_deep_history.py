"""Importing twenty years without importing twenty years of wrong prices.

The failure this guards against does not raise anywhere. Dukascopy publishes
scaled integers and the scale differs per instrument, so applying the wrong one
puts gold at 20.63 instead of 2063.63 - and every moving average, every ATR and
every ranking downstream accepts it, because the whole series is wrong by the
same factor and nothing looks odd in isolation.

So the tests here are mostly about the two refusals: nothing is imported
without its scale checked against a price from a different source, and no
period that could not be read is dropped in silence.
"""

from __future__ import annotations

import struct
from datetime import UTC, datetime

import pytest

from app.core.enums import AssetClass, Timeframe
from app.core.errors import ProviderError
from app.models.instruments import Instrument
from app.models.market_data import Bar
from app.providers.dukascopy import DukascopyProvider
from app.workers import deep_history

NOW = datetime(2026, 8, 16, tzinfo=UTC)


def year_of_bars(price_int: int, days: int = 30) -> bytes:
    """A file of `days` daily candles, all at one price."""
    return b"".join(
        struct.pack(
            ">5If",
            day * 86400,
            price_int,
            price_int,
            price_int,
            price_int,
            100.0,
        )
        for day in range(days)
    )


class FakeFeed(DukascopyProvider):
    """The real provider with only the socket replaced.

    Subclassed rather than mocked so the scale verification, the window
    filtering and the missing-period accounting are the real code paths - those
    are the parts worth testing, and a mock of `fetch_ohlcv` would test none of
    them.
    """

    def __init__(
        self, body: bytes, *, hourly: bytes | None = None, serves: int | None = None
    ):
        super().__init__()
        self.body = body
        # Answer a fixed number of files and then nothing. Without this a
        # multi-year window gets the same body back for every year, at a
        # different period start each time, and the row count becomes a
        # function of the window rather than of the fixture.
        self.serves = serves
        self.served = 0
        # Answered separately so a feed that can be verified but has no file
        # for the window is expressible - which is the case the hole reporting
        # exists for, and the one a single body cannot reach.
        self.hourly = hourly

    def _fetch(self, url: str) -> bytes:  # type: ignore[override]
        if "hour" in url and self.hourly is not None:
            return self.hourly
        if self.serves is not None and self.served >= self.serves:
            return b""
        self.served += 1
        return self.body


@pytest.fixture()
def eurusd(session, provider):
    """An instrument with one bar from another source - a reference price."""
    row = Instrument(symbol="EURUSD", name="Euro", asset_class=AssetClass.FOREX)
    session.add(row)
    session.flush()
    session.add(
        Bar(
            instrument_id=row.id,
            timeframe=Timeframe.H1.value,
            provider_id=provider.id,
            event_time=NOW,
            revision=1,
            ingested_at=NOW,
            open=1.10,
            high=1.11,
            low=1.09,
            close=1.10,
            volume=1.0,
            quality_score=1.0,
        )
    )
    session.flush()
    return row


class TestNothingIsImportedOnAGuessedScale:
    def test_an_instrument_with_no_other_price_is_skipped_by_name(self, session):
        """The refusal that matters. Importing on the table's guess is how a
        hundredfold error enters a series nobody looks at closely."""
        report = deep_history.backfill(
            session,
            symbols=["GBPUSD"],
            provider=FakeFeed(year_of_bars(127275)),
            end=NOW,
        )

        assert report["written"] == 0
        assert any("verify the scale against" in note for note in report["skipped"])

    def test_a_verifiable_instrument_is_imported(self, session, eurusd):
        report = deep_history.backfill(
            session,
            symbols=["EURUSD"],
            provider=FakeFeed(year_of_bars(110366)),
            start_year=2024,
            end=NOW,
        )

        assert report["written"] > 0
        assert report["by_symbol"]["EURUSD"] > 0

    def test_the_stored_prices_are_at_the_right_scale(self, session, eurusd):
        """The whole point, checked against the number in the table rather
        than against the parser's own arithmetic."""
        deep_history.backfill(
            session,
            symbols=["EURUSD"],
            provider=FakeFeed(year_of_bars(110366)),
            start_year=2024,
            end=NOW,
        )

        stored = (
            session.query(Bar)
            .filter(Bar.timeframe == Timeframe.D1.value)
            .order_by(Bar.event_time)
            .first()
        )
        assert float(stored.close) == pytest.approx(1.10366, abs=1e-5)

    def test_a_feed_price_that_matches_no_scale_is_refused(self, session, eurusd):
        """An instrument this feed prices unlike every other is exactly the
        one worth stopping on."""
        report = deep_history.backfill(
            session,
            symbols=["EURUSD"],
            provider=FakeFeed(year_of_bars(98765432)),
            start_year=2024,
            end=NOW,
        )

        assert report["written"] == 0
        assert any("no candidate scale" in note for note in report["skipped"])

    def test_the_reference_never_comes_from_dukascopy_itself(self, session, eurusd):
        """Verifying a feed against itself verifies nothing, so a second run
        must not start trusting the first run's output."""
        deep_history.backfill(
            session,
            symbols=["EURUSD"],
            provider=FakeFeed(year_of_bars(110366)),
            start_year=2024,
            end=NOW,
        )

        # The reference still comes from the other provider's H1 bar.
        assert deep_history.reference_price(session, eurusd.id) == pytest.approx(1.10)


class TestReRunningIsSafe:
    def test_the_same_window_twice_does_not_duplicate(self, session, eurusd):
        """Somebody will re-run this: the first attempt at twenty years hits a
        network error somewhere in the middle."""
        args = dict(
            symbols=["EURUSD"],
            provider=FakeFeed(year_of_bars(110366)),
            start_year=2024,
            end=NOW,
        )
        deep_history.backfill(session, **args)
        first = session.query(Bar).filter(Bar.timeframe == Timeframe.D1.value).count()

        deep_history.backfill(session, **args)
        second = session.query(Bar).filter(Bar.timeframe == Timeframe.D1.value).count()

        assert first == second > 0


class TestItStaysItsOwnSource:
    def test_the_bars_land_under_the_dukascopy_provider(self, session, eurusd):
        """Merging three sources means the last writer wins and the
        disagreement between them - itself a measurement - is never seen."""
        from app.models.instruments import Provider

        deep_history.backfill(
            session,
            symbols=["EURUSD"],
            provider=FakeFeed(year_of_bars(110366)),
            start_year=2024,
            end=NOW,
        )

        code = session.query(Provider.code).join(
            Bar, Bar.provider_id == Provider.id
        ).filter(Bar.timeframe == Timeframe.D1.value).distinct().all()

        assert code == [("dukascopy",)]

    def test_it_does_not_disturb_the_existing_series(self, session, eurusd, provider):
        before = session.query(Bar).filter(Bar.provider_id == provider.id).count()

        deep_history.backfill(
            session,
            symbols=["EURUSD"],
            provider=FakeFeed(year_of_bars(110366)),
            start_year=2024,
            end=NOW,
        )

        assert session.query(Bar).filter(Bar.provider_id == provider.id).count() == before


class TestNothingIsDroppedQuietly:
    def test_a_period_with_no_file_is_reported(self, session, eurusd):
        """A hole is not a closed market, and the ranking excludes instruments
        whose series went quiet - so a hole does not merely lose data, it
        changes which instruments get ranked.

        The scale verifies off the daily file; the hourly files the window
        actually wants are absent. That split is the case worth testing - a
        feed that fails outright is caught earlier and never reaches here."""
        report = deep_history.backfill(
            session,
            symbols=["EURUSD"],
            timeframe=Timeframe.H1,
            provider=FakeFeed(year_of_bars(110366), hourly=b""),
            start_year=2026,
            end=NOW,
        )

        assert report["periods_with_no_file"]
        assert any("no bars in that window" in note for note in report["skipped"])

    def test_a_feed_that_cannot_be_verified_at_all_is_skipped_earlier(
        self, session, eurusd
    ):
        """And reports no holes, because it never got as far as the window.
        Reporting holes here would describe periods nobody asked for."""
        report = deep_history.backfill(
            session,
            symbols=["EURUSD"],
            provider=FakeFeed(b""),
            start_year=2024,
            end=NOW,
        )

        assert report["written"] == 0
        assert report["periods_with_no_file"] == []
        assert any("served nothing" in note for note in report["skipped"])

    def test_a_skip_and_a_hole_are_reported_separately(self, session, eurusd):
        """Different problems with different fixes. One count for both invites
        neither."""
        report = deep_history.backfill(
            session,
            symbols=["EURUSD", "NOREFERENCE"],
            provider=FakeFeed(year_of_bars(110366)),
            start_year=2024,
            end=NOW,
        )

        assert "skipped" in report
        assert "periods_with_no_file" in report
        assert any("NOREFERENCE" in note for note in report["skipped"])

    def test_one_bad_symbol_does_not_stop_the_others(self, session, eurusd):
        report = deep_history.backfill(
            session,
            symbols=["NOREFERENCE", "EURUSD"],
            provider=FakeFeed(year_of_bars(110366)),
            start_year=2024,
            end=NOW,
        )

        assert report["by_symbol"].get("EURUSD", 0) > 0
        assert len(report["skipped"]) == 1


class TestTheReferenceLookup:
    def test_no_bars_at_all_gives_none_rather_than_a_default(self, session):
        row = Instrument(symbol="NEW", name="New", asset_class=AssetClass.FOREX)
        session.add(row)
        session.flush()

        assert deep_history.reference_price(session, row.id) is None

    def test_a_provider_error_names_the_symbol_it_came_from(self, session, eurusd):
        class Broken(FakeFeed):
            def verify_scale(self, symbol, reference, *, at):  # type: ignore[override]
                raise ProviderError("the feed served nothing")

        report = deep_history.backfill(
            session, symbols=["EURUSD"], provider=Broken(b""), end=NOW
        )

        assert any(note.startswith("EURUSD:") for note in report["skipped"])


class TestTheEntryPoint:
    """A real command rather than a shell one-liner: this writes hundreds of
    thousands of rows, and the arguments that decide how many should be visible
    in the command rather than buried inside a quoted script."""

    def test_the_default_symbols_are_all_in_the_ranked_universe(self):
        """Importing an instrument the rule never ranks costs an hour of
        requests and answers nothing."""
        from app.brain.crosssection import RANKED_UNIVERSE

        assert set(deep_history.OFFERED) <= RANKED_UNIVERSE

    def test_there_are_enough_of_them_to_rank(self):
        """Below twenty the rule refuses, so a backfill of nineteen would be
        an hour spent producing a series that can never be measured."""
        from app.brain.crosssection import MIN_CROSS_SECTION

        assert len(deep_history.OFFERED) >= MIN_CROSS_SECTION

    def test_a_dry_run_writes_nothing(self, session, eurusd, monkeypatch):
        """The step that decides whether the import is trustworthy costs one
        request per symbol. Finding out six cannot be verified is much cheaper
        before the other 3,700 requests than after."""
        from contextlib import contextmanager

        @contextmanager
        def fixed_session():
            yield session

        monkeypatch.setattr(
            "app.db.session.session_scope", fixed_session, raising=False
        )
        monkeypatch.setattr(
            deep_history, "DukascopyProvider", lambda: FakeFeed(year_of_bars(110366))
        )
        before = session.query(Bar).count()

        code = deep_history.main(["--dry-run", "--symbols", "EURUSD"])

        assert code == 0
        assert session.query(Bar).count() == before

    def test_an_unknown_timeframe_is_rejected_by_the_parser(self):
        """Rather than reaching the feed and 404ing 3,700 times."""
        with pytest.raises(SystemExit):
            deep_history.main(["--timeframe", "M5"])


class TestAPartialImportDoesNotLookLikeSuccess:
    """The real dry run got fifteen answers then thirteen consecutive 503s. A
    report of "imported 15" reads as success. Fifteen is below the minimum
    cross-section so nothing could be measured on it - but had the throttle cut
    in at twenty-two, the measurement would have run happily across a universe
    chosen by which requests the feed felt like answering."""

    def test_too_few_symbols_is_flagged(self, session, eurusd):
        report = deep_history.backfill(
            session,
            symbols=["EURUSD"],
            provider=FakeFeed(year_of_bars(110366)),
            start_year=2024,
            end=NOW,
        )

        assert report["usable_for_ranking"] is False
        assert "chosen by which requests succeeded" in report["universe_warning"]

    def test_a_full_import_carries_no_warning(self, session, provider):
        from app.brain.crosssection import MIN_CROSS_SECTION, RANKED_UNIVERSE

        symbols = sorted(RANKED_UNIVERSE)[:MIN_CROSS_SECTION]
        for symbol in symbols:
            row = Instrument(
                symbol=symbol, name=symbol, asset_class=AssetClass.FOREX
            )
            session.add(row)
            session.flush()
            session.add(
                Bar(
                    instrument_id=row.id,
                    timeframe=Timeframe.H1.value,
                    provider_id=provider.id,
                    event_time=NOW,
                    revision=1,
                    ingested_at=NOW,
                    open=1.10,
                    high=1.11,
                    low=1.09,
                    close=1.10,
                    volume=1.0,
                    quality_score=1.0,
                )
            )
        session.flush()

        report = deep_history.backfill(
            session,
            symbols=symbols,
            provider=FakeFeed(year_of_bars(110366)),
            start_year=2024,
            end=NOW,
        )

        assert report["usable_for_ranking"] is True
        assert report["universe_warning"] is None

    def test_the_throttle_count_reaches_the_report(self, session, eurusd):
        """A run that retried four hundred times succeeded, and that is worth
        knowing before the next one is scheduled."""
        report = deep_history.backfill(
            session,
            symbols=["EURUSD"],
            provider=FakeFeed(year_of_bars(110366)),
            start_year=2024,
            end=NOW,
        )

        assert "throttled" in report


class TestALongRunSurvivesOneFailure:
    """The hourly run is roughly 3,700 requests over forty minutes. A single
    transaction means one failure at the twenty-seventh symbol discards the
    other twenty-six."""

    def test_work_done_before_a_failure_is_kept(self, session, provider):
        from app.brain.crosssection import RANKED_UNIVERSE

        symbols = sorted(RANKED_UNIVERSE)[:3]
        for symbol in symbols:
            row = Instrument(
                symbol=symbol, name=symbol, asset_class=AssetClass.FOREX
            )
            session.add(row)
            session.flush()
            session.add(
                Bar(
                    instrument_id=row.id,
                    timeframe=Timeframe.H1.value,
                    provider_id=provider.id,
                    event_time=NOW,
                    revision=1,
                    ingested_at=NOW,
                    open=1.10,
                    high=1.11,
                    low=1.09,
                    close=1.10,
                    volume=1.0,
                    quality_score=1.0,
                )
            )
        session.flush()

        class FailsOnTheThird(FakeFeed):
            def __init__(self):
                super().__init__(year_of_bars(110366))
                self.seen = 0

            def verify_scale(self, symbol, reference, *, at):  # type: ignore[override]
                self.seen += 1
                if self.seen >= 3:
                    raise ProviderError("the feed stopped answering")
                return super().verify_scale(symbol, reference, at=at)

        report = deep_history.backfill(
            session,
            symbols=symbols,
            provider=FailsOnTheThird(),
            start_year=2024,
            end=NOW,
        )

        # The first two are on disk, not rolled back with the third.
        assert len(report["by_symbol"]) == 2
        assert (
            session.query(Bar).filter(Bar.timeframe == Timeframe.D1.value).count() > 0
        )


class TestTheInsertStaysUnderTheProtocolLimit:
    """PostgreSQL caps a statement at 65535 bound parameters. A bar carries
    thirteen columns, so the ceiling is 5,041 rows - and twenty years of daily
    bars is about 5,200 per symbol. The first real backfill died on the first
    symbol for exactly this reason."""

    def test_the_chunk_leaves_room_for_columns_nobody_has_added_yet(self):
        columns = len(Bar.__table__.columns)

        assert deep_history.INSERT_CHUNK * columns < 65535

    def test_more_bars_than_one_statement_allows_are_written(
        self, session, eurusd
    ):
        """The regression. Six thousand daily bars is past the limit, and
        before chunking this raised OperationalError rather than writing."""
        # Past the 5,041-row ceiling a single statement allows.
        big = year_of_bars(110366, days=6000)

        report = deep_history.backfill(
            session,
            symbols=["EURUSD"],
            # Two serves: the scale check consumes one, the window the other.
            provider=FakeFeed(big, serves=2),
            start_year=2005,
            end=datetime(2045, 1, 1, tzinfo=UTC),
        )

        assert report["by_symbol"]["EURUSD"] == 6000
        assert 6000 * len(Bar.__table__.columns) > 65535
        assert (
            session.query(Bar).filter(Bar.timeframe == Timeframe.D1.value).count()
            == 6000
        )

    def test_a_chunked_write_still_upserts_rather_than_duplicating(
        self, session, eurusd
    ):
        big = year_of_bars(110366, days=6000)

        def run():
            return deep_history.backfill(
                session,
                symbols=["EURUSD"],
                provider=FakeFeed(big, serves=2),
                start_year=2005,
                end=datetime(2045, 1, 1, tzinfo=UTC),
            )

        run()
        run()

        assert (
            session.query(Bar).filter(Bar.timeframe == Timeframe.D1.value).count()
            == 6000
        )


class TestItGivesUpInsteadOfGrinding:
    """Measured on the live feed: ten requests 0.6s apart got five answers,
    2s apart got two, 5s apart got one - in that order. Slowing down made it
    worse, which is not how a rate limit behaves. Against an endpoint that has
    simply stopped answering, retrying twenty-eight symbols at six attempts
    each spends three hours proving the same refusal and writes nothing."""

    def all_symbols(self, session, provider, count):
        from app.brain.crosssection import RANKED_UNIVERSE

        symbols = sorted(RANKED_UNIVERSE)[:count]
        for symbol in symbols:
            row = Instrument(
                symbol=symbol, name=symbol, asset_class=AssetClass.FOREX
            )
            session.add(row)
            session.flush()
            session.add(
                Bar(
                    instrument_id=row.id,
                    timeframe=Timeframe.H1.value,
                    provider_id=provider.id,
                    event_time=NOW,
                    revision=1,
                    ingested_at=NOW,
                    open=1.10,
                    high=1.11,
                    low=1.09,
                    close=1.10,
                    volume=1.0,
                    quality_score=1.0,
                )
            )
        session.flush()
        return symbols

    def test_it_stops_after_consecutive_failures(self, session, provider):
        symbols = self.all_symbols(session, provider, 20)

        class Refuses(FakeFeed):
            def __init__(self):
                super().__init__(b"")
                self.asked = 0

            def verify_scale(self, symbol, reference, *, at):  # type: ignore[override]
                self.asked += 1
                raise ProviderError("503 all the way down")

        feed = Refuses()
        report = deep_history.backfill(
            session, symbols=symbols, provider=feed, end=NOW
        )

        assert report["gave_up"]
        assert feed.asked == deep_history.CONSECUTIVE_FAILURES_BEFORE_STOPPING
        assert len(symbols) > feed.asked

    def test_a_success_resets_the_counter(self, session, provider):
        """Scattered failures are not the same as a dead feed, and a run that
        gave up on three bad symbols spread across twenty-eight would be
        throwing away a working import."""
        symbols = self.all_symbols(session, provider, 12)

        class EveryOther(FakeFeed):
            def __init__(self):
                super().__init__(year_of_bars(110366))
                self.asked = 0

            def verify_scale(self, symbol, reference, *, at):  # type: ignore[override]
                self.asked += 1
                if self.asked % 2:
                    raise ProviderError("intermittent")
                return super().verify_scale(symbol, reference, at=at)

        feed = EveryOther()
        report = deep_history.backfill(
            session, symbols=symbols, provider=feed, start_year=2024, end=NOW
        )

        assert report["gave_up"] is None
        assert feed.asked == len(symbols)
        assert len(report["by_symbol"]) == 6

    def test_a_missing_reference_does_not_count_toward_giving_up(
        self, session, provider
    ):
        """That is a fact about our own database, not about the feed, and it
        would still be true on a day the feed answered perfectly."""
        report = deep_history.backfill(
            session,
            symbols=["NOREF1", "NOREF2", "NOREF3", "NOREF4", "NOREF5"],
            provider=FakeFeed(year_of_bars(110366)),
            end=NOW,
        )

        assert report["gave_up"] is None
        assert len(report["skipped"]) == 5

    def test_work_done_before_giving_up_is_kept(self, session, provider):
        symbols = self.all_symbols(session, provider, 10)

        class DiesAfterTwo(FakeFeed):
            def __init__(self):
                super().__init__(year_of_bars(110366))
                self.asked = 0

            def verify_scale(self, symbol, reference, *, at):  # type: ignore[override]
                self.asked += 1
                if self.asked > 2:
                    raise ProviderError("the feed stopped answering")
                return super().verify_scale(symbol, reference, at=at)

        report = deep_history.backfill(
            session, symbols=symbols, provider=DiesAfterTwo(),
            start_year=2024, end=NOW,
        )

        assert report["gave_up"]
        assert len(report["by_symbol"]) == 2
        assert report["written"] > 0
