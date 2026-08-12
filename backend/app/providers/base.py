"""Market-data provider interface.

Adapters must be replaceable (spec §4). Everything downstream depends on this
protocol, never on a concrete provider. An adapter returns *raw* rows; it does
not validate, normalize or persist - that is the ingestion pipeline's job, and
keeping the split sharp is what lets us swap a paid feed for a file without
touching the rest of the system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from app.core.enums import AssetClass, Timeframe


@dataclass(frozen=True)
class ProviderCapabilities:
    ohlcv: bool = True
    ticks: bool = False
    depth: bool = False
    news: bool = False
    economic_calendar: bool = False
    supported_timeframes: tuple[Timeframe, ...] = ()
    # Earliest history the provider can serve, when it declares one.
    history_start: datetime | None = None
    max_bars_per_request: int | None = None
    requests_per_minute: int | None = None
    # Largest window the provider will answer in one call, per timeframe.
    # Feeds cap intraday requests far more tightly than daily ones, and a
    # single global chunk size either wastes calls on daily data or exceeds
    # the limit on minute data. The provider knows its own constraint, so it
    # declares it and ingestion honours it.
    max_days_per_request: dict[Timeframe, int] = field(default_factory=dict)

    def chunk_days(self, timeframe: Timeframe, default: int) -> int:
        return self.max_days_per_request.get(timeframe, default)

    def as_dict(self) -> dict[str, object]:
        return {
            "ohlcv": self.ohlcv,
            "ticks": self.ticks,
            "depth": self.depth,
            "news": self.news,
            "economic_calendar": self.economic_calendar,
            "supported_timeframes": [tf.value for tf in self.supported_timeframes],
            "history_start": self.history_start.isoformat() if self.history_start else None,
            "max_bars_per_request": self.max_bars_per_request,
            "requests_per_minute": self.requests_per_minute,
            "max_days_per_request": {
                tf.value: days for tf, days in self.max_days_per_request.items()
            },
        }


@dataclass(frozen=True)
class ProviderSymbol:
    """A symbol as the provider names it, plus whatever metadata it exposes."""

    raw_symbol: str
    name: str = ""
    asset_class: AssetClass = AssetClass.OTHER
    base_currency: str | None = None
    quote_currency: str | None = None
    exchange: str | None = None
    timezone: str = "Etc/UTC"
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RawBar:
    """One bar exactly as the provider reported it.

    `event_time` must be the bar's *open* time in UTC. Providers that report
    close time are converted in their adapter, not downstream - a mixed
    convention here is a silent one-bar lookahead.
    """

    event_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    tick_volume: float | None = None
    spread: float | None = None
    source_ref: str | None = None


@runtime_checkable
class MarketDataProvider(Protocol):
    """Contract every market-data adapter implements."""

    code: str
    name: str

    def capabilities(self) -> ProviderCapabilities: ...

    def list_symbols(self) -> list[ProviderSymbol]: ...

    def fetch_ohlcv(
        self,
        raw_symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[RawBar]:
        """Return bars with `start <= event_time < end`, ascending, UTC.

        Implementations raise `ProviderError` (or `RateLimitedError`) on
        failure and must never return partial data silently marked as complete.
        """
        ...

    def health_check(self) -> bool: ...
