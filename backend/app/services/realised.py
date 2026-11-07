"""Realised profit, read from the deals the terminal closed.

The one figure the platform could not compute. Positions publish their floating
profit every cycle, but a closed trade leaves the positions file entirely and
nothing recorded where it went - so an account could be up four hundred dollars
on the day and every page would show only what was still open.

Deals rather than orders. An order is a request; a deal is what the account was
actually charged or paid, which is what a P&L is made of.

The numeric `net` field preserves the publisher's subtotal for compatibility.
Legacy exporters include profit, swap and commission but omit DEAL_FEE. Fee
availability is reported separately; absent fees are unknown, not zero. Even
when fees exist, this file alone does not prove complete account history.

Entry charges remain in the monetary totals and event details, but are not
closed deals and must not inflate trade counts or the exit-event hit rate.
A partial exit is still one exit event, not necessarily a completed position.

Absent is not zero. Until the expert publishes the file - it needs a recompile
and a terminal restart, which is a thing to do on a closed market - this
reports that the history is not being published rather than reporting that
nothing has been closed. Those are very different facts and only one of them is
about trading.
"""

from __future__ import annotations

import json
import math
import pathlib
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from app.providers.metatrader import bridge_dir_for

DEALS_FILE = "molido_deals.json"

#: The terminal writes `2026.08.17 08:02:27` on its own clock, which is not
#: UTC - measured at +3 on this broker. The offset is applied by the caller
#: that knows it; this module keeps the timestamps as published and says so.
STAMP_FORMAT = "%Y.%m.%d %H:%M:%S"


def _parse(stamp: str, *, offset_hours: float) -> datetime | None:
    try:
        naive = datetime.strptime(stamp.strip(), STAMP_FORMAT)
    except (ValueError, AttributeError):
        return None
    return naive.replace(tzinfo=UTC) - timedelta(hours=offset_hours)


def _fee(value: Any) -> float | None:
    """Only an explicitly published finite number establishes a fee value."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def read(
    *,
    directory: pathlib.Path | str | None = None,
    account_key: str | None = None,
    offset_hours: float = 0.0,
    since: datetime | None = None,
) -> dict[str, Any]:
    """Every closed deal the bridge has published, and what they add up to.

    One of `directory` or `account_key` says whose deals these are. An explicit
    directory wins, because a caller that already knows the path has usually
    been handed it by something that resolved it once already.

    With neither, this reads the single terminal this deployment has always
    run. Once more than one account is configured `bridge_dir_for` raises
    rather than picking, because a P&L attributed to the wrong account is a
    number that looks entirely real.
    """
    if directory is not None:
        root = pathlib.Path(directory)
    else:
        root = pathlib.Path(bridge_dir_for(account_key))
    path = root / DEALS_FILE

    if not path.exists():
        # Stated, not returned as an empty list. An account with no closed
        # trades and an expert that is not publishing them look identical in a
        # zero, and only one of them is about trading.
        return {
            "available": False,
            "reason": (
                "the terminal is not publishing closed deals yet. The expert "
                "needs a recompile and a restart for that, which is a thing to "
                "do on a closed market - not a statement that nothing has been "
                "closed"
            ),
            "deals": [],
            "by_symbol": [],
            "net": None,
        }

    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as problem:
        return {
            "available": False,
            "reason": f"the deal file could not be read: {problem}",
            "deals": [],
            "by_symbol": [],
            "net": None,
        }

    deals: list[dict[str, Any]] = []
    for row in body.get("deals") or []:
        closed_at = _parse(str(row.get("closed_at") or ""), offset_hours=offset_hours)
        if since is not None and (closed_at is None or closed_at < since):
            continue
        deals.append(
            {
                "ticket": row.get("ticket"),
                "symbol": row.get("symbol"),
                "side": row.get("side"),
                "volume": row.get("volume"),
                "price": row.get("price"),
                "profit": row.get("profit"),
                "swap": row.get("swap"),
                "commission": row.get("commission"),
                "fee": _fee(row.get("fee")),
                "is_charge": bool(row.get("is_charge", False)),
                "net": row.get("net"),
                "closed_at": closed_at.isoformat() if closed_at else None,
            }
        )

    deals.sort(key=lambda d: d["closed_at"] or "", reverse=True)

    grouped: dict[str, dict[str, float]] = defaultdict(
        lambda: {"net": 0.0, "trades": 0.0, "wins": 0.0}
    )
    for deal in deals:
        symbol = str(deal["symbol"] or "?")
        net = float(deal["net"] or 0.0)
        grouped[symbol]["net"] += net
        if not deal["is_charge"]:
            grouped[symbol]["trades"] += 1
            if net > 0:
                grouped[symbol]["wins"] += 1

    by_symbol = sorted(
        (
            {
                "symbol": symbol,
                "net": round(totals["net"], 2),
                "trades": int(totals["trades"]),
                "wins": int(totals["wins"]),
                # Reported only once there is something to divide. A hit rate
                # from two trades is a coin flip wearing a percentage.
                "hit_rate": (
                    round(totals["wins"] / totals["trades"], 3)
                    if totals["trades"] >= 5
                    else None
                ),
            }
            for symbol, totals in grouped.items()
        ),
        # Cast at the sort rather than loosening the row type: `net` is
        # always a float here and only the dict's union says otherwise.
        key=lambda row: float(row["net"] or 0.0),
    )

    net = round(sum(float(d["net"] or 0.0) for d in deals), 2)
    charge_events = sum(1 for deal in deals if deal["is_charge"])
    missing_fee_events = sum(1 for deal in deals if deal["fee"] is None)
    fees_available = bool(deals) and missing_fee_events == 0

    return {
        "available": True,
        "deals": deals,
        "by_symbol": by_symbol,
        "net": net,
        "trades": len(deals) - charge_events,
        "deal_events": len(deals),
        "charge_events": charge_events,
        "fee": round(sum(d["fee"] for d in deals), 2) if fees_available else None,
        "fees_available": fees_available,
        "missing_fee_events": missing_fee_events,
        "history_complete": None,
        "gross": round(sum(float(d["profit"] or 0.0) for d in deals), 2),
        "swap": round(sum(float(d["swap"] or 0.0) for d in deals), 2),
        "commission": round(sum(float(d["commission"] or 0.0) for d in deals), 2),
        "published_at": body.get("published_at"),
        "window_days": body.get("window_days"),
        "note": (
            "Published deal-event subtotal; entry charges affect money totals, "
            "not exit-event counts or hit rates. Missing fees are unknown, not zero. "
            "History completeness and broker reconciliation are not verified. "
            "A total that counts only profit is a number the account never saw."
        ),
    }
