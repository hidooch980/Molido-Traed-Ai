"""Every timeframe of the broker's bars, kept current every minute.

The terminal publishes M1, M5, M15, M30 and H1 files on a twenty-second timer,
built by the terminal from its own ticks. Until now the collector read three of
them once every fifteen minutes, and three host timers each started a fresh
interpreter inside the api container every minute to read a few more for two
symbols. So most symbols had no current M1, nothing had H3, H4 or a broker
D1, and nothing said which series were behind.

This is one in-process pass, run every minute by the worker:

1. **Ingest** every published timeframe for every symbol the terminal writes,
   measuring the broker's clock once for all of them.
2. **Backfill** holes: `broker_bars.ingest` now notices when a settled window
   holds fewer stored bars than the file and rewrites that instrument once.
3. **Derive** H3, H4 and D1 from the broker's H1, and M30 from M5 for symbols
   the terminal publishes no M30 file for - aligned on the *broker's* day, so
   they are the candles the terminal itself shows, under their own provider so
   an observed bar and a computed one can always be told apart.
4. **Measure freshness** per symbol and timeframe, in open-market time, so a
   reader can refuse a series that has fallen behind.

Only closed bars are stored. The forming bar moves until it closes, and a
decision taken on it is a decision on a price that has not finished happening.
Nothing here sends, changes or reads an order.
"""

from __future__ import annotations

import math
import pathlib
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.enums import Timeframe
from app.models.instruments import Instrument, Provider
from app.models.market_data import Bar
from app.services.bar_revisions import append_only_bars, latest_bar_query
from app.workers import broker_bars

#: What the terminal's expert writes, finest first.
PUBLISHED_TIMEFRAMES: tuple[Timeframe, ...] = (
    Timeframe.M1,
    Timeframe.M5,
    Timeframe.M15,
    Timeframe.M30,
    Timeframe.H1,
)

#: Built here, from a finer broker series: target -> (source, minimum parts).
#:
#: A bucket needs enough of its parts to describe the period. H3 and H4 take
#: two-thirds and half, because an index or a stock that opens mid-bucket is
#: still a real candle on the terminal. A day takes twelve hours, the same
#: floor `aggregate.py` uses: Friday closes early and Sunday opens late, and a
#: day of three hours is not a quiet day, it is an unmeasured one. M30 from M5
#: takes all six; it only fills symbols the terminal publishes no M30 for.
DERIVED: dict[Timeframe, tuple[Timeframe, int]] = {
    Timeframe.M30: (Timeframe.M5, 6),
    Timeframe.H3: (Timeframe.H1, 2),
    Timeframe.H4: (Timeframe.H1, 2),
    Timeframe.D1: (Timeframe.H1, 12),
}

#: Every timeframe this keeps current.
LIVE_TIMEFRAMES: tuple[Timeframe, ...] = (
    Timeframe.M1,
    Timeframe.M5,
    Timeframe.M15,
    Timeframe.M30,
    Timeframe.H1,
    Timeframe.H3,
    Timeframe.H4,
    Timeframe.D1,
)

#: Derived bars are recorded here, never under the observed provider.
DERIVED_PROVIDER = "metatrader-derived"

#: How far back the first derivation reads its source. After that only the
#: newest few buckets are rebuilt.
DERIVE_LOOKBACK: dict[Timeframe, timedelta] = {
    Timeframe.M30: timedelta(days=3),
    Timeframe.H3: timedelta(days=21),
    Timeframe.H4: timedelta(days=21),
    Timeframe.D1: timedelta(days=30),
}

#: Buckets behind the newest derived one that are rebuilt each pass, because
#: their source bars can still be restated or backfilled.
RESTATE_BUCKETS = 2

#: The terminal publishes every twenty seconds and this runs once a minute, so
#: a bar that has just closed can take this long to be stored without anything
#: being wrong.
PUBLISH_GRACE = timedelta(seconds=120)

#: Beyond this many bars of open-market time a series is stale. The same number
#: `app.ops.freshness` and the risk brain use.
MAX_AGE_BARS = 3.0

#: Series with nothing in this long are reported absent, not aged.
FRESHNESS_LOOKBACK = timedelta(days=45)

#: Statuses a decision may be taken on. "idle" means the terminal itself has
#: nothing newer - a session that has closed for the day, which is not a
#: failure of this pipeline and is left to the cross-section's own rules.
DECIDABLE = frozenset({"fresh", "idle"})

#: The worker's advisory lock, so two passes never write the same rows at once.
LOCK_KEY = 0x6D6C6261  # "mlba"


# ----------------------------------------------------------------- the clock


def broker_local(stamp: datetime, shift_hours: int) -> datetime:
    return stamp.astimezone(UTC) + timedelta(hours=shift_hours)


def bucket_start(stamp: datetime, timeframe: Timeframe, shift_hours: int) -> datetime:
    """Start of the bucket holding `stamp`, aligned on the broker's own clock.

    The terminal draws H4 and D1 from its server midnight, not from UTC's, so a
    UTC-aligned H4 would be a candle nobody looking at the chart has seen.
    """
    seconds = int(timeframe.delta.total_seconds())
    shift = shift_hours * 3600
    epoch = int(stamp.astimezone(UTC).timestamp())
    start = (epoch + shift) // seconds * seconds - shift
    return datetime.fromtimestamp(start, tz=UTC)


def market_open(moment: datetime, shift_hours: int) -> bool:
    """FX trades Monday 00:00 to Friday 24:00 on the broker's clock.

    RoboForex and FTMO both run their server on New York close plus seven, so
    the broker's weekend is exactly the FX weekend.
    """
    return broker_local(moment, shift_hours).weekday() < 5


def open_seconds(start: datetime, end: datetime, shift_hours: int) -> float:
    """Seconds between two instants that fall on broker weekdays.

    Freshness is judged in market time. A Friday bar read on a Saturday is the
    newest there is, and charging it the weekend calls a shut market stale.
    """
    if end <= start:
        return 0.0
    total = 0.0
    cursor = start
    # Bounded: a series silent for longer than the lookback is absent anyway.
    limit = start + FRESHNESS_LOOKBACK + timedelta(days=2)
    end = min(end, limit)
    while cursor < end:
        local = broker_local(cursor, shift_hours)
        next_midnight_local = (local + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        boundary = min(end, next_midnight_local - timedelta(hours=shift_hours))
        boundary = boundary.astimezone(UTC)
        if local.weekday() < 5:
            total += (boundary - cursor).total_seconds()
        cursor = boundary
    return total


# ------------------------------------------------------------------- folding


def fold(
    rows: Iterable[dict[str, Any]],
    *,
    target: Timeframe,
    source: Timeframe,
    shift_hours: int,
    now: datetime,
    min_parts: int,
) -> list[dict[str, Any]]:
    """Closed `target` bars from `source` bars of one instrument.

    Only buckets that have closed by `now` are emitted. Parts must sit on the
    source grid and be coherent; a bucket with too few is skipped rather than
    emitted as a candle that describes a fraction of its period.
    """
    if now.tzinfo is None:
        raise ValueError("evaluation clock must be timezone aware")
    now = now.astimezone(UTC)
    expected = int(target.delta / source.delta)
    groups: dict[datetime, dict[datetime, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        stamp = row["event_time"]
        if stamp.tzinfo is None:
            raise ValueError("bar clock must be timezone aware")
        stamp = stamp.astimezone(UTC)
        if bucket_start(stamp, source, shift_hours) != stamp:
            continue
        values = [row.get(name) for name in ("open", "high", "low", "close")]
        try:
            o, h, lo, c = (float(v) for v in values)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(v) and v > 0 for v in (o, h, lo, c)):
            continue
        if lo > min(o, c) or h < max(o, c):
            continue
        groups[bucket_start(stamp, target, shift_hours)][stamp] = {
            "event_time": stamp,
            "open": o,
            "high": h,
            "low": lo,
            "close": c,
            "volume": row.get("volume"),
        }

    built: list[dict[str, Any]] = []
    for start, parts_by_stamp in sorted(groups.items()):
        if start + target.delta > now or len(parts_by_stamp) < min_parts:
            continue
        parts = [parts_by_stamp[key] for key in sorted(parts_by_stamp)]
        volumes = [p["volume"] for p in parts if p["volume"] is not None]
        built.append(
            {
                "event_time": start,
                "open": parts[0]["open"],
                "high": max(p["high"] for p in parts),
                "low": min(p["low"] for p in parts),
                "close": parts[-1]["close"],
                "volume": float(sum(float(v) for v in volumes)) if volumes else None,
                "quality_score": round(min(len(parts) / expected, 1.0), 4),
                "parts": len(parts),
            }
        )
    return built


def _provider_id(session: Session, code: str, *, create: bool) -> Any:
    row = session.scalar(select(Provider).where(Provider.code == code))
    if row is None and create:
        row = Provider(
            code=code,
            name="Derived from the broker's own bars",
            capabilities={"ohlcv": True, "derived": True},
        )
        session.add(row)
        session.flush()
    return None if row is None else row.id


def _aware(stamp: datetime) -> datetime:
    return stamp if stamp.tzinfo is not None else stamp.replace(tzinfo=UTC)




def derive(
    session: Session,
    target: Timeframe,
    *,
    now: datetime,
    shift_hours: int,
    since: datetime | None = None,
    only_symbols: Iterable[str] | None = None,
    skip_symbols: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Build closed `target` bars from the stored broker series and upsert them.

    Per instrument, only buckets from its newest derived bar minus
    `RESTATE_BUCKETS` are rebuilt, so a steady pass reads a few hours of
    source rather than weeks. `since` reaches further back when the source
    was just backfilled.
    """
    source, min_parts = DERIVED[target]
    moment = now.astimezone(UTC)
    observed = _provider_id(session, broker_bars.PROVIDER_CODE, create=False)
    if observed is None:
        return {"derived": 0, "reason": "no broker bars are stored yet"}
    derived = _provider_id(session, DERIVED_PROVIDER, create=True)

    instruments = dict(session.execute(select(Instrument.id, Instrument.symbol)).all())
    wanted = set(instruments)
    if only_symbols is not None:
        names = set(only_symbols)
        wanted = {i for i in wanted if instruments[i] in names}
    if skip_symbols is not None:
        names = set(skip_symbols)
        wanted = {i for i in wanted if instruments[i] not in names}
    if not wanted:
        return {"derived": 0, "instruments": 0}

    floor = moment - DERIVE_LOOKBACK[target]
    newest_derived = dict(
        session.execute(
            select(Bar.instrument_id, func.max(Bar.event_time))
            .where(
                Bar.provider_id == derived,
                Bar.timeframe == target.value,
                Bar.event_time >= floor,
            )
            .group_by(Bar.instrument_id)
        ).all()
    )
    starts: dict[Any, datetime] = {}
    for instrument_id in wanted:
        newest = newest_derived.get(instrument_id)
        start = (
            floor if newest is None else max(floor, _aware(newest) - target.delta * RESTATE_BUCKETS)
        )
        if since is not None:
            start = max(floor, min(start, bucket_start(since, target, shift_hours)))
        starts[instrument_id] = start
    read_from = min(starts.values())

    source_rows: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    source_bars = session.scalars(latest_bar_query(
        Bar.provider_id == observed,
        Bar.timeframe == source.value,
        Bar.event_time >= read_from,
        Bar.event_time <= moment - source.delta,
        Bar.ingested_at <= moment,
        Bar.instrument_id.in_(wanted),
    )).all()
    for bar in source_bars:
        instrument_id, stamp = bar.instrument_id, bar.event_time
        o, h, lo, c, v = bar.open, bar.high, bar.low, bar.close, bar.volume
        stamp = _aware(stamp)
        if stamp < starts[instrument_id]:
            continue
        source_rows[instrument_id].append(
            {"event_time": stamp, "open": o, "high": h, "low": lo, "close": c, "volume": v}
        )

    written = 0
    for instrument_id, rows in source_rows.items():
        bars = fold(
            rows,
            target=target,
            source=source,
            shift_hours=shift_hours,
            now=moment,
            min_parts=min_parts,
        )
        payload = [
            {
                "instrument_id": instrument_id,
                "timeframe": target.value,
                "provider_id": derived,
                "event_time": bar["event_time"],
                "revision": 1,
                "ingested_at": moment,
                "open": bar["open"],
                "high": bar["high"],
                "low": bar["low"],
                "close": bar["close"],
                "volume": bar["volume"],
                "quality_score": bar["quality_score"],
                "source_ref": f"derived:{source.value}->{target.value}:broker+{shift_hours}h",
            }
            for bar in bars
            if bar["event_time"] >= bucket_start(starts[instrument_id], target, shift_hours)
        ]
        if payload:
            written += append_only_bars(session, payload)
    session.flush()
    return {
        "derived": written,
        "instruments": len(source_rows),
        "source": source.value,
        "read_from": read_from.isoformat(),
    }


# ----------------------------------------------------------------- freshness


@dataclass(frozen=True)
class SeriesFreshness:
    symbol: str
    timeframe: Timeframe
    provider: str
    last_event_time: datetime | None
    lag_seconds: float | None
    status: str

    @property
    def decidable(self) -> bool:
        return self.status in DECIDABLE

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "last_event_time": None
            if self.last_event_time is None
            else self.last_event_time.isoformat(),
            "lag_seconds": None if self.lag_seconds is None else round(self.lag_seconds, 1),
            "status": self.status,
        }


def classify(
    *,
    timeframe: Timeframe,
    last_event_time: datetime | None,
    now: datetime,
    shift_hours: int,
    published_newest: datetime | None = None,
) -> tuple[str, float | None]:
    """One series' status and its lag in open-market seconds.

    - fresh: the newest bar that could have closed is stored (within grace).
    - behind: the terminal has published a newer closed bar than is stored.
    - idle: nothing newer at the terminal either - the session is closed.
    - late: up to `MAX_AGE_BARS` bars of market time old, cause unknown.
    - stale: older than that.
    - absent: nothing stored.
    """
    if last_event_time is None:
        return "absent", None
    last = _aware(last_event_time)
    lag = open_seconds(last + timeframe.delta, now, shift_hours)
    if published_newest is not None and _aware(published_newest) > last:
        return "behind", lag
    if lag <= (timeframe.delta + PUBLISH_GRACE).total_seconds():
        return "fresh", lag
    if published_newest is not None:
        return "idle", lag
    if lag <= (timeframe.delta * MAX_AGE_BARS + PUBLISH_GRACE).total_seconds():
        return "late", lag
    return "stale", lag


def infer_shift(session: Session, now: datetime | None = None) -> int | None:
    """The broker's offset, read back from the daily bars this pass derived.

    A derived D1 starts at broker midnight, so its UTC hour is the offset. Lets
    a reader without the bridge (the API) align on the broker's day.
    """
    derived = _provider_id(session, DERIVED_PROVIDER, create=False)
    if derived is None:
        return None
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    newest = session.scalar(
        select(func.max(Bar.event_time)).where(
            Bar.provider_id == derived,
            Bar.timeframe == Timeframe.D1.value,
            # A time constant, so the planner reads recent chunks only.
            Bar.event_time >= moment - timedelta(days=10),
            Bar.event_time <= moment,
        )
    )
    if newest is None:
        return None
    return (24 - _aware(newest).hour) % 24


def measure_freshness(
    session: Session,
    *,
    now: datetime,
    shift_hours: int,
    published: dict[Timeframe, dict[str, datetime]] | None = None,
    timeframes: Iterable[Timeframe] = LIVE_TIMEFRAMES,
) -> dict[tuple[str, Timeframe], SeriesFreshness]:
    """Every (symbol, timeframe) the broker series covers, and how current it is.

    Observed bars are preferred; a derived bar answers only where the terminal
    publishes none, which is how a missing M30 file is still covered.
    Two grouped queries, both bounded by a time constant.
    """
    moment = now.astimezone(UTC)
    wanted = [tf.value for tf in timeframes]
    newest: dict[tuple[str, str], tuple[datetime, str]] = {}
    for code in (broker_bars.PROVIDER_CODE, DERIVED_PROVIDER):
        provider_id = _provider_id(session, code, create=False)
        if provider_id is None:
            continue
        for symbol, timeframe, stamp in session.execute(
            select(Instrument.symbol, Bar.timeframe, func.max(Bar.event_time))
            .join(Instrument, Instrument.id == Bar.instrument_id)
            .where(
                Bar.provider_id == provider_id,
                Bar.timeframe.in_(wanted),
                Bar.event_time >= moment - FRESHNESS_LOOKBACK,
                Bar.event_time <= moment,
            )
            .group_by(Instrument.symbol, Bar.timeframe)
        ).all():
            key = (symbol, str(timeframe))
            held = newest.get(key)
            # Observed beats derived for the same series; derived only fills.
            if held is None or (
                held[1] != broker_bars.PROVIDER_CODE and code == broker_bars.PROVIDER_CODE
            ):
                newest[key] = (_aware(stamp), code)

    symbols = sorted({symbol for symbol, _ in newest})
    for frames in (published or {}).values():
        symbols = sorted(set(symbols) | set(frames))
    report: dict[tuple[str, Timeframe], SeriesFreshness] = {}
    for symbol in symbols:
        for timeframe in timeframes:
            stored = newest.get((symbol, timeframe.value))
            last, code = (None, broker_bars.PROVIDER_CODE) if stored is None else stored
            source_newest = None
            if code == broker_bars.PROVIDER_CODE and published is not None:
                source_newest = (published.get(timeframe) or {}).get(symbol)
            status, lag = classify(
                timeframe=timeframe,
                last_event_time=last,
                now=moment,
                shift_hours=shift_hours,
                published_newest=source_newest,
            )
            report[(symbol, timeframe)] = SeriesFreshness(
                symbol, timeframe, code, last, lag, status
            )
    return report


def summarise(report: dict[tuple[str, Timeframe], SeriesFreshness]) -> dict[str, Any]:
    """Counts per timeframe, and the names of every series not decidable."""
    by_timeframe: dict[str, dict[str, Any]] = {}
    for (symbol, timeframe), series in sorted(
        report.items(), key=lambda item: (item[0][1].delta, item[0][0])
    ):
        entry = by_timeframe.setdefault(timeframe.value, {"counts": {}, "not_decidable": []})
        entry["counts"][series.status] = entry["counts"].get(series.status, 0) + 1
        if not series.decidable:
            entry["not_decidable"].append(f"{symbol}:{series.status}")
    return by_timeframe


# --------------------------------------------------------------------- a pass


def _locked(session: Session) -> bool:
    """Take the pass's advisory lock for this transaction; SQLite has none."""
    if session.get_bind().dialect.name != "postgresql":
        return True
    return bool(session.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": LOCK_KEY}))


def _parse_published(report: dict[str, Any]) -> dict[str, datetime]:
    parsed: dict[str, datetime] = {}
    for symbol, stamp in (report.get("published_newest") or {}).items():
        try:
            parsed[symbol] = _aware(datetime.fromisoformat(stamp))
        except (TypeError, ValueError):
            continue
    return parsed


#: A file unchanged since the last pass is not read again - for this long.
#: After it, every file is read once more whatever its timestamp says, so a
#: pass whose commit failed cannot leave a file skipped for good.
RESCAN_EVERY = timedelta(minutes=10)


@dataclass
class FileCache:
    """What the worker has already read, kept between passes in its memory.

    Most files do not change from one minute to the next: forty-two of the
    main terminal's forty-four M1 files were last written in 2024, and the
    hourly ones change once an hour. Parsing all 214 every minute was most of
    a pass's CPU on a host already at a load of 25.
    """

    seen: dict[str, tuple[float, int, datetime]]
    published: dict[tuple[str, str], datetime]
    #: target timeframe -> (newest source bar it was built from, when).
    derived: dict[str, tuple[datetime | None, datetime]]

    @classmethod
    def empty(cls) -> FileCache:
        return cls({}, {}, {})

    def derive_due(
        self,
        target: Timeframe,
        source_newest: datetime | None,
        moment: datetime,
        backfilled: bool,
    ) -> bool:
        """Whether a derived timeframe can have changed since it was last built.

        A derived bar changes only when its source gains a bar. The hourly
        file is rewritten every twenty seconds, but its newest closed bar
        moves once an hour - so rebuilding H3, H4 and D1 every minute redid
        the same fold fifty-nine times in sixty.
        """
        before = self.derived.get(target.value)
        return (
            backfilled
            or before is None
            or before[0] != source_newest
            or moment - before[1] >= RESCAN_EVERY
        )

    def changed(
        self, root: pathlib.Path, timeframe: Timeframe, moment: datetime
    ) -> tuple[set[str], dict[str, tuple[str, float, int]]]:
        """Symbols whose file must be read this pass, and every file's stat."""
        changed: set[str] = set()
        stats: dict[str, tuple[str, float, int]] = {}
        suffix = f"_{timeframe.value}.csv"
        for path in root.glob(f"molido_bars_*{suffix}"):
            symbol = path.name[len("molido_bars_") : -len(suffix)]
            try:
                stat = path.stat()
            except OSError:
                changed.add(symbol)
                continue
            stats[symbol] = (str(path), stat.st_mtime, stat.st_size)
            before = self.seen.get(str(path))
            if (
                before is None
                or before[0] != stat.st_mtime
                or before[1] != stat.st_size
                or moment - before[2] >= RESCAN_EVERY
            ):
                changed.add(symbol)
        return changed, stats

    def remember(
        self,
        timeframe: Timeframe,
        symbols: set[str],
        stats: dict[str, tuple[str, float, int]],
        published: dict[str, datetime],
        moment: datetime,
    ) -> dict[str, datetime]:
        """Record what was read; return the newest published bar of every file."""
        for symbol in symbols:
            if symbol in stats:
                path, mtime, size = stats[symbol]
                self.seen[path] = (mtime, size, moment)
            if symbol in published:
                self.published[(timeframe.value, symbol)] = published[symbol]
        return {
            symbol: stamp
            for (frame, symbol), stamp in self.published.items()
            if frame == timeframe.value and symbol in stats
        }


#: The worker's own cache. Module state on purpose: the worker process lives
#: for days and runs a pass every minute.
WORKER_CACHE = FileCache.empty()


def refresh(
    session: Session,
    *,
    directory: pathlib.Path | str,
    now: datetime,
    timeframes: Iterable[Timeframe] = PUBLISHED_TIMEFRAMES,
    cache: FileCache | None = None,
) -> dict[str, Any]:
    """One pass over one terminal's files: ingest, backfill, derive, measure.

    Each step runs in its own savepoint, so a malformed M1 file cannot roll
    back the hourly bars. The caller commits. With a `cache`, files unchanged
    since the last pass are not parsed again.
    """
    if now.tzinfo is None:
        raise ValueError("evaluation clock must be timezone aware")
    moment = now.astimezone(UTC)
    root = pathlib.Path(directory)
    if not _locked(session):
        return {"skipped": True, "reason": "another live-bars pass holds the lock"}

    offset = broker_bars._measure_offset(
        session, root, broker_bars.OFFSET_REFERENCE_TIMEFRAME, moment
    )
    if not offset.known:
        return {
            "recorded": 0,
            "reason": f"the broker's clock offset could not be measured: {offset.reason}",
            "clock_offset": offset.as_dict(),
        }
    shift = int(offset.hours or 0)

    ingested: dict[str, Any] = {}
    published: dict[Timeframe, dict[str, datetime]] = {}
    for timeframe in timeframes:
        wanted: set[str] | None = None
        stats: dict[str, tuple[str, float, int]] = {}
        if cache is not None:
            wanted, stats = cache.changed(root, timeframe, moment)
        try:
            with session.begin_nested():
                report = broker_bars.ingest(
                    session,
                    directory=root,
                    timeframe=timeframe,
                    now=moment,
                    offset=offset,
                    symbols=wanted,
                    skip_dead=True,
                )
        except Exception as problem:  # noqa: BLE001 - reported, never fatal
            ingested[timeframe.value] = {"recorded": 0, "reason": type(problem).__name__}
            continue
        published[timeframe] = _parse_published(report)
        if cache is not None and wanted is not None:
            published[timeframe] = cache.remember(
                timeframe, wanted, stats, published[timeframe], moment
            )
        ingested[timeframe.value] = {
            key: report.get(key)
            for key in (
                "recorded",
                "skipped_settled",
                "backfilled",
                "files",
                "failures",
                "dead_files",
            )
        }
        ingested[timeframe.value]["backfill_since"] = report.get("backfill_since")

    derived: dict[str, Any] = {}
    for target, (source, _) in DERIVED.items():
        since_raw = (ingested.get(source.value) or {}).get("backfill_since")
        since = _aware(datetime.fromisoformat(since_raw)) if since_raw else None
        kwargs: dict[str, Any] = {}
        if target is Timeframe.M30:
            # Only where the terminal writes no M30 of its own.
            have = set(published.get(Timeframe.M30) or {})
            if not published.get(Timeframe.M5):
                continue
            kwargs["only_symbols"] = set(published[Timeframe.M5]) - have
            if not kwargs["only_symbols"]:
                continue
        source_newest = max((published.get(source) or {}).values(), default=None)
        if cache is not None and not cache.derive_due(
            target, source_newest, moment, backfilled=since is not None
        ):
            derived[target.value] = {"derived": 0, "reason": "source unchanged"}
            continue
        try:
            with session.begin_nested():
                derived[target.value] = derive(
                    session, target, now=moment, shift_hours=shift, since=since, **kwargs
                )
        except Exception as problem:  # noqa: BLE001 - reported, never fatal
            derived[target.value] = {"derived": 0, "reason": type(problem).__name__}
            continue
        if cache is not None:
            cache.derived[target.value] = (source_newest, moment)

    freshness = measure_freshness(session, now=moment, shift_hours=shift, published=published)
    return {
        "recorded": sum(int((r or {}).get("recorded") or 0) for r in ingested.values()),
        "derived": sum(int((r or {}).get("derived") or 0) for r in derived.values()),
        "ingested": ingested,
        "derived_by_timeframe": derived,
        "clock_offset_hours": shift,
        "market_open": market_open(moment, shift),
        "freshness": summarise(freshness),
    }


def decidable_symbols(
    session: Session,
    timeframe: Timeframe,
    *,
    now: datetime,
    shift_hours: int | None = None,
) -> dict[str, SeriesFreshness]:
    """The broker series a brain may decide on at `timeframe`, by symbol.

    For a caller without the bridge's files: "behind" cannot be told from
    "idle" here, so a series older than one bar of market time reads late or
    stale and is left out. `shift_hours` defaults to what the derived daily
    bars say, and to zero when there are none yet.
    """
    shift = infer_shift(session, now) if shift_hours is None else shift_hours
    report = measure_freshness(session, now=now, shift_hours=shift or 0, timeframes=(timeframe,))
    return {symbol: series for (symbol, _), series in report.items() if series.decidable}
