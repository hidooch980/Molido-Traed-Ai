"""What the collector collects.

A watchlist entry binds a canonical instrument to the symbol a specific
provider uses for it. That mapping cannot be inferred: Yahoo calls EUR/USD
`EURUSD=X` and gold `GC=F`, and guessing would silently collect the wrong
instrument — the most expensive kind of data error, because the numbers look
perfectly plausible.

Configured through `MOLIDO_WATCHLIST`, one entry per comma:

    EURUSD:EURUSD=X:H1, XAUUSD:GC=F:H1, BTCUSD:BTC-USD:H1

    <canonical>:<provider symbol>:<timeframe>
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.enums import Timeframe
from app.core.errors import ConfigurationError

# The starting universe for the Yahoo adapter.
#
# **Its length is a correctness constraint rather than a preference.** The
# cross-section ranks instruments against each other and refuses to rank fewer
# than `crosssection.MIN_CROSS_SECTION` of them at one timestamp. A watchlist
# shorter than that floor therefore produces a deployment that collects bars
# faithfully forever and never learns one thing from them - and it does so
# quietly, because collection is genuinely healthy. This default listed four.
#
# The currency pairs carry the floor by themselves, which is why the list leans
# that way: they share a single 24/5 session, so they print on the same hours
# and are rankable at the same instant. Instruments on other calendars cannot
# be relied on for the floor - index futures settle, and if the majority of a
# universe is closed then the cross-section is not short of data, it is short
# of a market. Metals, energy and index futures add depth during their own
# hours; crypto is the only part of this list awake at the weekend.
#
# It is still small beside what a paid feed would allow, and deliberately: a
# collector that quietly hammers a free endpoint for five hundred symbols gets
# blocked, and a blocked feed looks exactly like a quiet market.
_DEFAULT_SYMBOLS = (
    # Currency majors
    ("EURUSD", "EURUSD=X"),
    ("GBPUSD", "GBPUSD=X"),
    ("USDJPY", "USDJPY=X"),
    ("USDCHF", "USDCHF=X"),
    ("AUDUSD", "AUDUSD=X"),
    ("USDCAD", "USDCAD=X"),
    ("NZDUSD", "NZDUSD=X"),
    # Currency crosses
    ("EURGBP", "EURGBP=X"),
    ("EURJPY", "EURJPY=X"),
    ("GBPJPY", "GBPJPY=X"),
    ("AUDJPY", "AUDJPY=X"),
    ("CHFJPY", "CHFJPY=X"),
    ("CADJPY", "CADJPY=X"),
    ("NZDJPY", "NZDJPY=X"),
    ("EURAUD", "EURAUD=X"),
    ("EURCHF", "EURCHF=X"),
    ("EURCAD", "EURCAD=X"),
    ("EURNZD", "EURNZD=X"),
    ("GBPAUD", "GBPAUD=X"),
    ("GBPCAD", "GBPCAD=X"),
    ("GBPCHF", "GBPCHF=X"),
    ("AUDCAD", "AUDCAD=X"),
    ("AUDCHF", "AUDCHF=X"),
    ("AUDNZD", "AUDNZD=X"),
    ("NZDCAD", "NZDCAD=X"),
    ("NZDCHF", "NZDCHF=X"),
    ("CADCHF", "CADCHF=X"),
    # Metals and energy, as continuous futures
    ("XAUUSD", "GC=F"),
    ("XAGUSD", "SI=F"),
    ("XPTUSD", "PL=F"),
    ("USOIL", "CL=F"),
    ("UKOIL", "BZ=F"),
    ("NGAS", "NG=F"),
    ("COPPER", "HG=F"),
    # Index futures
    ("US500", "ES=F"),
    ("US100", "NQ=F"),
    ("US30", "YM=F"),
    ("US2000", "RTY=F"),
    # Crypto
    ("BTCUSD", "BTC-USD"),
    ("ETHUSD", "ETH-USD"),
    ("SOLUSD", "SOL-USD"),
    ("XRPUSD", "XRP-USD"),
)

#: The timeframes the fast subset is collected on, and why there is a fast
#: subset at all.
#:
#: The forward measurement needs about 6,573 independent instants to separate
#: this edge from noise. On hourly bars that is roughly a year; on five-minute
#: bars about a month; on one-minute bars about a week. Collecting only H1 made
#: the wait a year for no reason other than that nothing else was fetched.
#:
#: **Only the currency pairs, and deliberately.** The cross-section needs
#: twenty instruments sharing one timestamp, the pairs carry that floor on
#: their own, and a free endpoint asked for forty-two symbols across four
#: timeframes every cycle is a blocked endpoint - which looks exactly like a
#: quiet market.
#:
#: The faster answer is not a free one, and the docstring on
#: `forward_timeframes` states the other half: spread is constant while bar
#: range falls with the square root of time, so the same 1.4 pips is 16% of an
#: hourly bar and near 58% of a five-minute one. Faster answers, dearer
#: trades. The measurement is net of costs, which is exactly why it is allowed
#: to settle that rather than either of us arguing it.
_FAST_TIMEFRAMES = ("M15", "M5", "M1")

_CURRENCY_PAIRS = tuple(
    (sym, raw) for sym, raw in _DEFAULT_SYMBOLS if raw.endswith("=X")
)

DEFAULT_WATCHLIST = ",".join(
    [f"{sym}:{raw}:H1" for sym, raw in _DEFAULT_SYMBOLS]
    + [
        f"{sym}:{raw}:{tf}"
        for tf in _FAST_TIMEFRAMES
        for sym, raw in _CURRENCY_PAIRS
    ]
)


@dataclass(frozen=True)
class WatchEntry:
    symbol: str  # canonical, e.g. EURUSD
    raw_symbol: str  # provider-specific, e.g. EURUSD=X
    timeframe: Timeframe

    @property
    def key(self) -> str:
        return f"{self.symbol}:{self.timeframe.value}"


def parse_watchlist(raw: str) -> list[WatchEntry]:
    entries: list[WatchEntry] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split(":")
        if len(parts) != 3:
            raise ConfigurationError(
                "Watchlist entries must be <canonical>:<provider symbol>:<timeframe>",
                entry=chunk,
            )
        symbol, raw_symbol, timeframe = (p.strip() for p in parts)
        try:
            tf = Timeframe(timeframe.upper())
        except ValueError as exc:
            raise ConfigurationError(
                f"Unknown timeframe {timeframe!r} in watchlist entry", entry=chunk
            ) from exc
        entries.append(
            WatchEntry(symbol=symbol.upper(), raw_symbol=raw_symbol, timeframe=tf)
        )

    # An empty universe is a misconfiguration, never a choice. The compose file
    # passes `MOLIDO_WATCHLIST: ${MOLIDO_WATCHLIST}`, and an unset variable
    # arrives here as an empty string rather than as an absent setting - so the
    # application default never gets a chance to apply, and returning `[]` here
    # would start a collector that sweeps nothing, reports `entries: 0` with no
    # failures, and looks entirely healthy while gathering no market data at
    # all. Refusing is the only outcome that is visible.
    if not entries:
        raise ConfigurationError(
            "The watchlist is empty, so the collector would gather nothing. "
            "Set MOLIDO_WATCHLIST, or leave it out entirely to take the "
            "built-in universe - an empty value is not the same as no value.",
            entry=raw,
        )

    return entries
