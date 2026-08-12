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

# Sensible starting universe for the Yahoo adapter. Deliberately small: a
# collector that quietly hammers a free endpoint for 500 symbols gets blocked,
# and a blocked feed looks exactly like a quiet market.
DEFAULT_WATCHLIST = "EURUSD:EURUSD=X:H1,GBPUSD:GBPUSD=X:H1,XAUUSD:GC=F:H1,BTCUSD:BTC-USD:H1"


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
    return entries
