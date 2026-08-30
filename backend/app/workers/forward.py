"""Record what the cross-sectional rule proposes, and what a coin flip does.

This is the only thing in the system that can settle the question the whole
project turns on. The rule cleared four of the five bars on history and fails
the fifth - forward evidence - and the only way to earn that is to write down
what it says, before the outcome is known, on data nobody has searched.

Two properties matter more than anything else here, and both are about not
flattering the result later:

**The decision is recorded before the outcome exists.** The bar it decides on
is closed; everything it is judged against has not happened yet. A record
written after the fact, however honestly, is a record of what somebody
remembered.

**The control is written in the same call.** Not a second pass, not a nightly
job that might miss a day. A rule series built over months beside a control
series that was skipped whenever something else broke is a comparison with a
hole in it, and the hole is invisible afterwards.

It records and does not trade. Whether an order is sent is the autopilot's
question and it has its own four gates; this exists so that in some number of
months there is something to point at, whichever way it comes out.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.brain import crosssection
from app.core.enums import Timeframe
from app.models.instruments import Instrument, Provider
from app.models.journal import SOURCE_PUBLIC
from app.models.market_data import Bar
from app.services import journal_log

#: Enough for the 50-bar mean plus the ATR window plus a margin. Asking for
#: fewer produces instruments that are silently skipped for want of history.
LOOKBACK = 80

#: How many instruments must share a timestamp for it to be the cross-section's
#: instant. The same floor the ranking itself uses - a timestamp where only
#: three instruments printed is not a cross-section, it is three instruments.
MIN_FOR_INSTANT = crosssection.MIN_CROSS_SECTION

#: The target, as a multiple of the risk. 1R, as tested.
TARGET_MULTIPLE = 1.0

#: The stop the measurement used. Recorded with the decision so a later reader
#: can tell which geometry produced which series - a rule re-measured under a
#: different stop is a different rule.
STOP_MULTIPLE = 2.5


def snapshot(
    session: Session,
    *,
    timeframe: Timeframe = Timeframe.H1,
    as_of: datetime | None = None,
    provider_code: str = SOURCE_PUBLIC,
) -> tuple[dict[str, dict[str, Any]], datetime | None]:
    """The last `LOOKBACK` closed bars for every instrument, and their instant.

    Every instrument is cut at the same timestamp. A cross-section assembled
    from whatever each instrument last published would rank an instrument's
    Tuesday against another's Wednesday, and call the difference a signal.
    """
    ceiling = (as_of or datetime.now(UTC)).astimezone(UTC)
    # Active only. Two truncated duplicates of live symbols - left behind by an
    # old symbol-normalising bug - were still being ranked against the real
    # ones, and one was picked on the first live cycle. Deactivating them is
    # the data fix; this is the code fix, and the staleness guard in `rank` is
    # the general one for any series that stops.
    instruments = session.scalars(
        select(Instrument).where(Instrument.is_active.is_(True))
    ).all()

    # Two passes, and the reason is point-in-time integrity rather than tidiness.
    #
    # The instant is Friday 21:00 whenever the weekend is on, because that is
    # the last bar the FX book shares. Crypto keeps printing through Saturday.
    # A single pass that read every instrument up to *now* would rank BTCUSD's
    # Saturday price inside a Friday cross-section - the mean, the last close
    # and therefore the stretch would all contain prices from after the moment
    # being decided on.
    #
    # That is lookahead, it flatters the rule silently, and it would have gone
    # into the forward series as evidence.
    provider_id = _provider_id(session, provider_code)
    if provider_id is None:
        return {}, None

    instant = _instant(
        session, instruments, timeframe=timeframe, ceiling=ceiling, provider_id=provider_id
    )
    if instant is None:
        return {}, None
    cutoff = instant

    # One query for the whole active universe instead of one query per symbol.
    # First isolate the latest revision for each instrument/event_time, then
    # rank those rows per instrument and keep the newest LOOKBACK bars.
    from sqlalchemy import func

    active_ids = [instrument.id for instrument in instruments]
    if not active_ids:
        return {}, instant

    latest_revision = (
        select(
            Bar.instrument_id,
            Bar.event_time,
            func.max(Bar.revision).label("revision"),
        )
        .where(
            Bar.instrument_id.in_(active_ids),
            Bar.timeframe == timeframe.value,
            Bar.provider_id == provider_id,
            Bar.event_time <= cutoff,
        )
        .group_by(Bar.instrument_id, Bar.event_time)
        .subquery()
    )

    ranked = (
        select(
            Bar,
            func.row_number()
            .over(
                partition_by=Bar.instrument_id,
                order_by=Bar.event_time.desc(),
            )
            .label("_rn"),
        )
        .join(
            latest_revision,
            (Bar.instrument_id == latest_revision.c.instrument_id)
            & (Bar.event_time == latest_revision.c.event_time)
            & (Bar.revision == latest_revision.c.revision),
        )
        .where(
            Bar.timeframe == timeframe.value,
            Bar.provider_id == provider_id,
        )
        .subquery()
    )

    rows = session.execute(
        select(ranked).where(ranked.c._rn <= LOOKBACK)
    ).all()

    by_instrument: dict[uuid.UUID, list[Any]] = {}
    for row in rows:
        values = row._mapping
        instrument_id = values["instrument_id"]
        by_instrument.setdefault(instrument_id, []).append(values)

    built: dict[str, dict[str, Any]] = {}
    for instrument in instruments:
        # Its own name rather than reusing `values`: the loop above binds that
        # name to a RowMapping, and one identifier carrying two types is how
        # the type checker - and the next reader - lose the thread.
        bucket = by_instrument.get(instrument.id, [])
        if len(bucket) < LOOKBACK:
            continue

        bucket.sort(key=lambda x: x["event_time"])
        built[instrument.symbol] = {
            "closes": [float(v["close"]) for v in bucket],
            "bars": [
                (float(v["high"]), float(v["low"]), float(v["close"]))
                for v in bucket
            ],
            "last_at": bucket[-1]["event_time"],
        }

    return built, instant


def _instant(
    session: Session,
    instruments: Sequence[Instrument],
    *,
    timeframe: Timeframe,
    ceiling: datetime,
    provider_id: uuid.UUID,
) -> datetime | None:
    """The most recent moment where enough instruments actually have a bar.

    Not the newest bar anywhere. Those differ on every weekend: crypto trades
    through it and FX does not, so the newest bar belongs to BTCUSD while every
    currency pair last printed on Friday. Taking the maximum made the whole FX
    book look two days stale against one instrument that never sleeps, and the
    staleness guard - correctly - threw all of it away. That cycle ranked two
    instruments out of forty-nine.
    """
    if not instruments:
        return None

    active_ids = [instrument.id for instrument in instruments]

    # Find the newest closed timestamp shared by enough active instruments.
    # This replaces one expensive latest-row query per instrument with one
    # grouped query over the hypertable.
    stamp = session.scalar(
        select(Bar.event_time)
        .where(
            Bar.instrument_id.in_(active_ids),
            Bar.timeframe == timeframe.value,
            Bar.provider_id == provider_id,
            Bar.event_time <= ceiling,
        )
        .group_by(Bar.event_time)
        .having(func.count(func.distinct(Bar.instrument_id)) >= MIN_FOR_INSTANT)
        .order_by(Bar.event_time.desc())
        .limit(1)
    )
    return stamp


def _provider_id(session: Session, code: str) -> uuid.UUID | None:
    return session.scalar(select(Provider.id).where(Provider.code == code))


def record_cycle(
    session: Session,
    *,
    timeframe: Timeframe = Timeframe.H1,
    as_of: datetime | None = None,
    account_key: str | None = None,
    price_source: str = SOURCE_PUBLIC,
) -> dict[str, Any]:
    """One pass: rank, record both arms, report what happened.

    Idempotent through the journal's unique constraint on (symbol, bar, arm),
    so running twice over an overlapping window does not inflate the sample the
    entire measurement rests on.
    """
    built, latest = snapshot(
        session, timeframe=timeframe, as_of=as_of, provider_code=price_source
    )
    if latest is None:
        return {
            "recorded": 0,
            "reason": (
                f"no instrument has {LOOKBACK} closed {timeframe.value} bars yet, "
                "so no cross-section can be ranked"
            ),
        }

    ranked = crosssection.rank(built, at=latest, bar_interval=timeframe.delta)
    if not ranked.available:
        return {"recorded": 0, "reason": ranked.reason, "considered": ranked.considered}

    written = 0
    duplicates = 0
    for picks, side in ((ranked.longs, "long"), (ranked.shorts, "short")):
        side_sign = 1 if side == "long" else -1
        for pick in picks:
            result = journal_log.record_with_control(
                session,
                symbol=pick.symbol,
                decision=side,
                at=latest,
                price=pick.price,
                stop_distance=pick.atr * STOP_MULTIPLE,
                price_source=price_source,
                # The whole point of widening the measurement: an entry that
                # cannot say which timeframe it came from cannot be separated
                # from one that came from another, and the hourly and minute
                # bars share a timestamp every hour.
                timeframe=timeframe.value,
                account_key=account_key,
                before={
                    "rule": "cross-sectional-stretch",
                    "stretch": round(pick.stretch, 4),
                    "atr": pick.atr,
                    "stop_multiple": STOP_MULTIPLE,
                    "cross_section_size": ranked.considered,
                    "price_source": price_source,
                    # Recorded, not assumed. The freshness window that
                    # decides whether this is still tradeable has to add
                    # back the bar it was taken on, and a decision taken
                    # on an M5 bar charged an hour is an hour of drift
                    # nobody chose.
                    "timeframe": timeframe.value,
                    # The levels, resolved and stored rather than recomputed
                    # later. A resolver that rebuilds them from the ATR would
                    # score the trade against a geometry the decision never
                    # had if either constant ever moved - and the two would
                    # look identical in the database.
                    "entry": pick.price,
                    "stop": pick.price - pick.atr * STOP_MULTIPLE * side_sign,
                    "target": pick.price
                    + pick.atr * STOP_MULTIPLE * TARGET_MULTIPLE * side_sign,
                    "side": side,
                },
            )
            if result["rule"]["new"]:
                written += 1
            else:
                duplicates += 1

    session.commit()
    return {
        "price_source": price_source,
        "recorded": written,
        # Published rather than swallowed. A cycle that writes nothing because
        # everything was already recorded and one that writes nothing because
        # the rule proposed nothing are different facts.
        "already_recorded": duplicates,
        "at": latest.isoformat(),
        "considered": ranked.considered,
        "longs": [p.symbol for p in ranked.longs],
        "shorts": [p.symbol for p in ranked.shorts],
        "skipped": list(ranked.skipped),
    }
