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
import dataclasses
import math
import pathlib
from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.enums import AssetClass, Timeframe
from app.models.instruments import Instrument, Provider
from app.models.market_data import Bar
from app.providers.metatrader import DEFAULT_BRIDGE_DIR
from app.services.bar_revisions import append_only_bars
from app.workers import broker_offset

#: The provider these bars are recorded under. Separate from yfinance on
#: purpose - two sources writing one series means the last writer wins and the
#: disagreement is never seen.
PROVIDER_CODE = "metatrader"

#: MetaTrader writes `2026.08.14 07:53:24` in the terminal's own timezone and
#: publishes no offset for it.
#:
#: This said "which this deployment runs as GMT+0" and that was wrong. Aligning
#: EURUSD against the public feed puts the best match at +3, where the mean
#: absolute difference falls from 8.67 pips to 3.99. Every bar ingested under
#: the old assumption sat three hours in the future, and two things were
#: reported as findings because of it: the "33-39% of a stop distance" gap
#: between the two venues that justified measuring on both series, and an
#: hour's difference in the cross-section's instant that was explained as a
#: real session boundary.
#:
#: The offset is now measured per ingest rather than written down here. Most
#: brokers move with daylight saving - RoboForex is GMT+2 in winter and GMT+3
#: in summer - so a constant is right for six months and silently wrong for the
#: other six, which is the same failure it would be replacing.
STAMP_FORMAT = "%Y.%m.%d %H:%M:%S"

#: How many of the newest stored bars are still rewritten each cycle. The bar
#: that has just closed can be restated by the broker; bars five back cannot
#: in practice, and rewriting all 500 every pass was most of the cycle.
REWRITE_BARS = 5

#: How far back to look for what is already stored. A time constant lets the
#: planner skip old chunks; an instrument silent longer than this is simply
#: written in full, as it always was.
STORED_LOOKBACK = timedelta(days=30)

#: How old the newest reference M1 close may be, under the measured offset,
#: before the market counts as shut (or the terminal as stalled) and nothing is
#: written. EURUSD prints every minute while FX trades; ten minutes is far past
#: publish lag and quiet minutes, far short of the hour a wrong offset moves.
SHUT_MARKET_AGE = timedelta(minutes=10)


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


#: The timeframe whose alignment decides the broker's clock.
#:
#: The hourly file is the deepest the bridge publishes, and depth is what an
#: alignment needs: the faster files hold a few days and produce ties between
#: candidate offsets that are honestly refused. One measurement, taken where
#: the evidence is, applied to every timeframe from the same terminal.
OFFSET_REFERENCE_TIMEFRAME = Timeframe.H1


def _measure_offset(
    session: Session,
    root: pathlib.Path,
    timeframe: Timeframe,
    now: datetime | None = None,
) -> broker_offset.Offset:
    """Align the reference instrument's published rows against the public feed.

    Reads the file rather than the database so the first ingest can succeed.
    """
    path = root / f"molido_bars_{broker_offset.REFERENCE_SYMBOL}_{timeframe.value}.csv"
    if not path.exists():
        return broker_offset.Offset(
            None,
            0,
            None,
            None,
            f"the bridge publishes no {broker_offset.REFERENCE_SYMBOL} file, so "
            "there is nothing to align the broker's clock against",
        )

    published: dict[Any, float] = {}
    ambiguous: set[Any] = set()
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                try:
                    stamp = datetime.strptime(row["event_time"].strip(), STAMP_FORMAT).replace(
                        tzinfo=UTC
                    )
                    close = float(row["close"])
                except (TypeError, ValueError, KeyError, AttributeError):
                    continue
                if not math.isfinite(close):
                    continue
                if stamp in published and published[stamp] != close:
                    ambiguous.add(stamp)
                published[stamp] = close

    except (OSError, ValueError, KeyError) as problem:
        return broker_offset.Offset(
            None, 0, None, None, f"the reference file is unreadable: {problem}"
        )

    for stamp in ambiguous:
        published.pop(stamp, None)
    if not published:
        return broker_offset.align({}, published)
    # Widest lag either way, so every pairing align() could try is still read.
    reach = timedelta(hours=max(abs(lag) for lag in broker_offset.CANDIDATES) + 1)
    since = min(published) - reach
    public = broker_offset.public_closes(session, since=since)
    window = broker_offset.align(public, published)
    aligned = _prefer_recent(window, public, published)
    final = broker_offset.current(aligned, _latest_minute_close(root), now or datetime.now(UTC))
    if final.known and final.hours != window.hours:
        final = dataclasses.replace(
            final, valid_from=_move_boundary(public, published, old=window.hours, new=final.hours)
        )
    return final


#: A gap this long between two published bars is a market close (a weekend),
#: which is where brokers move their clocks.
WEEKEND_GAP = timedelta(hours=24)


def _move_boundary(
    public: dict[Any, float], published: dict[Any, float], *, old: int | None, new: int | None
) -> datetime | None:
    """Broker stamp of the first bar on the new clock, after a daylight-saving move.

    2026-10-25: the broker went from +3 to +2 over the weekend. A fit on the
    newest bars (or the live clock) gives +2, but the published window still
    holds three weeks of bars stamped at +3. Shifting all of them by +2 filed
    every older bar an hour early - onto the key of the real bar before it,
    with the next hour's prices (simulated against the live table on
    2026-10-31: 17,650 H1 and 10,289 M30 rows would have been overwritten).

    The move is placed at the newest weekend gap with the new clock fitting
    the bars after it and the old clock (or, when the whole window was too
    mixed to read, any other clock) fitting the week before it. If no gap
    proves it (a partial week, a thin public series), the newest weekend gap
    is used: only the current week is written at the new clock, and older
    bars, already stored, are left alone.
    """
    stamps = sorted(published)
    gaps = [i for i in range(1, len(stamps)) if stamps[i] - stamps[i - 1] >= WEEKEND_GAP]
    if not gaps:
        return stamps[0] if stamps else None
    for position in range(len(gaps) - 1, -1, -1):
        start = gaps[position]
        before_start = gaps[position - 1] if position > 0 else 0
        after = {s: published[s] for s in stamps[start:]}
        before = {s: published[s] for s in stamps[before_start:start]}
        earlier = broker_offset.align(public, before).hours
        if (
            broker_offset.align(public, after).hours == new
            and earlier is not None
            and earlier != new
            and (old is None or earlier == old)
        ):
            return stamps[start]
    return stamps[gaps[-1]]


#: Newest published reference bars that may overrule the whole window.
#:
#: The whole window (about twenty days of H1) keeps the pre-DST offset for a
#: week or more after a move. A terminal that publishes no fresh M1 file has no
#: live clock to correct it: b, d, e, f, g and j publish none, so they wrote
#: every H1 bar of the week after 2026-10-25 one hour early (+3 while the
#: broker read +2), and the main terminal, which has the live clock, wrote the
#: same bars at +2 - two clocks for one series. A fit on the newest bars alone
#: sees the move as soon as they are mostly on the new clock.
RECENT_BARS = 120


def _prefer_recent(
    aligned: broker_offset.Offset, public: dict[Any, float], published: dict[Any, float]
) -> broker_offset.Offset:
    """The newest bars' alignment when it is a clean one-hour move from the window's."""
    if len(published) <= RECENT_BARS:
        return aligned
    newest = dict(sorted(published.items())[-RECENT_BARS:])
    recent = broker_offset.align(public, newest)
    if (
        recent.hours is None
        or (
            aligned.hours is not None
            and abs(recent.hours - aligned.hours) != broker_offset.DST_STEP_HOURS
        )
        or recent.hours == aligned.hours
    ):
        return aligned
    was = "unknown" if aligned.hours is None else f"{aligned.hours:+d}h"
    return broker_offset.Offset(
        hours=recent.hours,
        overlap=recent.overlap,
        error_pips=recent.error_pips,
        runner_up_pips=recent.runner_up_pips,
        reason=(
            f"the newest {RECENT_BARS} bars align at {recent.hours:+d}h while the "
            f"whole window reads {was}; the newest bars win (daylight-saving move)"
        ),
    )


def _latest_minute_close(root: pathlib.Path) -> datetime | None:
    """Broker-stamped close of the newest reference M1 bar, or None.

    The window alignment keeps the old offset for days after a daylight-saving
    move; the live clock (broker_offset.current) sees it on the first bar.
    """
    name = f"molido_bars_{broker_offset.REFERENCE_SYMBOL}_{Timeframe.M1.value}.csv"
    path = root / name
    if not path.exists():
        # Host importers stage a few files as symlinks into a temp dir; the
        # terminal's own M1 file sits beside the real H1 file.
        anchor = (
            root
            / f"molido_bars_{broker_offset.REFERENCE_SYMBOL}_{OFFSET_REFERENCE_TIMEFRAME.value}.csv"
        )
        if anchor.is_symlink():
            path = anchor.resolve().parent / name
    newest = None
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                try:
                    stamp = datetime.strptime(row["event_time"].strip(), STAMP_FORMAT).replace(
                        tzinfo=UTC
                    )
                except (TypeError, ValueError, KeyError, AttributeError):
                    continue
                if newest is None or stamp > newest:
                    newest = stamp
    except OSError:
        return None
    return None if newest is None else newest + timedelta(minutes=1)


def _stamp(raw: str) -> datetime:
    """`2026.08.14 07:53:24` as an aware UTC-labelled datetime.

    Sliced rather than `strptime`'d on the exact layout the expert writes:
    the minute pass parses every row of every file, and `strptime` was most of
    its CPU. Anything that is not exactly that layout goes through `strptime`,
    so what is accepted and what is refused is unchanged.
    """
    text = raw.strip()
    if (
        len(text) == 19
        and text[4] == "."
        and text[7] == "."
        and text[10] == " "
        and text[13] == ":"
        and text[16] == ":"
        and text[:4].isdigit()
        and text[5:7].isdigit()
        and text[8:10].isdigit()
        and text[11:13].isdigit()
        and text[14:16].isdigit()
        and text[17:19].isdigit()
    ):
        return datetime(
            int(text[:4]),
            int(text[5:7]),
            int(text[8:10]),
            int(text[11:13]),
            int(text[14:16]),
            int(text[17:19]),
            tzinfo=UTC,
        )
    return datetime.strptime(text, STAMP_FORMAT).replace(tzinfo=UTC)




def ingest(
    session: Session,
    *,
    directory: pathlib.Path | str | None = None,
    timeframe: Timeframe = Timeframe.H1,
    now: datetime | None = None,
    offset: broker_offset.Offset | None = None,
    symbols: Collection[str] | None = None,
    skip_dead: bool = False,
) -> dict[str, Any]:
    """Read every bar file the bridge has written for this timeframe.

    Upserts on the natural key, so re-running over an overlapping window
    updates rather than duplicating - the bridge republishes the same 500 bars
    every cycle, and inserting them each time would multiply the series by the
    number of cycles.

    `offset` lets a caller that ingests several timeframes in one pass measure
    the broker's clock once instead of once per timeframe: the measurement
    reads the reference file and the public series, and on a loaded host that
    was repeated work for one terminal with one clock. `symbols` limits the
    files read, for a caller that only wants some. `skip_dead` leaves out a
    file whose newest bar is older than `STORED_LOOKBACK` for an instrument
    with nothing stored that recent - for a caller that runs every minute.
    """
    root = pathlib.Path(directory or DEFAULT_BRIDGE_DIR)
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        raise ValueError("evaluation clock must be timezone aware")
    moment = moment.astimezone(UTC)

    if not root.exists():
        return {
            "ingested": 0,
            "reason": f"the bridge directory {root} is not mounted here",
        }

    provider = _provider(session)

    # Measured from the files about to be read, not from what is already
    # stored. On a fresh deployment nothing is stored yet, so measuring from
    # the database can never succeed on the first pass and the ingest would
    # refuse forever.
    #
    # Without a known offset nothing is written at all. A wrong offset corrupts
    # every bar it touches and looks entirely normal doing it - which is what
    # the old GMT+0 constant did for three weeks.
    # One terminal has one clock. A short M15 alignment can confidently
    # disagree with deeper H1 evidence; accepting it shifts the same broker
    # by a different hour for each timeframe. Prefer the shared H1 anchor.
    if offset is None or not offset.known:
        offset = _measure_offset(session, root, OFFSET_REFERENCE_TIMEFRAME, moment)
    if not offset.known and timeframe is not OFFSET_REFERENCE_TIMEFRAME:
        offset = _measure_offset(session, root, timeframe, moment)
    if not offset.known:
        return {
            "ingested": 0,
            "reason": (
                "the broker's clock offset could not be measured, so no bar is "
                f"stored: {offset.reason}"
            ),
            "clock_offset": offset.as_dict(),
        }
    shift = timedelta(hours=offset.hours or 0)

    # A shut market or a stalled terminal has nothing new to write, and its
    # frozen bars are exactly where a wrong hour does damage: the window
    # alignment can trail a daylight-saving move by days, and on 2026-10-31
    # it read +3 while the broker ran +2. Rewriting the "unsettled" tail under
    # that hour would overwrite real bars with the next hour's prices. So when
    # the newest reference minute, under this offset, is older than
    # SHUT_MARKET_AGE, files are read and reported but nothing is written.
    latest_close = _latest_minute_close(root)
    reference_stale = latest_close is not None and moment - (latest_close - shift) > SHUT_MARKET_AGE

    # What is already stored, so settled bars are not rewritten every cycle.
    #
    # The bridge republishes its whole window - 500 hourly bars, 240 faster
    # ones - every twenty seconds, and each cycle upserted all of it: ~38,000
    # rows a pass, nearly every one identical to what was there, 88 s of a
    # 211 s cycle on production. Only the newest few bars can still be moving,
    # so rows older than the stored newest minus REWRITE_BARS are skipped.
    # Bounded to the recent past because a time constant is what lets the
    # planner skip old chunks; an instrument with nothing that recent is
    # written in full, as before.
    stored_newest: dict[Any, datetime] = {}
    for instrument_id, newest in session.execute(
        select(Bar.instrument_id, func.max(Bar.event_time))
        .where(
            Bar.provider_id == provider.id,
            Bar.timeframe == timeframe.value,
            Bar.event_time >= moment - STORED_LOOKBACK,
            Bar.event_time <= moment - timeframe.delta,
        )
        .group_by(Bar.instrument_id)
    ).all():
        if newest is not None:
            stored_newest[instrument_id] = (
                newest if newest.tzinfo is not None else newest.replace(tzinfo=UTC)
            )
    keep_back = timeframe.delta * REWRITE_BARS

    written = 0
    skipped_settled = 0
    skipped_shut = 0
    skipped_before_move = 0
    backfilled = 0
    backfill_since: datetime | None = None
    #: Newest closed bar each file holds, after the clock shift. What the
    #: broker has published, so a reader can tell "we fell behind the
    #: terminal" from "the terminal itself has nothing newer".
    published_newest: dict[str, datetime] = {}
    dead_files: list[str] = []
    files = 0
    failures: list[str] = []
    #: Half-written lines skipped. Counted rather than silent: a file that is
    #: mostly torn is a bridge problem, and a count is what shows that.
    torn = 0
    rejected = 0
    unclosed = 0
    duplicates = 0
    conflicts = 0

    pending: list[tuple[Any, list[dict[str, Any]]]] = []
    for path in sorted(root.glob(f"molido_bars_*_{timeframe.value}.csv")):
        symbol = path.name[len("molido_bars_") : -len(f"_{timeframe.value}.csv")]
        if not symbol:
            continue
        if symbols is not None and symbol not in symbols:
            continue
        files += 1

        try:
            instrument = _instrument(session, symbol)
            rows: list[dict[str, Any]] = []
            with path.open(newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    try:
                        broker_stamp = _stamp(row["event_time"])
                        stamp = broker_stamp - shift
                    except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
                        rejected += 1
                        if f"{symbol}: invalid timestamp" not in failures:
                            failures.append(f"{symbol}: invalid timestamp")
                        continue
                    if offset.valid_from is not None and broker_stamp < offset.valid_from:
                        # On the broker's old clock: stored already, at the
                        # right instant. Re-filing it at the new offset would
                        # overwrite the bar an hour earlier.
                        skipped_before_move += 1
                        continue
                    try:
                        prices = {
                            name: float(row[name]) for name in ("open", "high", "low", "close")
                        }
                        raw_volume = row.get("volume")
                        volume = (
                            None
                            if raw_volume is None or not raw_volume.strip()
                            else float(raw_volume)
                        )
                    except (TypeError, ValueError, KeyError, AttributeError):
                        torn += 1
                        rejected += 1
                        continue
                    if (
                        not all(math.isfinite(value) for value in prices.values())
                        or not prices["low"]
                        <= min(prices["open"], prices["close"])
                        <= max(prices["open"], prices["close"])
                        <= prices["high"]
                        or (volume is not None and (not math.isfinite(volume) or volume < 0))
                    ):
                        rejected += 1
                        continue
                    if stamp > moment or stamp + timeframe.delta > moment:
                        unclosed += 1
                        continue

                    rows.append(
                        {
                            "instrument_id": instrument.id,
                            "timeframe": timeframe.value,
                            "provider_id": provider.id,
                            "event_time": stamp,
                            "revision": 1,
                            "ingested_at": moment,
                            **prices,
                            "volume": volume,
                            "quality_score": 1.0,
                            "source_ref": f"metatrader:{symbol}:{timeframe.value}",
                        }
                    )
        except (OSError, ValueError, KeyError) as problem:
            # Named, not swallowed. A symbol that silently stops arriving looks
            # identical to one the broker stopped quoting.
            failures.append(f"{symbol}: {type(problem).__name__}")
            continue

        by_stamp: dict[Any, dict[str, Any]] = {}
        ambiguous_stamps: set[Any] = set()
        for row in rows:
            stamp = row["event_time"]
            if stamp in by_stamp:
                duplicates += 1
                if any(
                    row[name] != by_stamp[stamp][name]
                    for name in ("open", "high", "low", "close", "volume")
                ):
                    ambiguous_stamps.add(stamp)
            else:
                by_stamp[stamp] = row
        conflicts += len(ambiguous_stamps)
        rows = [row for stamp, row in by_stamp.items() if stamp not in ambiguous_stamps]

        if rows:
            newest_row = max(row["event_time"] for row in rows)
            if (
                skip_dead
                and newest_row < moment - STORED_LOOKBACK
                and instrument.id not in stored_newest
            ):
                # A file the terminal stopped writing long ago - an M1 file
                # left from 2024, a stock delisted from the expert. Rewriting
                # it every pass was most of a pass's rows and changed nothing;
                # it is named instead, because a symbol that silently stops
                # arriving looks identical to one the broker stopped quoting.
                dead_files.append(symbol)
                continue
            published_newest[symbol] = newest_row
        pending.append((instrument.id, rows))

    # Settled rows are skipped - unless the stored series has a hole where the
    # file has bars. The skip assumed every bar behind the rewrite window was
    # already stored, and a bar the terminal published late (a restart, a
    # refetch, a cycle that timed out) then never arrived at all: the floor
    # moved past it and nothing looked back. One grouped count per timeframe
    # compares what is stored inside each file's settled window with what the
    # file holds there; only an instrument that is short is written in full,
    # once, and the upsert makes that idempotent.
    windows: dict[Any, tuple[datetime, datetime, int]] = {}
    for instrument_id, rows in pending:
        newest_stored = stored_newest.get(instrument_id)
        if newest_stored is None or not rows:
            continue
        floor = newest_stored - keep_back
        settled = [row["event_time"] for row in rows if row["event_time"] < floor]
        if settled:
            windows[instrument_id] = (min(settled), max(settled), len(settled))
    stored_counts: dict[Any, int] = {}
    if windows:
        for instrument_id, count in session.execute(
            select(Bar.instrument_id, func.count())
            .where(
                Bar.provider_id == provider.id,
                Bar.timeframe == timeframe.value,
                Bar.event_time >= min(lo for lo, _, _ in windows.values()),
                or_(
                    *(
                        and_(
                            Bar.instrument_id == instrument_id,
                            Bar.event_time >= lo,
                            Bar.event_time <= hi,
                        )
                        for instrument_id, (lo, hi, _) in windows.items()
                    )
                ),
            )
            .group_by(Bar.instrument_id)
        ).all():
            stored_counts[instrument_id] = int(count)

    for instrument_id, rows in pending:
        newest_stored = stored_newest.get(instrument_id)
        if newest_stored is not None:
            window = windows.get(instrument_id)
            if window is not None and stored_counts.get(instrument_id, 0) < window[2]:
                # A hole: write the whole file for this instrument.
                backfilled += window[2] - stored_counts.get(instrument_id, 0)
                backfill_since = (
                    window[0] if backfill_since is None else min(backfill_since, window[0])
                )
            else:
                floor = newest_stored - keep_back
                fresh = [row for row in rows if row["event_time"] >= floor]
                skipped_settled += len(rows) - len(fresh)
                rows = fresh

        if reference_stale:
            skipped_shut += len(rows)
            continue

        if not rows:
            continue

        # The rows go as parameters, not baked into the statement. `.values(rows)`
        # built a fresh INSERT with ~13 bind parameters per bar - half a million
        # across a cycle - and compiled each one from scratch: profiled on
        # production at 133 s of a 227 s ingest, against 50 s actually
        # executing. One statement compiled once, rows sent in batches, writes
        # the same rows under the same conflict rule.
        written += append_only_bars(session, rows)

    # The caller owns commit/rollback, including validation of this report.
    session.flush()
    return {
        "ingested": written,
        "recorded": written,
        "skipped_settled": skipped_settled,
        "market_shut": reference_stale,
        "skipped_shut": skipped_shut,
        "skipped_before_move": skipped_before_move,
        "backfilled": backfilled,
        "backfill_since": None if backfill_since is None else backfill_since.isoformat(),
        "dead_files": dead_files,
        "published_newest": {
            symbol: stamp.isoformat() for symbol, stamp in sorted(published_newest.items())
        },
        "files": files,
        "torn_rows": torn,
        "rejected_rows": rejected,
        "unclosed_rows": unclosed,
        "duplicate_rows": duplicates,
        "conflicting_timestamps": conflicts,
        "provider": PROVIDER_CODE,
        "clock_offset": offset.as_dict(),
        "failures": failures,
        "note": (
            "recorded under the metatrader provider rather than merged with the "
            "public feed. Spreads and session boundaries differ, and two sources "
            "writing one series means the last writer wins and the disagreement "
            "is never seen"
        ),
    }
