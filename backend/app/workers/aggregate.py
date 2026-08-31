"""Build a daily series from the hourly one, because the daily feed stopped.

The historical measurement cleared its bar on D1 and nowhere else. That series
came from the deep-history provider, and it ends on 2025-12-31: the backfill
loaded 2005 to 2025 and the provider serves nothing after it. So the one
timeframe with a measured edge has no live feed - no forward evidence can
accumulate on it, and nothing can be traded from it.

The hourly series is current, carries fifty-one instruments, and twenty-four
of its bars are a daily one. So the daily series is built rather than fetched.

**Only closed days.** Today is still being written, and a partial day emitted
as a closed bar is the same error as reading a series at "now" instead of at
the decision instant: the high and the low keep moving after the rule has
looked at them.

**A day needs enough hours to be one.** A day holding three bars has a high
and a low, and they describe three hours. Ranked against instruments that had
a full session it is not a quiet day, it is an unmeasured one, and a
cross-section reads the difference as signal.

**Written under its own provider name.** Not as the deep-history provider,
which would mix a fetched series with a derived one and make the twenty-one
year measurement irreproducible. A reader can tell which rows were observed
and which were computed, and can drop either.
"""

from __future__ import annotations

import argparse
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.enums import Timeframe
from app.models.instruments import Instrument, Provider
from app.models.market_data import Bar

#: The provider these rows are written under. Derived, and says so.
DERIVED_PROVIDER = "aggregated"

#: Hours a UTC day must hold before it counts as a daily bar. The FX week is
#: not twenty-four hours everywhere - Friday closes early, Sunday opens late -
#: so this sits well under a full day, and still far above the handful of bars
#: a gap leaves behind.
MIN_HOURS_PER_DAY = 12

#: Rows per insert. PostgreSQL caps a statement at 65535 parameters and each
#: row carries thirteen columns, so five thousand is the arithmetic ceiling;
#: this leaves room.
INSERT_CHUNK = 2000


def _provider_id(session: Session, code: str) -> uuid.UUID:
    """The provider row, created if this is the first run.

    Insert-then-read rather than read-then-insert: two runs started minutes
    apart both find no row, both insert, and the second dies on the unique
    index. The insert is a no-op on conflict.
    """
    session.execute(
        pg_insert(Provider)
        .values(
            code=code,
            name="Derived from hourly bars",
            capabilities={"ohlcv": True, "derived": True},
            # Below the fetched feeds on purpose. A folded bar is evidence
            # about the hours it was folded from, and a reader weighting it
            # equally with an observed one is weighting the fold as data.
            trust_weight=0.4,
        )
        .on_conflict_do_nothing(index_elements=[Provider.code])
    )
    session.flush()
    found = session.scalar(select(Provider).where(Provider.code == code))
    if found is None:  # pragma: no cover - the insert above guarantees it
        raise RuntimeError(f"the {code} provider could not be created")
    return found.id


def daily_from_hourly(
    bars: list[tuple[datetime, float, float, float, float]],
    *,
    today: date,
    min_hours: int = MIN_HOURS_PER_DAY,
) -> list[dict[str, Any]]:
    """Fold hourly bars into closed daily ones.

    `bars` is (event_time, open, high, low, close) in any order. The open is
    the first hour's open and the close is the last hour's close, so the bar
    describes the day as it was traded rather than as it was stored.

    Days at or after `today` are dropped whatever they hold. The current one is
    still being written, and a partial day emitted as closed is the same error
    as reading a series at "now" rather than at the decision instant.
    """
    by_day: dict[date, list[tuple[datetime, float, float, float, float]]] = defaultdict(
        list
    )
    for row in bars:
        by_day[row[0].astimezone(UTC).date()].append(row)

    built: list[dict[str, Any]] = []
    for day, hours in sorted(by_day.items()):
        if day >= today:
            continue
        if len(hours) < min_hours:
            continue
        hours.sort(key=lambda r: r[0])
        built.append(
            {
                "event_time": datetime(day.year, day.month, day.day, tzinfo=UTC),
                "open": float(hours[0][1]),
                "high": max(float(hour[2]) for hour in hours),
                "low": min(float(hour[3]) for hour in hours),
                "close": float(hours[-1][4]),
                "hours": len(hours),
            }
        )
    return built


def build(
    session: Session,
    *,
    source: str = "yfinance",
    today: date | None = None,
    min_hours: int = MIN_HOURS_PER_DAY,
) -> dict[str, Any]:
    """Fold every instrument's hourly series into daily bars."""
    moment_today = today or datetime.now(UTC).date()

    source_id = session.scalar(select(Provider.id).where(Provider.code == source))
    if source_id is None:
        return {
            "written": 0,
            "instruments": 0,
            "reason": (
                f"no {source} provider is recorded, so there are no hourly bars "
                "to fold - which is not the same as a day with no hours in it"
            ),
        }
    target_id = _provider_id(session, DERIVED_PROVIDER)

    written = 0
    per_symbol: dict[str, int] = {}
    skipped: list[str] = []
    newest: date | None = None

    for instrument in session.scalars(select(Instrument)):
        rows = list(
            session.execute(
                select(Bar.event_time, Bar.open, Bar.high, Bar.low, Bar.close)
                .where(
                    Bar.instrument_id == instrument.id,
                    Bar.timeframe == Timeframe.H1,
                    Bar.provider_id == source_id,
                )
                .order_by(Bar.event_time)
            )
        )
        if not rows:
            continue

        days = daily_from_hourly(
            [
                (row[0], float(row[1]), float(row[2]), float(row[3]), float(row[4]))
                for row in rows
            ],
            today=moment_today,
            min_hours=min_hours,
        )
        if not days:
            skipped.append(
                f"{instrument.symbol}: {len(rows)} hourly bars, no day holding "
                f"{min_hours} of them"
            )
            continue

        payload = [
            {
                "instrument_id": instrument.id,
                "timeframe": Timeframe.D1,
                "provider_id": target_id,
                "event_time": day["event_time"],
                "revision": 1,
                "open": day["open"],
                "high": day["high"],
                "low": day["low"],
                "close": day["close"],
                "volume": 0.0,
                # Below one, and by how much the day was short. A derived bar
                # is not an observed one, and the score is where that shows.
                "quality_score": round(min(1.0, day["hours"] / 24.0), 3),
                "source_ref": f"{DERIVED_PROVIDER}:{source}:H1:{instrument.symbol}",
            }
            for day in days
        ]

        for start_at in range(0, len(payload), INSERT_CHUNK):
            chunk = payload[start_at : start_at + INSERT_CHUNK]
            statement = pg_insert(Bar).values(chunk)
            statement = statement.on_conflict_do_update(
                index_elements=[
                    Bar.instrument_id,
                    Bar.timeframe,
                    Bar.provider_id,
                    Bar.event_time,
                    Bar.revision,
                ],
                set_={
                    "open": statement.excluded.open,
                    "high": statement.excluded.high,
                    "low": statement.excluded.low,
                    "close": statement.excluded.close,
                    "quality_score": statement.excluded.quality_score,
                },
            )
            session.execute(statement)

        written += len(payload)
        per_symbol[instrument.symbol] = len(payload)
        last_day = days[-1]["event_time"].date()
        newest = last_day if newest is None or last_day > newest else newest

    return {
        "written": written,
        "instruments": len(per_symbol),
        "provider": DERIVED_PROVIDER,
        "source": source,
        "newest": newest.isoformat() if newest else None,
        "skipped": skipped[:10],
        "note": (
            "derived from hourly bars, not observed. Written under its own "
            "provider so the fetched series stays reproducible"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fold the hourly series into daily bars."
    )
    parser.add_argument("--source", default="yfinance")
    parser.add_argument("--min-hours", type=int, default=MIN_HOURS_PER_DAY)
    args = parser.parse_args()

    from app.db.session import session_scope

    with session_scope() as session:
        report = build(session, source=args.source, min_hours=args.min_hours)
    for key, value in report.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
