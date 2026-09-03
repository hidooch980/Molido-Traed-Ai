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

#: The target, as a multiple of the risk.
#:
#: 1.0 for as long as this system existed, and never measured against
#: anything - `measure` read both of these off the module and so could only
#: ever score the geometry already deployed. When it was finally given the
#: question, 1.0 lost at almost every cut.
TARGET_MULTIPLE = 1.5

#: The stop, as a multiple of ATR. Recorded with the decision so a later
#: reader can tell which geometry produced which series - a rule re-measured
#: under a different stop is a different rule, and the journal holds both eras
#: side by side rather than pretending the older one was taken under this.
#:
#: 2.5 was the number this platform was built around, and out of sample it
#: loses on four timeframes of the five now measured. The stop was inside the
#: noise: 2.5 ATR is seven pips on M15 while entry costs four, so most of the
#: risk was spent before the trade had an opinion, and a normal wiggle closed
#: it. A live account showed 18% wins against the journal's 55% on the same
#: decisions, and that gap is this number.
#:
#: 7.5 and 1.5 were chosen on training windows alone and confirmed on data
#: the choice never saw:
#:
#:     H1, four rolling cuts over 687 days, chosen at every one of them
#:         +0.0060  +0.0318  +0.0493  +0.0403   net, held out
#:         -0.0701  -0.0463  -0.0042  +0.0096   the incumbent, same windows
#:     D1, 21 years of dukascopy   +0.1470 held out against +0.0503
#:     M1, an independent feed     +0.1481 held out against -0.3639
#:
#: M15 and M5 refused to confirm any geometry and are recorded as failures
#: rather than dropped. Three datasets that share no bars all asked for a stop
#: three times wider and a target above parity, which is the agreement that
#: makes this a measurement rather than a fit.
#:
#: What it costs: fewer trades reach a target this far away, and the ones that
#: do sit through more noise. The measurement says that trade is worth making.
#: The next thing to check is whether the live journal agrees, and it will
#: take weeks rather than a cycle to say so.
STOP_MULTIPLE = 7.5


def snapshot(
    session: Session,
    *,
    timeframe: Timeframe = Timeframe.H1,
    as_of: datetime | None = None,
    provider_code: str = SOURCE_PUBLIC,
    lookback: int = LOOKBACK,
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
        select(ranked).where(ranked.c._rn <= lookback)
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
        if len(bucket) < lookback:
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


def _record_candidates(
    session: Session,
    built: dict[str, dict[str, Any]],
    *,
    at: datetime,
    timeframe: Timeframe,
    price_source: str,
    account_key: str | None,
) -> int:
    """Record every candidate brain's picks on this snapshot.

    Same instant, same bars, same ATR geometry as the incumbent - the brains
    differ only in what they choose, which is the only difference a
    comparison between them can be allowed to contain. A candidate that
    declines, or picks a symbol whose ATR is unusable, records nothing for
    that pick; the incumbent's rows above are untouched either way.
    """
    from app.learning import rules as rules_module

    # A brain whose lookback outruns the standard window gets a deeper
    # snapshot, built once and only when somebody needs it. Handing every
    # brain the deep one instead would silently shrink the universe for the
    # short-lookback brains - an instrument with 100 bars of history answers
    # a 10-bar question perfectly well and vanishes from a 280-bar window.
    # This is the fourth appearance of the window-vs-lookback defect family;
    # this time the window asks the brain what it needs.
    deep_need = max(
        (
            int(getattr(rule, "lookback", 0)) + 30
            for rule in rules_module.CANDIDATES.values()
        ),
        default=0,
    )
    deep: dict[str, dict[str, Any]] | None = None
    if deep_need > LOOKBACK:
        deep, _ = snapshot(
            session,
            timeframe=timeframe,
            as_of=at,
            provider_code=price_source,
            lookback=deep_need,
        )

    written = 0
    for name, rule in rules_module.CANDIDATES.items():
        if name == rules_module.CrossSectionalStretch().name:
            continue  # the incumbent is already recorded, with richer fields
        needs = int(getattr(rule, "lookback", 0)) + 1
        view = deep if deep is not None and needs > LOOKBACK else built
        picks = rule(view, universe=None)
        if picks.empty:
            continue
        for symbols, side in ((picks.longs, "long"), (picks.shorts, "short")):
            side_sign = 1 if side == "long" else -1
            for symbol in symbols:
                bars = view.get(symbol, {}).get("bars") or []
                atr = crosssection.average_true_range(list(bars))
                price = (view.get(symbol, {}).get("closes") or [None])[-1]
                if not atr or price is None:
                    continue
                result = journal_log.record_with_control(
                    session,
                    symbol=symbol,
                    decision=side,
                    at=at,
                    price=float(price),
                    stop_distance=atr * STOP_MULTIPLE,
                    price_source=price_source,
                    timeframe=timeframe.value,
                    strategy=name,
                    account_key=account_key,
                    before={
                        "rule": name,
                        "atr": atr,
                        "stop_multiple": STOP_MULTIPLE,
                        "price_source": price_source,
                        "timeframe": timeframe.value,
                        "entry": float(price),
                        "stop": float(price) - atr * STOP_MULTIPLE * side_sign,
                        "target": float(price)
                        + atr * STOP_MULTIPLE * TARGET_MULTIPLE * side_sign,
                        "side": side,
                    },
                )
                if result["rule"]["new"]:
                    written += 1
    return written


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

    # Decide only on instruments the broker actually offers.
    #
    # The snapshot is filled from a free data provider that carries symbols
    # this broker does not: crypto, metal futures, a dozen thin currencies -
    # nineteen of forty-nine on this deployment. A brain takes two picks a
    # side, so a cycle where both of one brain's shorts are BTCUSD and GCFUT
    # is a brain that contributed nothing: its opinion is discarded at the
    # order gate with "the terminal publishes no contract specification",
    # after it has already spent its picks. Two accounts have never sent an
    # order in their lives and a quarter of everything they were offered was
    # of this kind.
    #
    # Narrowed here, before the ranking, so every brain sees the same ground.
    # Filtering the candidates alone would let the incumbent rank against
    # forty-nine while the others ranked against thirty, and the whole basis
    # of the comparison is that they differ only in what they choose.
    #
    # Fails open, loudly. A bridge that cannot be read returns nothing, and
    # an empty intersection would stop the fleet deciding altogether - which
    # is a far worse failure than deciding on a symbol that cannot be
    # bought. So an empty or unreadable answer leaves the snapshot alone and
    # says so in the report.
    dropped: list[str] = []
    try:
        from app.providers.metatrader import tradeable_symbols

        tradeable = tradeable_symbols()
    except Exception:  # noqa: BLE001 - a narrowing must never stop a cycle
        tradeable = frozenset()
    if tradeable:
        dropped = sorted(name for name in built if name not in tradeable)
        narrowed = {name: rows for name, rows in built.items() if name in tradeable}
        # Only if enough is left to rank. Below the cross-section minimum the
        # ranking is not a ranking, and a narrowing that produces a worse
        # measurement than no narrowing should not happen silently.
        if len(narrowed) >= MIN_FOR_INSTANT:
            built = narrowed
        else:
            dropped = []

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

    # The other brains, recorded beside the incumbent in the same pass, on the
    # same snapshot, with the same geometry. A candidate recorded by its own
    # job on its own schedule would decide on different bars and the
    # comparison between brains would be a comparison of schedules.
    candidate_written = _record_candidates(
        session,
        built,
        at=latest,
        timeframe=timeframe,
        price_source=price_source,
        account_key=account_key,
    )

    session.commit()
    return {
        "price_source": price_source,
        "not_offered_by_the_broker": len(dropped),
        "not_offered_names": dropped[:20],
        "candidates_recorded": candidate_written,
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
