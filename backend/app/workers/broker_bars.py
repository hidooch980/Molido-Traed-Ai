"""Ingest the bars the broker publishes, under their own provider.

The bridge has been writing forty-six bar files every twenty seconds since it
was built, and nothing read them. Every bar in this database came from Yahoo,
which means the system researches on one price series and would trade on
another.

Those are not the same series and the difference is not cosmetic. Spreads
differ, session boundaries differ, weekend gaps land in different places, and
the same instrument is quoted differently at every broker. A rule measured on
Yahoo bars and executed against RoboForex prices has been measured on something
adjacent to what it will do.

They arrive under the MetaTrader provider rather than merged into the existing
series, which is the design `metatrader.py` stated from the start and nothing
implemented. Keeping them separate means a disagreement between the two is a
measurement the conflict detector can act on, rather than a silent overwrite
where the last writer wins.

Nothing here decides which series is right. Yahoo is a public consensus and the
broker is where the account actually fills - they answer different questions,
and a system that quietly picks one has answered a question nobody asked.
"""

from __future__ import annotations

import csv
import pathlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.enums import AssetClass, Timeframe
from app.models.instruments import Instrument, Provider
from app.models.market_data import Bar
from app.providers.metatrader import DEFAULT_BRIDGE_DIR

#: The provider these bars are recorded under. Separate from yfinance on
#: purpose - two sources writing one series means the last writer wins and the
#: disagreement is never seen.
PROVIDER_CODE = "metatrader"

#: MetaTrader writes `2026.08.14 07:53:24` in the terminal's own timezone,
#: which this deployment runs as GMT+0.
STAMP_FORMAT = "%Y.%m.%d %H:%M:%S"


def _provider(session: Session) -> Provider:
    row = session.scalar(select(Provider).where(Provider.code == PROVIDER_CODE))
    if row is None:
        row = Provider(
            code=PROVIDER_CODE,
            name="MetaTrader bridge",
            capabilities={"ohlcv": True},
        )
        session.add(row)
        session.flush()
    return row


def _instrument(session: Session, symbol: str) -> Instrument:
    row = session.scalar(select(Instrument).where(Instrument.symbol == symbol))
    if row is None:
        row = Instrument(
            symbol=symbol,
            name=symbol,
            # The broker's own classification is not published, and guessing
            # from the name would put .US500Cash in whatever bucket the string
            # happened to match. OTHER is honest.
            asset_class=AssetClass.OTHER,
        )
        session.add(row)
        session.flush()
    return row


def ingest(
    session: Session,
    *,
    directory: pathlib.Path | str | None = None,
    timeframe: Timeframe = Timeframe.H1,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Read every bar file the bridge has written for this timeframe.

    Upserts on the natural key, so re-running over an overlapping window
    updates rather than duplicating - the bridge republishes the same 500 bars
    every cycle, and inserting them each time would multiply the series by the
    number of cycles.
    """
    root = pathlib.Path(directory or DEFAULT_BRIDGE_DIR)
    moment = (now or datetime.now(UTC)).astimezone(UTC)

    if not root.exists():
        return {
            "ingested": 0,
            "reason": f"the bridge directory {root} is not mounted here",
        }

    provider = _provider(session)
    written = 0
    files = 0
    failures: list[str] = []

    for path in sorted(root.glob(f"molido_bars_*_{timeframe.value}.csv")):
        symbol = path.name[len("molido_bars_") : -len(f"_{timeframe.value}.csv")]
        if not symbol:
            continue
        files += 1

        try:
            instrument = _instrument(session, symbol)
            rows = []
            with path.open(newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    stamp = datetime.strptime(
                        row["event_time"].strip(), STAMP_FORMAT
                    ).replace(tzinfo=UTC)
                    rows.append(
                        {
                            "instrument_id": instrument.id,
                            "timeframe": timeframe.value,
                            "provider_id": provider.id,
                            "event_time": stamp,
                            "revision": 1,
                            "ingested_at": moment,
                            "open": float(row["open"]),
                            "high": float(row["high"]),
                            "low": float(row["low"]),
                            "close": float(row["close"]),
                            "volume": float(row.get("volume") or 0.0),
                            "quality_score": 1.0,
                            "source_ref": f"metatrader:{symbol}:{timeframe.value}",
                        }
                    )
        except (OSError, ValueError, KeyError) as problem:
            # Named, not swallowed. A symbol that silently stops arriving looks
            # identical to one the broker stopped quoting.
            failures.append(f"{symbol}: {type(problem).__name__}")
            continue

        if not rows:
            continue

        statement = pg_insert(Bar).values(rows)
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
                "volume": statement.excluded.volume,
                "ingested_at": statement.excluded.ingested_at,
            },
        )
        session.execute(statement)
        written += len(rows)

    session.commit()
    return {
        "ingested": written,
        "files": files,
        "provider": PROVIDER_CODE,
        "failures": failures,
        "note": (
            "recorded under the metatrader provider rather than merged with the "
            "public feed. Spreads and session boundaries differ, and two sources "
            "writing one series means the last writer wins and the disagreement "
            "is never seen"
        ),
    }
