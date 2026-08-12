"""Offline CSV/Parquet-free provider.

Exists so the whole pipeline - ingestion, quality detection, point-in-time
reads, tests - runs with no network and no paid API key. It is also the fixture
mechanism for the demo seed and for regression tests that need deliberately
corrupted data.

Directory layout:

    <root>/<RAW_SYMBOL>/<TIMEFRAME>.csv

CSV header (extra columns are ignored):

    time,open,high,low,close,volume[,tick_volume,spread]

`time` is parsed as UTC. Rows are returned as-is, including malformed ones -
detecting problems is the quality engine's job, not the adapter's.
"""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from app.core.enums import AssetClass, Timeframe
from app.core.errors import ProviderError
from app.providers.base import ProviderCapabilities, ProviderSymbol, RawBar


def _parse_time(value: str) -> datetime:
    raw = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ProviderError(f"Unparseable timestamp: {value!r}") from exc
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _parse_float(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise ProviderError(f"Unparseable number: {value!r}") from exc


class CsvProvider:
    """Reads bars from a local directory tree."""

    code = "csv"
    name = "Local CSV files"

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    # ------------------------------------------------------------ interface
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            ohlcv=True,
            ticks=False,
            supported_timeframes=tuple(Timeframe),
            max_bars_per_request=None,
            requests_per_minute=None,
        )

    def list_symbols(self) -> list[ProviderSymbol]:
        if not self.root.exists():
            return []
        symbols: list[ProviderSymbol] = []
        for entry in sorted(self.root.iterdir()):
            if not entry.is_dir():
                continue
            meta_path = entry / "meta.json"
            meta: dict = {}
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            symbols.append(
                ProviderSymbol(
                    raw_symbol=entry.name,
                    name=meta.get("name", entry.name),
                    asset_class=AssetClass(meta.get("asset_class", AssetClass.OTHER.value)),
                    base_currency=meta.get("base_currency"),
                    quote_currency=meta.get("quote_currency"),
                    exchange=meta.get("exchange"),
                    timezone=meta.get("timezone", "Etc/UTC"),
                    metadata=meta,
                )
            )
        return symbols

    def fetch_ohlcv(
        self,
        raw_symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[RawBar]:
        path = self.root / raw_symbol / f"{timeframe.value}.csv"
        if not path.exists():
            raise ProviderError(
                f"No CSV data for {raw_symbol} {timeframe.value}",
                path=str(path),
            )

        bars: list[RawBar] = []
        with path.open("r", encoding="utf-8", newline="") as handle:
            for line_no, row in enumerate(csv.DictReader(handle), start=2):
                if not row.get("time"):
                    continue
                event_time = _parse_time(row["time"])
                if event_time < start or event_time >= end:
                    continue
                bars.append(
                    RawBar(
                        event_time=event_time,
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=_parse_float(row.get("volume")),
                        tick_volume=_parse_float(row.get("tick_volume")),
                        spread=_parse_float(row.get("spread")),
                        source_ref=f"{path.name}:{line_no}",
                    )
                )
        # Deliberately not sorted or deduplicated: out-of-order and duplicate
        # rows are real provider defects, and the quality engine must see them.
        return bars

    def health_check(self) -> bool:
        return self.root.exists()
