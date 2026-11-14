"""The symbol universe agents scan: active instruments the broker actually offers.

When a terminal publishes contract specs, only instruments it can price are
scanned (broker suffixes such as `EURUSD.` or `EURUSDm` are matched). With no
terminal publishing, every active covered instrument is scanned and the source
says so.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.instruments import Instrument
from app.providers.metatrader import tradeable_symbols
from app.services.agent_scan import market_of


def _canon(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", name.upper())


def universe(session: Session, *, broker: frozenset[str] | None = None) -> dict[str, Any]:
    rows = session.scalars(
        select(Instrument).where(Instrument.is_active.is_(True)).order_by(Instrument.symbol)
    ).all()
    covered = [i.symbol for i in rows if market_of(i) is not None]
    names = broker if broker is not None else tradeable_symbols()
    if not names:
        return {"source": "database (no terminal publishes contract specs)",
                "symbols": covered, "excluded": []}
    canon = [_canon(n) for n in names]
    keep = [s for s in covered if any(c.startswith(_canon(s)) for c in canon)]
    return {"source": "mt5 bridge contract specs", "symbols": keep,
            "excluded": sorted(set(covered) - set(keep))}
