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

from app.brain import crosssection
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

#: Rows per INSERT statement.
#:
#: PostgreSQL's wire protocol caps a single statement at 65535 bound
#: parameters. A bar carries thirteen columns, so the ceiling is 5,041 rows -
#: and twenty years of daily bars is about 5,200 per symbol, which lands just
#: past it. The whole first backfill failed on the first symbol with "number of
#: parameters must be between 0 and 65535", and the hourly run would be
#: twenty-five times further over.
#:
#: Two thousand leaves room for columns nobody has added yet. The limit is a
#: property of the protocol rather than of this table, so sizing to exactly
#: 65535/13 would mean the next migration breaks the backfill and the failure
#: appears somewhere else entirely.
INSERT_CHUNK = 2000

#: Consecutive whole-symbol failures before the run gives up.
#:
#: Measured, not chosen. Pacing requests further apart made the feed *worse*,
#: not better: ten requests at 0.6s apart got five answers, at 2s got two, at
#: 5s got one - in that order, over about five minutes. A rate limit does not
#: behave like that. What does is an endpoint that has soured on this address
#: from the session's cumulative volume, and no pacing recovers it; it needs
#: hours, not seconds.
#:
#: Against that, retrying is not resilience. A run of twenty-eight symbols at
#: six attempts each would spend three hours discovering the same refusal
#: twenty-eight times and write nothing. Four symbols failing back to back is
#: enough to say the feed is not answering today, and saying so in three
#: minutes is worth more than proving it in three hours.
CONSECUTIVE_FAILURES_BEFORE_STOPPING = 4


def _provider(session: Session) -> Provider:
    """Get or create the provider row, safely under concurrency.

    Read-then-insert loses a race: two backfills started minutes apart both
    find no row, both insert, and the second dies on
    `UniqueViolation: Key (code)=(dukascopy) already exists` after doing real
    work. That happened - two runs overlapped and the second lost everything it
    had fetched.

    The insert is a no-op on conflict and the row is read back afterwards, so
    whoever wins the race, both callers end up with the same provider.
    """
    statement = (
        pg_insert(Provider)
        .values(
            code=PROVIDER_CODE,
            name="Dukascopy Bank",
            capabilities={"ohlcv": True, "ticks": True},
        )
        .on_conflict_do_nothing(index_elements=[Provider.code])
    )
    session.execute(statement)
    row = session.scalar(select(Provider).where(Provider.code == PROVIDER_CODE))
    if row is None:  # pragma: no cover - the insert above guarantees it exists
        raise RuntimeError(
            f"the {PROVIDER_CODE} provider row could neither be created nor read"
        )
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
    in_a_row = 0
    gave_up: str | None = None

    for position, symbol in enumerate(symbols, start=1):
        # Progress on a run this long is not decoration. Forty minutes of
        # silence and forty minutes of a wedged socket look identical.
        print(f"  [{position}/{len(symbols)}] {symbol}", flush=True)
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
            # Not counted toward the give-up threshold: this is a fact about
            # our own database, not about the feed, and it would still be true
            # on a day the feed was answering perfectly.
            continue

        try:
            feed.verify_scale(symbol, known, at=ceiling.replace(year=ceiling.year - 1))
            bars = feed.fetch_ohlcv(symbol, timeframe, start, ceiling)
        except ProviderError as problem:
            skipped.append(f"{symbol}: {problem}")
            in_a_row += 1
            if in_a_row >= CONSECUTIVE_FAILURES_BEFORE_STOPPING:
                gave_up = (
                    f"stopped after {in_a_row} symbols failed back to back. "
                    "The feed is not answering this address today - measured: "
                    "pacing requests further apart made it worse, not better, "
                    "which is degradation over time rather than a rate limit. "
                    "Re-run in a few hours; everything already written is kept"
                )
                break
            continue

        holes.extend(feed.missing_periods)

        if not bars:
            skipped.append(f"{symbol}: the feed returned no bars in that window")
            in_a_row += 1
            if in_a_row >= CONSECUTIVE_FAILURES_BEFORE_STOPPING:
                gave_up = (
                    f"stopped after {in_a_row} symbols produced nothing in a "
                    "row. Re-run later; everything already written is kept"
                )
                break
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
                    "volume": statement.excluded.volume,
                    "ingested_at": statement.excluded.ingested_at,
                },
            )
            session.execute(statement)
        # Committed per symbol, not once at the end. The hourly run is roughly
        # 3,700 requests over forty minutes, and a single transaction means one
        # failure at the twenty-seventh symbol discards the other twenty-six.
        # The upsert makes a re-run cheap either way, but re-running forty
        # minutes of network requests to recover work already done is a cost
        # nobody has to pay.
        session.commit()
        imported[symbol] = len(payload)
        written += len(payload)
        in_a_row = 0


    # Stated, not left to be inferred from the length of a dict. A dry run of
    # twenty-eight symbols got fifteen answers and then thirteen consecutive
    # 503s, and a backfill that reports "imported 15" reads as success. Fifteen
    # is below the minimum cross-section, so nothing could have been measured
    # on it - but had the throttle cut in at twenty-two instead, the
    # measurement would have run happily across a universe chosen by which
    # requests the feed felt like answering.
    enough = len(imported) >= crosssection.MIN_CROSS_SECTION

    return {
        "written": written,
        "by_symbol": imported,
        "usable_for_ranking": enough,
        # Distinct from `usable_for_ranking`. One says the result is too thin
        # to measure; this says the run did not finish, which is why.
        "gave_up": gave_up,
        "universe_warning": (
            None
            if enough
            else (
                f"only {len(imported)} of {len(symbols)} symbols imported, and "
                f"the rule needs {crosssection.MIN_CROSS_SECTION} to rank. "
                "Measuring on this would measure a universe chosen by which "
                "requests succeeded, not the one the rule was tested on - "
                "re-run rather than measure"
            )
        ),
        "throttled": feed.throttled,
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


#: The ranked-universe instruments this broker actually offers, read from the
#: `molido_available.json` the bridge publishes rather than guessed. Twenty-eight
#: of the forty-nine; the rest the broker does not quote.
OFFERED = (
    "AUDCAD", "AUDCHF", "AUDJPY", "AUDNZD", "AUDUSD",
    "CADCHF", "CADJPY", "CHFJPY",
    "EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURJPY", "EURNZD", "EURUSD",
    "GBPAUD", "GBPCAD", "GBPCHF", "GBPJPY", "GBPNZD", "GBPUSD",
    "NZDCAD", "NZDCHF", "NZDJPY", "NZDUSD",
    "USDCAD", "USDCHF", "USDJPY",
)


def main(argv: list[str] | None = None) -> int:
    """Run a backfill from the command line.

    A real entry point rather than a shell one-liner, because this writes
    hundreds of thousands of rows and the arguments that decide how many
    should be visible in the command rather than buried in a quoted script.

    Defaults to daily from 2005, which is the cheap run: about 600 files and a
    few minutes. Hourly from 2015 is roughly 3,700 files and an hour, and is
    the one that matters - it is the timeframe the rule was measured on.

        python -m app.workers.deep_history
        python -m app.workers.deep_history --timeframe H1 --from 2015
        python -m app.workers.deep_history --symbols EURUSD,GBPUSD --dry-run
    """
    import argparse

    from app.db.session import session_scope

    parser = argparse.ArgumentParser(description="Backfill Dukascopy history.")
    parser.add_argument("--timeframe", default="D1", choices=["D1", "H1", "M1"])
    parser.add_argument("--from", dest="start_year", type=int, default=DEFAULT_START_YEAR)
    parser.add_argument(
        "--symbols",
        default=",".join(OFFERED),
        help="comma separated; defaults to the ranked universe this broker offers",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="verify each symbol's price scale and report, writing nothing",
    )
    args = parser.parse_args(argv)

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    timeframe = Timeframe(args.timeframe)

    if args.dry_run:
        # The scale check on its own. Worth having separately: it is the step
        # that decides whether the import is trustworthy, it costs one request
        # per symbol, and finding out that six instruments cannot be verified
        # is much cheaper before the other 3,700 requests than after.
        feed = DukascopyProvider()
        moment = datetime.now(UTC).replace(year=datetime.now(UTC).year - 1)
        with session_scope() as session:
            for symbol in symbols:
                instrument = session.scalar(
                    select(Instrument).where(Instrument.symbol == symbol)
                )
                known = (
                    None
                    if instrument is None
                    else reference_price(session, instrument.id)
                )
                if known is None:
                    print(f"{symbol:8} SKIP  no reference price to verify against")
                    continue
                try:
                    scale = feed.verify_scale(symbol, known, at=moment)
                except ProviderError as problem:
                    print(f"{symbol:8} FAIL  {problem}")
                else:
                    print(f"{symbol:8} ok    scale {scale:.0e} against {known:g}")
        return 0

    print(
        f"backfilling {len(symbols)} symbols, {timeframe.value}, "
        f"from {args.start_year}. Re-running is safe - it upserts."
    )
    with session_scope() as session:
        report = backfill(
            session,
            symbols=symbols,
            timeframe=timeframe,
            start_year=args.start_year,
        )

    print(f"written {report['written']} bars across {len(report['by_symbol'])} symbols")
    if report["throttled"]:
        print(f"  the feed asked us to slow down {report['throttled']} times")
    for symbol, count in sorted(report["by_symbol"].items()):
        print(f"  {symbol:8} {count:>8}")
    for note in report["skipped"]:
        print(f"  SKIPPED {note}")
    if report["periods_with_no_file"]:
        print(f"  {len(report['periods_with_no_file'])} periods had no file")
    if report["gave_up"]:
        print()
        print(f"STOPPED EARLY: {report['gave_up']}")
        return 3
    if report["universe_warning"]:
        # Non-zero exit. A partial import that returns success is how a
        # measurement ends up running on whatever arrived.
        print()
        print(f"INCOMPLETE: {report['universe_warning']}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
