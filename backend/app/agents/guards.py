"""Paper-cycle guards: currency correlation and loss memory. Advisory only.

Nothing here sends an order or overrides the Risk Brain. A hit means the paper
cycle should skip or shrink a new setup; it is not a live BLOCK.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

CORRELATED = (
    frozenset({"EURUSD", "GBPUSD", "EURGBP"}),
    frozenset({"AUDUSD", "NZDUSD", "AUDNZD"}),
    frozenset({"XAUUSD", "XAGUSD"}),
)
NON_USD_BASE_BLOCKS_SAME_BASE = True
LOOKBACK = timedelta(days=30)
MIN_SIMILAR_LOSSES = 3


def _sym(value: Any) -> str:
    s = str(value or "").upper().replace(".", "")
    if len(s) > 6 and s.endswith("M"):
        s = s[:-1]
    return s


def currencies(symbol: str) -> tuple[str, str]:
    s = _sym(symbol)
    if s.startswith(("XAU", "XAG")):
        quote = s[3:6] if len(s) >= 6 else "USD"
        return s[:3], quote or "USD"
    if len(s) >= 6:
        return s[:3], s[3:6]
    return s, ""


def correlated(symbol: str, open_symbols: list[str] | tuple[str, ...] | None) -> str | None:
    """Why `symbol` conflicts with an open book, or None if it does not.

    USD as a shared quote is not enough (almost every pair quotes USD). A
    shared non-USD currency, the same symbol, or a known high-correlation
    group is.
    """
    if not open_symbols:
        return None
    want = _sym(symbol)
    if not want:
        return None
    base, quote = currencies(want)
    for raw in open_symbols:
        held = _sym(raw)
        if not held:
            continue
        if held == want:
            return f"{want} already open"
        b, q = currencies(held)
        shared = {base, quote} & {b, q} - {"", "USD"}
        if shared:
            return f"shares {', '.join(sorted(shared))} with {held}"
        for group in CORRELATED:
            if want in group and held in group:
                return f"{want} is correlated with open {held}"
    return None


def similar_losses(setup: dict[str, Any], losses: list[dict[str, Any]],
                   *, now: datetime | None = None,
                   window: timedelta = LOOKBACK) -> list[dict[str, Any]]:
    now = now or datetime.now(UTC)
    start = now - window
    symbol = _sym(setup.get("symbol"))
    side = str(setup.get("direction") or "").upper()
    regime = str(setup.get("regime") or "")
    out = []
    for row in losses:
        when = row.get("at")
        if isinstance(when, str):
            try:
                when = datetime.fromisoformat(when)
            except ValueError:
                when = None
        if isinstance(when, datetime):
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            if when < start:
                continue
        if _sym(row.get("symbol")) != symbol:
            continue
        if str(row.get("direction") or "").upper() != side:
            continue
        lost_regime = str(row.get("regime") or "")
        if regime and lost_regime and lost_regime != regime:
            continue
        out.append(row)
    return out


def loss_factor(setup: dict[str, Any], losses: list[dict[str, Any]],
                *, now: datetime | None = None) -> float:
    """1.0 = no memory, down to 0.25 after many similar paper losses."""
    n = len(similar_losses(setup, losses, now=now))
    if n < MIN_SIMILAR_LOSSES:
        return 1.0
    return max(0.25, 1.0 - 0.25 * (n - MIN_SIMILAR_LOSSES + 1))


def decide_trigger(*, last_run: datetime | None, now: datetime,
                   newest_close: datetime | None = None,
                   last_price: float | None = None, last_close: float | None = None,
                   last_range: float | None = None,
                   max_interval: int = 900) -> str | None:
    """Why a cycle should run now, or None to wait. Event-driven with a cap."""
    if last_run is None:
        return "first"
    if (now - last_run).total_seconds() >= max_interval:
        return "max_interval"
    if newest_close is not None and newest_close > last_run:
        return "bar_close"
    if (last_price is not None and last_close is not None and last_range
            and last_range > 0 and abs(last_price - last_close) >= 0.5 * last_range):
        return "price_move"
    return None
