"""Bars that cannot be true, found and removed - with the evidence kept.

A bar carries four prices and one relation between them: the high is the
highest price traded in the interval and the low is the lowest, so the open
and the close must both sit between them. A row where they do not is not a
price that needs interpreting. It is a record that contradicts itself.

3,529 such rows sit in the yfinance daily series - 3.32% of it. Every other
feed and timeframe in this deployment has none, including yfinance's own
1.3 million intraday bars, so this is a defect in how one provider assembles
one timeframe rather than a fact about the market. None has a second stored
revision: fifteen years on, the provider has not corrected any of them.

**They are removed rather than repaired**, and the difference matters. The
obvious repair is to widen the high and the low until they contain the
close, which assumes the close is right and the extremes were understated.
On the worst row here the close sits twenty-two times the bar's own range
outside it - that is a wrong close, and "repairing" it would manufacture a
bar with twenty-three times the true range, which then feeds ATR and every
geometry derived from it. A repair that invents a number is worse than a
deletion that admits one is missing.

Removing them turns an `invalid_ohlc_relation` into a `missing_candle`,
which is the honest trade: the first is an error and blocks the dataset, the
second is a warning and does not. A corrupt bar claims to be a price. A
missing bar claims nothing, and nothing is what is actually known.

**Every removed row is written out first.** Deleting market history is not
reversible by re-fetching, because the provider returns the same broken row -
so the export is the only way back, and the delete refuses to run without
one.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

#: How many rows one call will look at. Bounded because this walks a table
#: with two million rows in it and a sweep that has to finish is worth more
#: than one that does everything.
SCAN_LIMIT = 20_000


@dataclass
class Incoherent:
    """One row that contradicts itself, and by how much."""

    instrument_id: Any
    provider_id: Any
    timeframe: str
    event_time: datetime
    revision: int
    open: float
    high: float
    low: float
    close: float

    @property
    def inverted(self) -> bool:
        """The bar's own extremes are the wrong way round."""
        return self.high < self.low

    @property
    def breach(self) -> float:
        """How far outside its range the worst of open/close sits."""
        return max(
            self.low - self.close,
            self.close - self.high,
            self.low - self.open,
            self.open - self.high,
            0.0,
        )

    @property
    def span(self) -> float:
        return max(self.high - self.low, 0.0)

    @property
    def breach_share(self) -> float:
        """The breach as a share of the bar's own range.

        Reported because absolute price distance means nothing across
        instruments quoted in different units, and because it is the number
        that separates a rounding artefact from a wrong row - here the median
        is 1.7% and the worst is 2,280%.
        """
        return self.breach / self.span if self.span > 0 else float("inf")

    def as_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": str(self.instrument_id),
            "provider_id": str(self.provider_id),
            "timeframe": self.timeframe,
            "event_time": self.event_time.isoformat(),
            "revision": self.revision,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "breach": round(self.breach, 8),
            "breach_share": (
                None if self.span <= 0 else round(self.breach_share, 6)
            ),
        }


@dataclass
class Sweep:
    scanned: int = 0
    found: list[Incoherent] = field(default_factory=list)
    exported_to: str | None = None
    removed: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "scanned": self.scanned,
            "found": len(self.found),
            "exported_to": self.exported_to,
            "removed": self.removed,
            "by_provider_timeframe": self.by_provider_timeframe(),
        }

    def by_provider_timeframe(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for row in self.found:
            key = f"{row.provider_id}:{row.timeframe}"
            out[key] = out.get(key, 0) + 1
        return out


def find(
    session: Session,
    *,
    provider_id: Any | None = None,
    timeframe: str | None = None,
    limit: int = SCAN_LIMIT,
) -> Sweep:
    """Every stored row whose prices contradict each other.

    Only the newest revision of each instant is judged, because that is the
    row `point_in_time` serves and therefore the only one any consumer
    reads. A superseded row being wrong is what revisions are for.
    """
    from app.models.market_data import Bar

    query = select(Bar)
    if provider_id is not None:
        query = query.where(Bar.provider_id == provider_id)
    if timeframe is not None:
        query = query.where(Bar.timeframe == timeframe)
    query = query.order_by(
        Bar.instrument_id, Bar.timeframe, Bar.event_time, Bar.revision
    ).limit(limit)

    newest: dict[tuple, Any] = {}
    scanned = 0
    for bar in session.scalars(query):
        scanned += 1
        # Ascending revision, so the last write for an instant wins.
        newest[(bar.instrument_id, bar.timeframe, bar.event_time)] = bar

    sweep = Sweep(scanned=scanned)
    for bar in newest.values():
        o, h, low, c = (
            float(bar.open),
            float(bar.high),
            float(bar.low),
            float(bar.close),
        )
        if h >= low and low <= o <= h and low <= c <= h:
            continue
        sweep.found.append(
            Incoherent(
                instrument_id=bar.instrument_id,
                provider_id=bar.provider_id,
                timeframe=str(bar.timeframe),
                event_time=bar.event_time,
                revision=int(bar.revision),
                open=o,
                high=h,
                low=low,
                close=c,
            )
        )
    return sweep


def export(sweep: Sweep, path: str | pathlib.Path) -> str:
    """Write every row that is about to be deleted, one JSON object per line.

    Deleting market history is not reversible by re-fetching - the provider
    returns the same broken row - so this file is the only way back.
    """
    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "exported_at": datetime.now(UTC).isoformat(),
                    "rows": len(sweep.found),
                    "note": (
                        "bars whose open or close sat outside their own high/low, "
                        "removed because they contradict themselves and cannot be "
                        "repaired without inventing a price"
                    ),
                }
            )
            + "\n"
        )
        for row in sweep.found:
            handle.write(json.dumps(row.as_dict()) + "\n")
    sweep.exported_to = str(target)
    return str(target)


def remove(session: Session, sweep: Sweep) -> int:
    """Delete the rows in this sweep. Refuses without an export.

    The refusal is the point rather than a formality: this is the one
    operation here that cannot be undone by running something again, and a
    caller that has not written the evidence out has no way back at all.
    """
    if sweep.exported_to is None:
        raise ValueError(
            "refusing to delete bars that have not been exported - the "
            "provider returns the same broken rows, so the export is the "
            "only way back"
        )

    from app.models.market_data import Bar

    removed = 0
    for row in sweep.found:
        result = session.execute(
            select(Bar).where(
                Bar.instrument_id == row.instrument_id,
                Bar.provider_id == row.provider_id,
                Bar.timeframe == row.timeframe,
                Bar.event_time == row.event_time,
                Bar.revision == row.revision,
            )
        ).scalar_one_or_none()
        if result is None:
            continue
        session.delete(result)
        removed += 1
    session.flush()
    sweep.removed = removed
    return removed


__all__ = ["SCAN_LIMIT", "Incoherent", "Sweep", "export", "find", "remove"]
