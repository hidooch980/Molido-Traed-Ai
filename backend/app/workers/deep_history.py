"""Backfill twenty years of bank-feed history, one verified symbol at a time.

The forward measurement needs about 6,573 instants to answer - roughly a year
of hourly bars. This is the other way to learn something: an independent sample
nothing in this project has searched, fetched in hours rather than waited for.
It has already been decisive once. Re-run on eleven years of daily bars the
cross-sectional rule scored -0.0015 R against its control at t = -0.12, and
that single result is why the claim sits in PENDING_FORWARD instead of PROVEN.

Two refusals carry this module, and both are about the same failure.

**No symbol is imported without its price scale verified against a price this
system already holds.** Dukascopy publishes prices as scaled integers and the
scale differs per instrument - 1e5 for EURUSD, 1e3 for gold and the yen pairs.
Applying the wrong one puts gold at 20.63 instead of 2063.63. Nothing raises.
Every moving average, every ATR, every ranking simply believes it, and the
error is invisible in any chart because the whole series is wrong by the same
factor. So the scale is chosen by matching a bar this database already has, and
a symbol with no such bar is skipped by name rather than imported on a guess.

**A period that could not be read is reported, never dropped.** Weekends come
back empty legitimately. So does a year with a gap in it. A backfill that
returns fewer bars without saying which periods it could not read leaves a
history whose holes are indistinguishable from a closed market - and the
cross-sectional rule specifically excludes instruments whose series went quiet,
so a hole does not merely lose data, it silently changes which instruments get
ranked.

It writes under its own provider. Three sources now price the same instrument
and none of them is the truth; merging them means the last writer wins and the
disagreement - which is itself a measurement - is never seen.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.enums import Timeframe
from app.core.errors import ProviderError
from app.models.instruments import Instrument, Provider
from app.models.market_data import Bar
from app.providers.dukascopy import DukascopyProvider, default_asset_class

PROVIDER_CODE = "dukascopy"

#: How far back to reach by default. The claim that failed was tested on eleven
#: years; this covers that plus the 2008 crisis, which no two-year hourly
#: window contains and which is exactly the regime a mean-reversion rule should
#: be asked about.
DEFAULT_START_YEAR = 2005


def _provider(session: Session) -> Provider:
    row = session.scalar(select(Provider).where(Provider.code == PROVIDER_CODE))
    if row is None:
        row = Provider(
            code=PROVIDER_CODE,
            name="Dukascopy Bank",
            capabilities={"ohlcv": True, "ticks": True},
        )
        session.add(row)
        session.flush()
    return row


def reference_price(
    session: Session, instrument_id: Any, *, timeframe: Timeframe = Timeframe.H1
) -> float | None:
    """A price this database already holds for that instrument.

    Any provider will do and the bar may be years away from the one being
    checked, because the error being caught is a factor of a hundred rather
    than a few pips. What matters is only that it did not come from Dukascopy -
    verifying a feed against itself verifies nothing.
    """
    dukascopy = session.scalar(
        select(Provider.id).where(Provider.code == PROVIDER_CODE)
    )
    query = select(Bar.close).where(
        Bar.instrument_id == instrument_id,
        Bar.timeframe == timeframe.value,
    )
    if dukascopy is not None:
        query = query.where(Bar.provider_id != dukascopy)
    price = session.scalar(query.order_by(Bar.event_time.desc()).limit(1))
    return float(price) if price is not None else None


def backfill(
    session: Session,
    *,
    symbols: list[str],
    timeframe: Timeframe = Timeframe.D1,
    start_year: int = DEFAULT_START_YEAR,
    end: datetime | None = None,
    provider: DukascopyProvider | None = None,
) -> dict[str, Any]:
    """Fetch and store deep history for each symbol that can be verified.

    Upserts on the natural key, so re-running over an overlapping window
    updates rather than duplicating - and this is a window somebody will
    re-run, because the first attempt at twenty years will hit a network error
    somewhere in it.
    """
    feed = provider or DukascopyProvider()
    row = _provider(session)
    ceiling = (end or datetime.now(UTC)).astimezone(UTC)
    start = datetime(start_year, 1, 1, tzinfo=UTC)

    written = 0
    imported: dict[str, int] = {}
    skipped: list[str] = []
    holes: list[str] = []

    for symbol in symbols:
        instrument = session.scalar(
            select(Instrument).where(Instrument.symbol == symbol)
        )
        if instrument is None:
            instrument = Instrument(
                symbol=symbol,
                name=symbol,
                asset_class=default_asset_class(symbol),
            )
            session.add(instrument)
            session.flush()

        known = reference_price(session, instrument.id)
        if known is None:
            # Skipped by name. An instrument this system holds no price for
            # cannot have its scale checked, and importing it on the table's
            # guess is how a hundredfold error enters a series nobody will ever
            # look at closely enough to notice.
            skipped.append(
                f"{symbol}: no price from another source to verify the scale "
                "against, so its history is not imported"
            )
            continue

        try:
            feed.verify_scale(symbol, known, at=ceiling.replace(year=ceiling.year - 1))
            bars = feed.fetch_ohlcv(symbol, timeframe, start, ceiling)
        except ProviderError as problem:
            skipped.append(f"{symbol}: {problem}")
            continue

        holes.extend(feed.missing_periods)

        if not bars:
            skipped.append(f"{symbol}: the feed returned no bars in that window")
            continue

        payload = [
            {
                "instrument_id": instrument.id,
                "timeframe": timeframe.value,
                "provider_id": row.id,
                "event_time": bar.event_time,
                "revision": 1,
                "ingested_at": ceiling,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume or 0.0,
                "quality_score": 1.0,
                "source_ref": f"dukascopy:{symbol}:{timeframe.value}",
            }
            for bar in bars
        ]

        statement = pg_insert(Bar).values(payload)
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
        imported[symbol] = len(payload)
        written += len(payload)

    session.commit()
    return {
        "written": written,
        "by_symbol": imported,
        "timeframe": timeframe.value,
        "from": start.isoformat(),
        "provider": PROVIDER_CODE,
        # Both published. A symbol skipped for want of a reference and a
        # period the feed had no file for are different problems with
        # different fixes, and a single "12 failures" count invites neither.
        "skipped": skipped,
        "periods_with_no_file": holes[:50],
        "note": (
            "stored under its own provider rather than merged. Three sources "
            "now price the same instrument and none is the truth; merging "
            "means the last writer wins and the disagreement is never seen"
        ),
    }
