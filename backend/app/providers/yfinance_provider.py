"""Yahoo Finance adapter.

One real network adapter, included to prove the provider interface is not
shaped around the offline CSV case. `yfinance` is an optional dependency
(`pip install -e ".[providers]"`); importing this module without it raises a
clear ProviderError rather than an ImportError at some distant call site.

Yahoo's intraday history is short and its data is not tick-accurate. It is fine
for development and for daily bars; it is not a production execution feed, and
the trust_weight assigned to it in the provider registry reflects that.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.enums import AssetClass, Timeframe
from app.core.errors import ProviderError
from app.providers.base import ProviderCapabilities, ProviderSymbol, RawBar

# Yahoo's per-request history limits. Sub-hourly data is capped hard; daily
# and above are effectively unlimited, so those are left out and fall back to
# the caller's default.
_MAX_DAYS: dict[Timeframe, int] = {
    Timeframe.M1: 7,
    Timeframe.M5: 55,
    Timeframe.M15: 55,
    Timeframe.M30: 55,
    Timeframe.H1: 700,
    Timeframe.H4: 700,
}

_INTERVALS: dict[Timeframe, str] = {
    Timeframe.M1: "1m",
    Timeframe.M5: "5m",
    Timeframe.M15: "15m",
    Timeframe.M30: "30m",
    Timeframe.H1: "1h",
    Timeframe.D1: "1d",
    Timeframe.W1: "1wk",
    Timeframe.MN1: "1mo",
}


class YFinanceProvider:
    code = "yfinance"
    name = "Yahoo Finance"

    def __init__(self, symbols: dict[str, ProviderSymbol] | None = None) -> None:
        # Yahoo has no listable universe for our purposes; the operator
        # configures which tickers this adapter is allowed to serve.
        self._symbols = symbols or {}

    def _yf(self):
        try:
            import yfinance  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - depends on extras
            raise ProviderError(
                "yfinance is not installed. Install with: pip install -e '.[providers]'"
            ) from exc
        return yfinance

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            ohlcv=True,
            ticks=False,
            supported_timeframes=tuple(_INTERVALS),
            max_bars_per_request=None,
            requests_per_minute=60,
            # Yahoo's documented per-request ranges. Chunking tighter than
            # these multiplies request count for nothing — a 680-day hourly
            # backfill split into 30-day pieces is 23 calls where 2 suffice,
            # and with dozens of symbols that is the difference between a
            # working collector and a rate-limited one.
            max_days_per_request=_MAX_DAYS,
        )

    def register_symbol(self, raw_symbol: str, **kwargs) -> None:
        self._symbols[raw_symbol] = ProviderSymbol(
            raw_symbol=raw_symbol,
            name=kwargs.get("name", raw_symbol),
            asset_class=kwargs.get("asset_class", AssetClass.OTHER),
            base_currency=kwargs.get("base_currency"),
            quote_currency=kwargs.get("quote_currency"),
            exchange=kwargs.get("exchange"),
            timezone=kwargs.get("timezone", "Etc/UTC"),
        )

    def list_symbols(self) -> list[ProviderSymbol]:
        return list(self._symbols.values())

    def fetch_ohlcv(
        self,
        raw_symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[RawBar]:
        interval = _INTERVALS.get(timeframe)
        if interval is None:
            raise ProviderError(
                f"{self.code} does not support timeframe {timeframe.value}",
                timeframe=timeframe.value,
            )

        yf = self._yf()
        try:
            frame = yf.Ticker(raw_symbol).history(
                start=start,
                end=end,
                interval=interval,
                auto_adjust=False,
                actions=False,
            )
        except Exception as exc:  # noqa: BLE001 - adapter boundary
            raise ProviderError(f"yfinance request failed for {raw_symbol}: {exc}") from exc

        if frame is None or frame.empty:
            return []

        bars: list[RawBar] = []
        for index, row in frame.iterrows():
            event_time = index.to_pydatetime()
            event_time = (
                event_time.replace(tzinfo=UTC)
                if event_time.tzinfo is None
                else event_time.astimezone(UTC)
            )
            volume = row.get("Volume")
            bars.append(
                RawBar(
                    event_time=event_time,
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=float(volume) if volume is not None else None,
                    source_ref=f"yfinance:{raw_symbol}:{interval}",
                )
            )
        return bars

    def health_check(self) -> bool:
        try:
            self._yf()
        except ProviderError:
            return False
        return True
