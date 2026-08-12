"""Demo dataset generator.

Produces a deterministic synthetic EURUSD H1 series containing *known* defects,
so the data-quality engine can be verified against ground truth rather than
merely executed. The seed is fixed: the same defects appear on every machine,
which is what makes the assertion in `tests/test_data_quality.py` meaningful.

Injected defects (all returned by `generate_csv` for the caller to assert on):

* a contiguous run of missing bars mid-week (not a weekend gap)
* a duplicated timestamp
* a single bar with an implausible range (outlier + price gap)
"""

from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

BASE_PRICE = 1.0850
# February 2024 deliberately: it contains none of the baseline FX holidays, so
# the only defects in the demo data are the ones injected on purpose. Starting
# on 1 January would emit bars on New Year's Day, which the calendar correctly
# rejects as trading while the market was shut.
START = datetime(2024, 2, 1, 0, 0, tzinfo=UTC)
BAR_COUNT = 720  # ~30 calendar days of H1; open slots are fewer (weekends)


@dataclass
class InjectedDefects:
    missing_from: datetime
    missing_count: int
    duplicated_at: datetime
    outlier_at: datetime

    def as_dict(self) -> dict[str, object]:
        return {
            "missing_from": self.missing_from.isoformat(),
            "missing_count": self.missing_count,
            "duplicated_at": self.duplicated_at.isoformat(),
            "outlier_at": self.outlier_at.isoformat(),
        }


def _walk(count: int, seed: int = 20240101) -> list[float]:
    """Mean-reverting random walk. Not a market model - just plausible shape."""
    rng = random.Random(seed)
    price = BASE_PRICE
    out: list[float] = []
    for i in range(count):
        drift = math.sin(i / 48.0) * 0.00008
        price += drift + rng.gauss(0, 0.00035)
        out.append(round(price, 5))
    return out


def generate_csv(root: Path, symbol: str = "EURUSD", timeframe: str = "H1") -> InjectedDefects:
    """Write the demo CSV and return the defects deliberately placed in it."""
    directory = Path(root) / symbol
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{timeframe}.csv"

    # Bars are emitted only when the market is actually open. Generating a
    # continuous 24/7 series for a forex pair would be fiction, and the
    # session-mismatch detector correctly rejects it - the demo data has to be
    # realistic enough that its *deliberate* defects are the only ones present.
    slots = _open_slots(symbol, timeframe)
    closes = _walk(len(slots))
    rng = random.Random(7)

    missing_start_index = 200
    missing_count = 5
    duplicate_index = 400
    outlier_index = 500

    rows: list[dict[str, str]] = []
    previous_close = closes[0]

    for i, (event_time, close) in enumerate(zip(slots, closes, strict=True)):
        if missing_start_index <= i < missing_start_index + missing_count:
            continue  # injected gap

        open_ = previous_close
        spread_hl = abs(rng.gauss(0, 0.0004)) + 0.0002
        high = max(open_, close) + spread_hl
        low = min(open_, close) - spread_hl
        volume = round(abs(rng.gauss(1500, 350)), 2)

        if i == outlier_index:
            # A single absurd bar: wide range and a large jump from the previous
            # close, which should trip both the outlier and price-gap detectors.
            close = round(close * 1.05, 5)
            high = round(close + 0.02, 5)
            low = round(open_ - 0.02, 5)

        row = {
            "time": event_time.isoformat().replace("+00:00", "Z"),
            "open": f"{open_:.5f}",
            "high": f"{high:.5f}",
            "low": f"{low:.5f}",
            "close": f"{close:.5f}",
            "volume": f"{volume:.2f}",
        }
        rows.append(row)

        if i == duplicate_index:
            rows.append(dict(row))  # injected duplicate timestamp

        previous_close = close

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["time", "open", "high", "low", "close", "volume"]
        )
        writer.writeheader()
        writer.writerows(rows)

    meta = directory / "meta.json"
    meta.write_text(
        '{"name": "Euro / US Dollar", "asset_class": "forex", '
        '"base_currency": "EUR", "quote_currency": "USD", "timezone": "Etc/UTC"}',
        encoding="utf-8",
    )

    return InjectedDefects(
        missing_from=slots[missing_start_index],
        missing_count=missing_count,
        duplicated_at=slots[duplicate_index],
        outlier_at=slots[outlier_index],
    )


def _open_slots(symbol: str, timeframe: str) -> list[datetime]:
    """Bar open-times when the market actually trades, over the demo window."""
    from app.core.enums import AssetClass, Timeframe
    from app.services.instruments import classify_symbol
    from app.services.sessions import (
        SessionCalendar,
        TradingWindow,
        default_hours,
    )

    asset_class, _, _ = classify_symbol(symbol.upper())
    if asset_class == AssetClass.OTHER:
        asset_class = AssetClass.FOREX
    hours, timezone = default_hours(asset_class)
    calendar = SessionCalendar(
        timezone=timezone, windows=[TradingWindow.parse(w) for w in hours]
    )
    start, end = demo_window()
    return calendar.expected_bar_times(start, end, Timeframe(timeframe))


def demo_window() -> tuple[datetime, datetime]:
    return START, START + timedelta(hours=BAR_COUNT + 1)
