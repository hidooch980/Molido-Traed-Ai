"""Dukascopy: twenty years of bank-feed history, free, no key.

This exists because of what the forward measurement costs. The rule needs about
6,573 instants to answer at 80% power - roughly a year of hourly bars. A second
out-of-sample historical test costs hours and has already been decisive once:
re-run on eleven years of daily bars the rule scored -0.0015 R at t = -0.12.
Another independent sample can kill or support the claim long before the
forward series is old enough to speak.

It is a different kind of source from the two already here. Yahoo is a
consensus of consensuses with two years of intraday depth; the broker is where
the account fills, with three weeks. Dukascopy is a bank's own book going back
to 2003. None of them is the truth, and the disagreements between them are
information rather than noise.

The wire format is undocumented, so every field below was read off the live
endpoint rather than taken from memory, and each of these would have been a
silent wrong-price bug:

  **The order is open, close, low, high.** Not OHLC. Unpacking it as OHLC
  yields bars whose "high" is sometimes below their "low", which most
  indicator code will happily average into a plausible-looking number.

  **Prices are big-endian integers, scaled per instrument.** EURUSD is 1e5 and
  gold is 1e3. Applying the wrong one puts gold at 20.63 instead of 2063.63 -
  a number no test asserts against and every ATR silently believes.

  **Times are seconds from the file's period start**, and the month in the URL
  is zero-indexed. January is `00`. A one-month shift produces a series that
  looks entirely normal and is wrong everywhere.

  **An empty response means the market was closed**, not that the fetch
  failed. Weekends are zero-length bodies, and treating them as errors makes
  every backfill look broken.

  **The aggregated files appear only for completed periods.** The 2026 daily
  file is a 404 in August 2026 while every year from 2003 to 2025 is there,
  and this month's hourly file is missing while last month's holds its full
  744 records. So this is a history source, not a live feed - asking it for
  today returns nothing, which is not the same as today having no bars.

**The feed throttles, and it throttles into a shape that looks like data.** A
dry run of twenty-eight symbols got fifteen answers and then thirteen
consecutive 503s - not scattered, but every request after the fifteenth. A 503
raises, the symbol is skipped, and the backfill finishes reporting fifteen
imported instruments. Fifteen is below the minimum cross-section of twenty, so
the measurement built on it would refuse to run at all; had the cut landed at
twenty-two instead, it would have run happily on a universe chosen by whichever
symbols the feed answered first. So requests are paced and throttled responses
are retried with backoff, and a 404 is never retried because a 404 is an
answer.

A period that comes back empty is *recorded by name*, not skipped in silence.
Weekends are empty legitimately, but so is a year the feed has a gap in, and a
backfill that returns fewer bars without saying which periods it could not read
produces a history with holes that nothing downstream can distinguish from a
market that was closed.

The scale is *verified against a price already known*, never taken from the
table alone. The table is a fast path; a scale that silently stops matching
when Dukascopy adds an instrument is exactly the failure this module is most
exposed to, and importing ten years of hundredfold-wrong prices would poison
every measurement downstream at once.
"""

from __future__ import annotations

import calendar
import lzma
import struct
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.enums import AssetClass, Timeframe
from app.core.errors import ProviderError
from app.providers.base import (
    ProviderCapabilities,
    ProviderSymbol,
    RawBar,
)

FEED = "https://datafeed.dukascopy.com/datafeed"

#: One candle: seconds-offset, open, close, low, high, volume.
#:
#: Five big-endian uint32 then a float32. The middle four are *not* in OHLC
#: order - read the module docstring before changing this.
CANDLE = struct.Struct(">5If")
CANDLE_SIZE = CANDLE.size  # 24

#: One tick: milliseconds-offset, ask, bid, ask volume, bid volume.
TICK = struct.Struct(">3I2f")
TICK_SIZE = TICK.size  # 20

#: Candidate price scales, most common first. A candidate list rather than a
#: lookup, because the scale is chosen by matching a reference price and the
#: list only says which values are worth trying.
SCALES: tuple[float, ...] = (1e5, 1e3, 1e2, 1e4, 1e6)

#: How far a scaled price may sit from the reference before the scale is
#: rejected. Generous on purpose: the reference may be hours away and from a
#: different venue, and the failure being caught is a factor of a hundred, not
#: a few pips.
SCALE_TOLERANCE = 0.25

#: Seconds between requests. Not politeness for its own sake: the feed answered
#: fifteen rapid requests and then 503'd thirteen in a row, and the failure
#: silently selects a universe by arrival order.
MIN_INTERVAL = 0.6

#: Attempts before giving up on a throttled or transient response.
MAX_ATTEMPTS = 4

#: Worth retrying. 404 is deliberately absent - it means the feed does not hold
#: that period, which is an answer rather than a failure, and retrying it four
#: times over twenty years would quadruple every weekend.
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})

#: The earliest history the feed serves. Instruments start at different dates;
#: this is the floor for the oldest of them.
HISTORY_START = datetime(2003, 5, 5, tzinfo=UTC)


def infer_scale(raw: int, reference: float) -> float:
    """Pick the price scale by matching a price already known to be right.

    Raises rather than guessing. A wrong scale does not produce an error
    anywhere downstream - it produces gold at 20.63, which every moving average
    and every ATR will accept without complaint, and which no assertion in this
    project currently catches.
    """
    if raw <= 0:
        raise ProviderError("cannot infer a price scale from a non-positive value")
    if reference <= 0:
        raise ProviderError(
            "cannot infer a price scale without a reference price that is "
            "already known to be right - guessing here imports ten years of "
            "wrong prices that look entirely plausible"
        )

    for scale in SCALES:
        if abs(raw / scale - reference) / reference <= SCALE_TOLERANCE:
            return scale

    raise ProviderError(
        f"no candidate scale puts {raw} within {SCALE_TOLERANCE:.0%} of the "
        f"reference {reference}. Tried {SCALES}. Refusing rather than picking "
        "the closest: an instrument this feed prices differently from every "
        "other is exactly the one worth stopping on"
    )


def _safe(symbol: str) -> str:
    """Refuse anything that is not a plain instrument name.

    The symbol lands inside a URL path. Without this, a name carrying a slash
    or a scheme reaches urlopen and the fetch becomes whatever that name says -
    including a local file. Instrument names arrive from the database, which is
    exactly the kind of "trusted" input that stops being trusted the day
    somebody adds a row by hand.
    """
    if not symbol.isalnum() or not (2 <= len(symbol) <= 16):
        raise ProviderError(
            f"{symbol!r} is not a plain instrument name, and this one goes "
            "into a URL path"
        )
    return symbol


def _url(symbol: str, timeframe: Timeframe, moment: datetime) -> str:
    """Where this feed keeps that period.

    The month is zero-indexed in the path - January is `00`. This is the single
    most common way to read this feed wrong, and it produces a series that is
    shifted by a month and looks completely normal.
    """
    symbol = _safe(symbol)
    year, month, day = moment.year, moment.month - 1, moment.day
    if timeframe is Timeframe.D1:
        return f"{FEED}/{symbol}/{year}/BID_candles_day_1.bi5"
    if timeframe is Timeframe.H1:
        return f"{FEED}/{symbol}/{year}/{month:02d}/BID_candles_hour_1.bi5"
    if timeframe is Timeframe.M1:
        return f"{FEED}/{symbol}/{year}/{month:02d}/{day:02d}/BID_candles_min_1.bi5"
    raise ProviderError(
        f"this feed publishes day, hour and minute candles; {timeframe.value} "
        "would have to be built from one of those rather than fetched"
    )


def _period_start(timeframe: Timeframe, moment: datetime) -> datetime:
    """The instant the file's offsets are counted from."""
    if timeframe is Timeframe.D1:
        return datetime(moment.year, 1, 1, tzinfo=UTC)
    if timeframe is Timeframe.H1:
        return datetime(moment.year, moment.month, 1, tzinfo=UTC)
    return datetime(moment.year, moment.month, moment.day, tzinfo=UTC)


def decode_candles(
    body: bytes, *, period_start: datetime, scale: float
) -> list[RawBar]:
    """Turn one decompressed file into bars.

    A trailing partial record raises rather than being dropped. A file that
    does not divide evenly is a file being read with the wrong record size, and
    silently discarding the remainder would hide that while returning bars that
    are all subtly misaligned.
    """
    if len(body) % CANDLE_SIZE:
        raise ProviderError(
            f"{len(body)} bytes is not a whole number of {CANDLE_SIZE}-byte "
            "candles, which means this is being read with the wrong record "
            "size and every bar in it is misaligned"
        )

    bars: list[RawBar] = []
    for offset in range(0, len(body), CANDLE_SIZE):
        seconds, open_, close, low, high, volume = CANDLE.unpack_from(body, offset)
        if not open_:
            # A zero-price record is a period the feed has no book for, not a
            # bar at zero. Dropping it is right; scaling it would put a price
            # of 0.0 into a mean.
            continue
        bars.append(
            RawBar(
                event_time=period_start + timedelta(seconds=seconds),
                open=open_ / scale,
                # Middle two are close and low, in that order. Read the module
                # docstring before "fixing" this to look like OHLC.
                high=high / scale,
                low=low / scale,
                close=close / scale,
                tick_volume=float(volume),
                source_ref="dukascopy",
            )
        )
    return bars


def decode_ticks(body: bytes, *, hour_start: datetime, scale: float) -> list[dict]:
    """Turn one hour of ticks into ask/bid rows. Ask comes first on the wire."""
    if len(body) % TICK_SIZE:
        raise ProviderError(
            f"{len(body)} bytes is not a whole number of {TICK_SIZE}-byte ticks"
        )
    rows = []
    for offset in range(0, len(body), TICK_SIZE):
        millis, ask, bid, ask_volume, bid_volume = TICK.unpack_from(body, offset)
        rows.append(
            {
                "event_time": hour_start + timedelta(milliseconds=millis),
                "ask": ask / scale,
                "bid": bid / scale,
                "ask_volume": ask_volume,
                "bid_volume": bid_volume,
            }
        )
    return rows


class DukascopyProvider:
    """Bank-feed history, read straight off the public endpoint."""

    code = "dukascopy"
    name = "Dukascopy Bank"

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        opener: object | None = None,
        scales: dict[str, float] | None = None,
        min_interval: float = MIN_INTERVAL,
        max_attempts: int = MAX_ATTEMPTS,
        sleep: Any = None,
    ) -> None:
        self._timeout = timeout
        self._opener = opener
        self._min_interval = min_interval
        self._max_attempts = max_attempts
        self._sleep = sleep or time.sleep
        self._last_request = 0.0
        #: How often the feed asked us to slow down. Published rather than
        #: absorbed: a run that retried four hundred times succeeded, and that
        #: is worth knowing before the next one is scheduled.
        self.throttled = 0
        # Verified scales, per symbol. Populated by `verify_scale` and empty
        # until then - an unverified symbol is refused rather than imported on
        # a guess.
        self._scales: dict[str, float] = dict(scales or {})
        #: Periods the last fetch could not read. Weekends land here too, so
        #: this is evidence rather than a verdict - but a backfill that
        #: silently returns fewer bars leaves a history with holes nothing
        #: downstream can tell apart from a closed market.
        self.missing_periods: list[str] = []

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            ohlcv=True,
            ticks=True,
            supported_timeframes=(Timeframe.M1, Timeframe.H1, Timeframe.D1),
            history_start=HISTORY_START,
            # One file per period, so the natural request size is the file.
            max_days_per_request={
                Timeframe.D1: 366,
                Timeframe.H1: 31,
                Timeframe.M1: 1,
            },
        )

    def list_symbols(self) -> list[ProviderSymbol]:
        """The feed publishes no machine-readable catalogue.

        Returning an empty list rather than a hardcoded one: a list written
        here would drift from what the endpoint actually serves, and a symbol
        that 404s is discovered by asking for it. USDCAD already answers 404 on
        the daily path that every other major answers.
        """
        return []

    def verify_scale(self, symbol: str, reference: float, *, at: datetime) -> float:
        """Establish this symbol's price scale against a price already known.

        Called before any backfill. The scale is not read from a table, because
        a table cannot notice when it stops being right, and the consequence
        here is ten years of hundredfold-wrong prices that look plausible in
        every chart and every statistic computed from them.
        """
        body = self._fetch(_url(symbol, Timeframe.D1, at))
        if not body:
            raise ProviderError(
                f"the feed served nothing for {symbol} at {at.date()}, so its "
                "price scale cannot be established and it must not be imported"
            )
        first = next(
            (
                CANDLE.unpack_from(body, offset)[1]
                for offset in range(0, len(body), CANDLE_SIZE)
                if CANDLE.unpack_from(body, offset)[1]
            ),
            0,
        )
        scale = infer_scale(first, reference)
        self._scales[symbol] = scale
        return scale

    def fetch_ohlcv(
        self,
        raw_symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[RawBar]:
        """Bars with start <= event_time < end, ascending, UTC."""
        scale = self._scales.get(raw_symbol)
        if scale is None:
            raise ProviderError(
                f"{raw_symbol} has no verified price scale. Call verify_scale "
                "with a price known to be right first - importing on an "
                "assumed scale is how gold arrives at 20.63 and nothing "
                "downstream notices"
            )

        bars: list[RawBar] = []
        self.missing_periods = []
        for moment in self._periods(timeframe, start, end):
            url = _url(raw_symbol, timeframe, moment)
            body = self._fetch(url)
            if not body:
                # Empty is the market being closed, or a period this feed has
                # not aggregated yet - never a failure, because raising here
                # would make every backfill spanning a Saturday look broken.
                # Named rather than dropped: see the module docstring.
                self.missing_periods.append(url.rsplit("/datafeed/", 1)[-1])
                continue
            bars.extend(
                decode_candles(
                    body,
                    period_start=_period_start(timeframe, moment),
                    scale=scale,
                )
            )

        return sorted(
            (b for b in bars if start <= b.event_time < end),
            key=lambda b: b.event_time,
        )

    def health_check(self) -> bool:
        try:
            return self._fetch(_url("EURUSD", Timeframe.D1, HISTORY_START)) is not None
        except ProviderError:
            return False

    @staticmethod
    def _periods(
        timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[datetime]:
        """One entry per file that could hold something in the window."""
        moments: list[datetime] = []
        if timeframe is Timeframe.D1:
            for year in range(start.year, end.year + 1):
                moments.append(datetime(year, 1, 1, tzinfo=UTC))
            return moments

        cursor = datetime(start.year, start.month, 1, tzinfo=UTC)
        if timeframe is Timeframe.M1:
            cursor = datetime(start.year, start.month, start.day, tzinfo=UTC)
        while cursor < end:
            moments.append(cursor)
            if timeframe is Timeframe.M1:
                cursor += timedelta(days=1)
            else:
                days = calendar.monthrange(cursor.year, cursor.month)[1]
                cursor += timedelta(days=days)
        return moments

    def _pace(self) -> None:
        """Wait out the minimum interval since the last request."""
        if self._min_interval <= 0:
            return
        waited = time.monotonic() - self._last_request
        if waited < self._min_interval:
            self._sleep(self._min_interval - waited)
        self._last_request = time.monotonic()

    def _fetch(self, url: str) -> bytes:
        if not url.startswith(FEED + "/"):
            # Belt and braces with `_safe`. Everything reaching here is built
            # by `_url`, and this is what makes that a checked fact rather
            # than a convention.
            raise ProviderError(f"refusing to fetch {url!r}: not this feed")

        raw = self._read(url)
        if not raw:
            return b""
        try:
            return lzma.LZMADecompressor().decompress(raw)
        except lzma.LZMAError as problem:
            raise ProviderError(
                f"{url} did not decompress: {problem}. A body that is not LZMA "
                "is usually an error page served with a 200",
                url=url,
            ) from problem

    def _read(self, url: str) -> bytes:
        """One request, paced, retried on a throttle, never retried on a 404.

        The backoff doubles. A feed that answered fifteen requests and then
        refused thirteen wants a pause, not the same rate with more attempts.
        """
        request = urllib.request.Request(  # noqa: S310 - scheme fixed by FEED
            url, headers={"User-Agent": "molido/1.0 (research backfill)"}
        )
        opener = self._opener or urllib.request.urlopen
        delay = self._min_interval or 0.5
        last: Exception | None = None

        for attempt in range(self._max_attempts):
            self._pace()
            try:
                with opener(request, timeout=self._timeout) as response:  # type: ignore[operator]
                    return bytes(response.read())
            except urllib.error.HTTPError as problem:
                if problem.code == 404:
                    # A period the feed does not hold. An answer, not a
                    # failure - and retrying it would quadruple every weekend
                    # across twenty years.
                    return b""
                if problem.code not in RETRY_STATUS:
                    raise ProviderError(
                        f"{url} answered {problem.code}", url=url, status=problem.code
                    ) from problem
                last = problem
            except OSError as problem:
                # Timeouts and reset connections. Retried for the same reason
                # a 503 is: the alternative is a series whose holes were
                # decided by the network.
                last = problem

            self.throttled += 1
            if attempt < self._max_attempts - 1:
                self._sleep(delay)
                delay *= 2

        raise ProviderError(
            f"{url} still failing after {self._max_attempts} attempts: {last}. "
            "Reported rather than skipped: a symbol dropped here is a symbol "
            "missing from the cross-section, and a cross-section chosen by "
            "which requests happened to succeed is not the tested universe",
            url=url,
        )


def default_asset_class(symbol: str) -> AssetClass:
    """A coarse guess, used only for labelling a newly created instrument."""
    if symbol.startswith(("XAU", "XAG", "XPT", "XPD")):
        return AssetClass.COMMODITY
    if len(symbol) == 6 and symbol.isalpha():
        return AssetClass.FOREX
    return AssetClass.OTHER
