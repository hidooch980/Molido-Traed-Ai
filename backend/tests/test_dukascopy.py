"""Reading a bank's twenty-year book without silently getting the prices wrong.

The wire format is undocumented, so the fixtures below are real bytes captured
from the live endpoint rather than bytes this project invented. That matters:
a test built from `struct.pack` with the same field order as the parser passes
whether or not the field order is right, and every failure this module can have
is a failure that produces plausible numbers.

Four of those failures are one line each, and each one is tested by name.
"""

from __future__ import annotations

import struct
from datetime import UTC, datetime

import pytest

from app.core.enums import Timeframe
from app.core.errors import ProviderError
from app.providers import dukascopy as dk

#: Real bytes. EURUSD hourly, January 2024, first record - the hour of New
#: Year's Day, when the book is closed and every price is the same.
REAL_HOUR_0 = bytes.fromhex("000000000001af260001af260001af260001af2600000000")

#: Real bytes. EURUSD daily, 2024, second record - a trading day, so the four
#: prices differ and the order can actually be checked.
REAL_DAY_1 = bytes.fromhex("000000000001af5b0001af1d0001af140001af6f45753f5c")

#: Real bytes. EURUSD ticks, 2 January 2024, 10:00 - first tick.
REAL_TICK_0 = bytes.fromhex("000000e00001ae460001ae453f7d70a440900000")


class TestTheFieldOrderIsNotOHLC:
    """The middle four fields are open, close, low, high. Reading them as OHLC
    produces bars whose high is below their low, which no indicator in this
    project checks and every one of them will average."""

    def test_the_real_bytes_decode_to_a_sane_bar(self):
        [bar] = dk.decode_candles(
            REAL_DAY_1, period_start=datetime(2024, 1, 1, tzinfo=UTC), scale=1e5
        )

        assert bar.open == pytest.approx(1.10427)
        assert bar.close == pytest.approx(1.10365)
        assert bar.low == pytest.approx(1.10356)
        assert bar.high == pytest.approx(1.10447)

    def test_the_high_is_the_highest_and_the_low_the_lowest(self):
        """The assertion that fails the moment somebody 'fixes' the order to
        look like OHLC. On these real bytes, the OHLC reading gives a high of
        1.10365 and a low of 1.10447 - inverted."""
        [bar] = dk.decode_candles(
            REAL_DAY_1, period_start=datetime(2024, 1, 1, tzinfo=UTC), scale=1e5
        )

        assert bar.high >= max(bar.open, bar.close)
        assert bar.low <= min(bar.open, bar.close)

    def test_a_closed_period_decodes_flat_rather_than_broken(self):
        [bar] = dk.decode_candles(
            REAL_HOUR_0, period_start=datetime(2024, 1, 1, tzinfo=UTC), scale=1e5
        )

        assert bar.open == bar.high == bar.low == bar.close == pytest.approx(1.10374)
        assert bar.tick_volume == 0.0


class TestTheOffsetsAreSeconds:
    def test_an_hourly_offset_lands_on_the_hour(self):
        record = struct.pack(">5If", 3600, 110000, 110100, 109900, 110200, 5.0)

        [bar] = dk.decode_candles(
            record, period_start=datetime(2024, 1, 1, tzinfo=UTC), scale=1e5
        )

        assert bar.event_time == datetime(2024, 1, 1, 1, 0, tzinfo=UTC)

    def test_a_daily_offset_lands_on_the_day(self):
        record = struct.pack(">5If", 86400, 110000, 110100, 109900, 110200, 5.0)

        [bar] = dk.decode_candles(
            record, period_start=datetime(2024, 1, 1, tzinfo=UTC), scale=1e5
        )

        assert bar.event_time == datetime(2024, 1, 2, tzinfo=UTC)


class TestTheMonthIsZeroIndexed:
    """January is `00` in the path. A one-month shift produces a series that
    looks completely normal and is wrong at every point in it."""

    def test_january_is_double_zero(self):
        url = dk._url("EURUSD", Timeframe.H1, datetime(2024, 1, 15, tzinfo=UTC))

        assert url.endswith("/EURUSD/2024/00/BID_candles_hour_1.bi5")

    def test_december_is_eleven(self):
        url = dk._url("EURUSD", Timeframe.H1, datetime(2024, 12, 15, tzinfo=UTC))

        assert url.endswith("/EURUSD/2024/11/BID_candles_hour_1.bi5")

    def test_the_daily_file_is_per_year_with_no_month_at_all(self):
        url = dk._url("EURUSD", Timeframe.D1, datetime(2024, 7, 15, tzinfo=UTC))

        assert url.endswith("/EURUSD/2024/BID_candles_day_1.bi5")

    def test_an_unsupported_timeframe_is_refused_not_approximated(self):
        with pytest.raises(ProviderError, match="day, hour and minute"):
            dk._url("EURUSD", Timeframe.M15, datetime(2024, 1, 1, tzinfo=UTC))


class TestTheScaleIsNeverAssumed:
    """Applying 1e5 to gold puts it at 20.63 instead of 2063.63. Nothing
    downstream raises; every ATR simply believes it."""

    def test_a_reference_price_picks_the_scale(self):
        assert dk.infer_scale(110366, 1.1037) == 1e5
        assert dk.infer_scale(2063625, 2063.6) == 1e3
        assert dk.infer_scale(141110, 141.11) == 1e3

    def test_a_scale_that_matches_nothing_raises(self):
        with pytest.raises(ProviderError, match="no candidate scale"):
            dk.infer_scale(110366, 87654.0)

    def test_there_is_no_scale_without_a_reference(self):
        """The whole point. A default here would be the bug."""
        with pytest.raises(ProviderError, match="reference price"):
            dk.infer_scale(110366, 0.0)

    def test_fetching_an_unverified_symbol_is_refused(self):
        provider = dk.DukascopyProvider()

        with pytest.raises(ProviderError, match="no verified price scale"):
            provider.fetch_ohlcv(
                "EURUSD",
                Timeframe.D1,
                datetime(2024, 1, 1, tzinfo=UTC),
                datetime(2024, 2, 1, tzinfo=UTC),
            )

    def test_gold_at_the_wrong_scale_is_caught_by_the_reference(self):
        """The concrete failure, spelled out: gold's raw integer under the FX
        scale is 20.63, and the reference is what notices."""
        assert 2063625 / 1e5 == pytest.approx(20.63625)
        assert dk.infer_scale(2063625, 2063.6) == 1e3


class TestAMisreadFileIsLoudNotQuiet:
    def test_a_body_that_does_not_divide_evenly_raises(self):
        """A leftover tail means the record size is wrong, and every bar in
        the file is misaligned. Dropping the tail hides that."""
        with pytest.raises(ProviderError, match="whole number"):
            dk.decode_candles(
                REAL_DAY_1 + b"\x00\x01",
                period_start=datetime(2024, 1, 1, tzinfo=UTC),
                scale=1e5,
            )

    def test_a_zero_price_record_is_dropped_not_scaled(self):
        """A period the feed has no book for is not a bar at zero, and a 0.0
        entering a fifty-bar mean moves it by two percent."""
        record = struct.pack(">5If", 0, 0, 0, 0, 0, 0.0)

        assert dk.decode_candles(
            record, period_start=datetime(2024, 1, 1, tzinfo=UTC), scale=1e5
        ) == []


class TestTicks:
    def test_ask_comes_before_bid_on_the_wire(self):
        [tick] = dk.decode_ticks(
            REAL_TICK_0, hour_start=datetime(2024, 1, 2, 10, tzinfo=UTC), scale=1e5
        )

        assert tick["ask"] == pytest.approx(1.10150)
        assert tick["bid"] == pytest.approx(1.10149)
        # The spread is positive, which is the check that catches them swapped.
        assert tick["ask"] > tick["bid"]

    def test_the_offset_is_milliseconds(self):
        [tick] = dk.decode_ticks(
            REAL_TICK_0, hour_start=datetime(2024, 1, 2, 10, tzinfo=UTC), scale=1e5
        )

        assert tick["event_time"] == datetime(
            2024, 1, 2, 10, 0, 0, 224_000, tzinfo=UTC
        )


class TestTheSymbolCannotSteerTheFetch:
    """The symbol goes into a URL path, and instrument names come from a table
    somebody can insert into by hand."""

    @pytest.mark.parametrize(
        "bad", ["../../etc/passwd", "EUR/USD", "file:///etc/passwd", "", "EUR USD"]
    )
    def test_a_name_that_is_not_a_plain_symbol_is_refused(self, bad):
        with pytest.raises(ProviderError):
            dk._url(bad, Timeframe.D1, datetime(2024, 1, 1, tzinfo=UTC))

    def test_a_url_off_this_feed_is_refused_even_if_it_gets_that_far(self):
        provider = dk.DukascopyProvider()

        with pytest.raises(ProviderError, match="not this feed"):
            provider._fetch("https://example.com/whatever.bi5")


class TestTheWindow:
    def test_a_closed_period_is_skipped_rather_than_failing_the_backfill(self):
        """Weekends are zero-length bodies. Raising on them would make every
        backfill spanning a Saturday look broken."""
        provider = dk.DukascopyProvider(scales={"EURUSD": 1e5})
        provider._fetch = lambda url: b""  # type: ignore[method-assign]

        assert (
            provider.fetch_ohlcv(
                "EURUSD",
                Timeframe.D1,
                datetime(2024, 1, 1, tzinfo=UTC),
                datetime(2024, 2, 1, tzinfo=UTC),
            )
            == []
        )

    def test_bars_outside_the_window_are_not_returned(self):
        """The file holds a whole year; the caller asked for a month."""
        provider = dk.DukascopyProvider(scales={"EURUSD": 1e5})
        body = b"".join(
            struct.pack(">5If", day * 86400, 110000, 110100, 109900, 110200, 1.0)
            for day in range(60)
        )
        provider._fetch = lambda url: body  # type: ignore[method-assign]

        bars = provider.fetch_ohlcv(
            "EURUSD",
            Timeframe.D1,
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 2, 1, tzinfo=UTC),
        )

        assert len(bars) == 31
        assert bars[0].event_time == datetime(2024, 1, 1, tzinfo=UTC)
        assert bars[-1].event_time == datetime(2024, 1, 31, tzinfo=UTC)

    def test_the_bars_come_back_ascending(self):
        provider = dk.DukascopyProvider(scales={"EURUSD": 1e5})
        body = b"".join(
            struct.pack(">5If", day * 86400, 110000, 110100, 109900, 110200, 1.0)
            for day in (5, 1, 3, 2)
        )
        provider._fetch = lambda url: body  # type: ignore[method-assign]

        bars = provider.fetch_ohlcv(
            "EURUSD",
            Timeframe.D1,
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 2, 1, tzinfo=UTC),
        )

        assert [b.event_time for b in bars] == sorted(b.event_time for b in bars)

    def test_one_file_is_requested_per_month_for_hourly_data(self):
        asked: list[str] = []
        provider = dk.DukascopyProvider(scales={"EURUSD": 1e5})
        provider._fetch = lambda url: asked.append(url) or b""  # type: ignore[method-assign,func-returns-value]

        provider.fetch_ohlcv(
            "EURUSD",
            Timeframe.H1,
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 4, 1, tzinfo=UTC),
        )

        assert len(asked) == 3
        assert asked[0].endswith("2024/00/BID_candles_hour_1.bi5")
        assert asked[2].endswith("2024/02/BID_candles_hour_1.bi5")


class TestItSatisfiesTheProviderContract:
    def test_it_is_a_market_data_provider(self):
        from app.providers.base import MarketDataProvider

        assert isinstance(dk.DukascopyProvider(), MarketDataProvider)

    def test_it_declares_history_back_to_2003(self):
        """The reason this source is here at all: an independent sample that
        covers rate cycles and crises the two-year hourly window does not."""
        assert dk.DukascopyProvider().capabilities().history_start.year == 2003

    def test_it_publishes_no_symbol_catalogue_rather_than_a_stale_one(self):
        """A hardcoded list would drift from what the endpoint serves. USDCAD
        already answers 404 on the daily path every other major answers."""
        assert dk.DukascopyProvider().list_symbols() == []


class TestAHoleIsNamedRatherThanLeftInTheSeries:
    """Weekends come back empty legitimately, and so does a year the feed has
    a gap in. A backfill that returns fewer bars without saying which periods
    it could not read leaves a history whose holes nothing downstream can tell
    apart from a market that was closed."""

    def test_an_empty_period_is_recorded_by_name(self):
        provider = dk.DukascopyProvider(scales={"EURUSD": 1e5})
        provider._fetch = lambda url: b""  # type: ignore[method-assign]

        provider.fetch_ohlcv(
            "EURUSD",
            Timeframe.H1,
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 3, 1, tzinfo=UTC),
        )

        assert provider.missing_periods == [
            "EURUSD/2024/00/BID_candles_hour_1.bi5",
            "EURUSD/2024/01/BID_candles_hour_1.bi5",
        ]

    def test_the_list_is_reset_per_call_not_accumulated(self):
        """Otherwise the second backfill inherits the first one's holes and
        reports gaps that were already filled."""
        provider = dk.DukascopyProvider(scales={"EURUSD": 1e5})
        provider._fetch = lambda url: b""  # type: ignore[method-assign]
        window = (datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 2, 1, tzinfo=UTC))

        provider.fetch_ohlcv("EURUSD", Timeframe.H1, *window)
        provider.fetch_ohlcv("EURUSD", Timeframe.H1, *window)

        assert len(provider.missing_periods) == 1

    def test_a_transient_network_error_raises_rather_than_reading_as_empty(self):
        """The distinction that matters. A 404 is a period the feed does not
        hold; a dropped connection is a period nobody read, and treating the
        second as the first writes a hole into ten years of history and calls
        it a closed market."""
        import urllib.error

        provider = dk.DukascopyProvider(scales={"EURUSD": 1e5})

        def drop(request, timeout=None):
            raise urllib.error.URLError("connection reset")

        provider._opener = drop

        with pytest.raises(ProviderError, match="could not be read"):
            provider.fetch_ohlcv(
                "EURUSD",
                Timeframe.D1,
                datetime(2024, 1, 1, tzinfo=UTC),
                datetime(2024, 2, 1, tzinfo=UTC),
            )

    def test_a_404_reads_as_empty(self):
        """Which is what an uncompleted period returns: the 2026 daily file is
        a 404 in August 2026 while 2003 through 2025 are all there."""
        import io
        import urllib.error

        provider = dk.DukascopyProvider(scales={"EURUSD": 1e5})

        def gone(request, timeout=None):
            raise urllib.error.HTTPError(
                request.full_url, 404, "Not Found", {}, io.BytesIO(b"")
            )

        provider._opener = gone

        assert (
            provider.fetch_ohlcv(
                "EURUSD",
                Timeframe.D1,
                datetime(2024, 1, 1, tzinfo=UTC),
                datetime(2024, 2, 1, tzinfo=UTC),
            )
            == []
        )
        assert provider.missing_periods == ["EURUSD/2024/BID_candles_day_1.bi5"]
