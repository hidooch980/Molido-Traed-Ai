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

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.brain import crosssection
from app.core.enums import Timeframe
from app.models.instruments import Instrument
from app.models.market_data import Bar
from app.services import journal_log

#: Enough for the 50-bar mean plus the ATR window plus a margin. Asking for
#: fewer produces instruments that are silently skipped for want of history.
LOOKBACK = 80

#: How many instruments must share a timestamp for it to be the cross-section's
#: instant. The same floor the ranking itself uses - a timestamp where only
#: three instruments printed is not a cross-section, it is three instruments.
MIN_FOR_INSTANT = crosssection.MIN_CROSS_SECTION

#: The stop the measurement used. Recorded with the decision so a later reader
#: can tell which geometry produced which series - a rule re-measured under a
#: different stop is a different rule.
STOP_MULTIPLE = 2.5


def snapshot(
    session: Session, *, timeframe: Timeframe = Timeframe.H1, as_of: datetime | None = None
) -> tuple[dict[str, dict[str, Any]], datetime | None]:
    """The last `LOOKBACK` closed bars for every instrument, and their instant.

    Every instrument is cut at the same timestamp. A cross-section assembled
    from whatever each instrument last published would rank an instrument's
    Tuesday against another's Wednesday, and call the difference a signal.
    """
    cutoff = (as_of or datetime.now(UTC)).astimezone(UTC)
    # Active only. Two truncated duplicates of live symbols - left behind by an
    # old symbol-normalising bug - were still being ranked against the real
    # ones, and one was picked on the first live cycle. Deactivating them is
    # the data fix; this is the code fix, and the staleness guard in `rank` is
    # the general one for any series that stops.
    instruments = session.scalars(
        select(Instrument).where(Instrument.is_active.is_(True))
    ).all()

    built: dict[str, dict[str, Any]] = {}
    seen_at: dict[datetime, int] = {}

    for instrument in instruments:
        rows = session.scalars(
            select(Bar)
            .where(
                Bar.instrument_id == instrument.id,
                Bar.timeframe == timeframe.value,
                Bar.event_time <= cutoff,
            )
            .order_by(Bar.event_time.desc())
            .limit(LOOKBACK)
        ).all()
        if len(rows) < LOOKBACK:
            continue

        rows = list(reversed(rows))
        built[instrument.symbol] = {
            "closes": [float(r.close) for r in rows],
            "bars": [(float(r.high), float(r.low), float(r.close)) for r in rows],
            # Carried so the ranking can exclude a series that stopped moving.
            # A frozen series drifts one way from its own mean, so it ranks
            # extreme and gets picked, and the pick is about the outage rather
            # than the market.
            "last_at": rows[-1].event_time,
        }
        seen_at[rows[-1].event_time] = seen_at.get(rows[-1].event_time, 0) + 1

    # The instant is the most recent one where enough instruments actually have
    # a bar - not the newest bar anywhere.
    #
    # Those are different on any weekend. Crypto trades through it and FX does
    # not, so the newest bar in the database belongs to BTCUSD while every
    # currency pair last printed on Friday. Taking the maximum makes the whole
    # FX book look two days stale against one instrument that never sleeps, and
    # the staleness guard - correctly - throws all of it away. The first cycle
    # after that guard shipped ranked two instruments out of forty-nine.
    latest = None
    for stamp in sorted(seen_at, reverse=True):
        if seen_at[stamp] >= MIN_FOR_INSTANT:
            latest = stamp
            break

    return built, latest


def record_cycle(
    session: Session,
    *,
    timeframe: Timeframe = Timeframe.H1,
    as_of: datetime | None = None,
    account_key: str | None = None,
) -> dict[str, Any]:
    """One pass: rank, record both arms, report what happened.

    Idempotent through the journal's unique constraint on (symbol, bar, arm),
    so running twice over an overlapping window does not inflate the sample the
    entire measurement rests on.
    """
    built, latest = snapshot(session, timeframe=timeframe, as_of=as_of)
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
        for pick in picks:
            result = journal_log.record_with_control(
                session,
                symbol=pick.symbol,
                decision=side,
                at=latest,
                price=pick.price,
                stop_distance=pick.atr * STOP_MULTIPLE,
                account_key=account_key,
                before={
                    "rule": "cross-sectional-stretch",
                    "stretch": round(pick.stretch, 4),
                    "atr": pick.atr,
                    "stop_multiple": STOP_MULTIPLE,
                    "cross_section_size": ranked.considered,
                },
            )
            if result["rule"]["new"]:
                written += 1
            else:
                duplicates += 1

    session.commit()
    return {
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
