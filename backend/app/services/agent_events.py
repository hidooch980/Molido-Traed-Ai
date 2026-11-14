"""Economic calendar for RT06 and the risk gate, from the existing free feed.

Source: `app/services/calendar.py` (public ForexFactory XML, no key). Off unless
`MOLIDO_AGENT_CALENDAR=1`; while off, or when the feed fails or its clock looks
shifted, this returns None and RT06 abstains. A failed feed never reads as
"no news".
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.logging import get_logger
from app.services import calendar

log = get_logger(__name__)
FLAG = "MOLIDO_AGENT_CALENDAR"
WINDOW_BEFORE = timedelta(minutes=60)
WINDOW_AFTER = timedelta(minutes=30)


def enabled() -> bool:
    return os.environ.get(FLAG, "").strip().lower() in ("1", "true", "yes", "on")


def high_impact(*, opener: Any = None, force: bool = False) -> list[dict[str, Any]] | None:
    if not (enabled() or force):
        return None
    try:
        releases = calendar.parse(calendar.fetch(opener=opener))
    except Exception as exc:  # noqa: BLE001 - any feed failure means "unknown"
        log.warning("agent calendar unavailable: %s", exc)
        return None
    if calendar.looks_shifted(releases):
        return None
    return [{"time": r.at, "impact": "high", "currency": r.currency.upper(), "title": r.title}
            for r in releases if r.at is not None and r.impact == "High"]


def currencies(symbol: str) -> set[str]:
    s = symbol.upper()
    out = {s[:3], s[3:6]}
    if s.startswith(("XAU", "XAG")):
        out.add("USD")
    return out


def news_soon(events: list[dict[str, Any]] | None, symbol: str, at: datetime) -> bool | None:
    if events is None:
        return None
    ccys = currencies(symbol)
    at = at.astimezone(UTC)
    return any(e["currency"] in ccys and -WINDOW_AFTER <= e["time"] - at <= WINDOW_BEFORE
               for e in events)
