"""Continuous data collection.

This is what actually runs on the server between now and the day the cognitive
brain exists: it keeps pulling bars, scoring their quality, and materializing
features, so that when the later phases arrive they inherit real history rather
than starting from an empty database.

Design notes that matter operationally:

* **Closed markets are skipped, not polled.** Asking a provider for EURUSD at
  03:00 Sunday wastes quota and, worse, writes nothing — which is
  indistinguishable in the logs from a broken feed. The session calendar
  already knows the answer.
* **Each cycle is independently safe to repeat.** Ingestion is idempotent by
  window key and features are skipped when already present, so a crash, a
  restart, or two overlapping cycles cannot duplicate data.
* **One failing instrument does not stop the sweep.** Provider errors are
  recorded per entry and the loop continues; a single delisted symbol must not
  halt collection for everything else.
* **Nothing here decides anything.** The collector writes data. No trading
  logic, no risk decision, no order — those layers do not exist yet, and this
  process must never grow them by accident.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.enums import AuditEventType, Severity, Timeframe
from app.core.errors import InsufficientDataError, MolidoError
from app.core.logging import bind_trace, configure_logging, get_logger
from app.db.session import session_scope
from app.models.instruments import Instrument, Provider
from app.models.market_data import Bar
from app.providers.base import MarketDataProvider
from app.providers.registry import get_provider, install_defaults, register
from app.services import (
    audit,
    data_quality,
    episodes,
    feature_store,
    ingestion,
    retention,
    sessions,
    symbol_dna,
)
from app.services.instruments import get_instrument_by_symbol, upsert_instrument
from app.workers.watchlist import WatchEntry, parse_watchlist

log = get_logger(__name__)

# How far back an ordinary cycle asks for. Generous on purpose: providers
# revise recent candles, and re-fetching a few is cheap, while missing a
# revision leaves a wrong bar in the record permanently.
REFRESH_WINDOW = timedelta(days=3)

# First-run backfill depth per timeframe. Intraday history is short and heavy;
# daily history is long and light.
BACKFILL_DEPTH: dict[Timeframe, timedelta] = {
    Timeframe.M1: timedelta(days=7),
    Timeframe.M5: timedelta(days=55),
    Timeframe.M15: timedelta(days=55),
    Timeframe.M30: timedelta(days=55),
    Timeframe.H1: timedelta(days=680),
    Timeframe.H4: timedelta(days=680),
    Timeframe.D1: timedelta(days=365 * 15),
    Timeframe.W1: timedelta(days=365 * 25),
    Timeframe.MN1: timedelta(days=365 * 30),
}


@dataclass
class CycleReport:
    started_at: datetime
    entries: int = 0
    skipped_closed: int = 0
    ingested: int = 0
    written: int = 0
    features_written: int = 0
    #: Feeds that produced no recent bar. Counted separately from failures: a
    #: stale feed is not a failed fetch, and collapsing them would hide a
    #: symbol that went quiet behind a cycle that reported success.
    stale_findings: int = 0
    failures: list[str] = field(default_factory=list)

    def as_payload(self) -> dict[str, Any]:
        return {
            "entries": self.entries,
            "skipped_closed": self.skipped_closed,
            "ingested": self.ingested,
            "bars_written": self.written,
            "features_written": self.features_written,
            "stale_findings": self.stale_findings,
            "failures": self.failures[:10],
            "failure_count": len(self.failures),
        }


def _resolve_provider() -> MarketDataProvider:
    """The configured collection adapter.

    yfinance is registered lazily here rather than in `install_defaults`,
    because that helper is also used by tests and the CLI, and a provider that
    reaches the internet must never be installed by accident.
    """
    settings = get_settings()
    install_defaults()
    code = settings.collector_provider

    if code == "yfinance":
        from app.providers.yfinance_provider import YFinanceProvider

        provider = YFinanceProvider()
        register(provider)
        return provider
    return get_provider(code)


def run_cycle(entries: list[WatchEntry] | None = None) -> CycleReport:
    """One full sweep of the watchlist. Synchronous and idempotent."""
    settings = get_settings()
    entries = entries or parse_watchlist(settings.watchlist)
    provider = _resolve_provider()
    report = CycleReport(started_at=datetime.now(UTC), entries=len(entries))
    now = datetime.now(UTC)

    for entry in entries:
        try:
            with session_scope() as session:
                instrument = upsert_instrument(session, entry.symbol)
                calendar = sessions.build_calendar(session, instrument)

                # A market that has been closed for the whole refresh window has
                # nothing new to give. Still poll if it closed recently, since
                # the final bars of a session often arrive late.
                if not calendar.is_open(now) and not calendar.is_open(
                    now - timedelta(hours=6)
                ):
                    report.skipped_closed += 1
                    log.debug("collector.skipped_closed", symbol=entry.symbol)
                    continue

                provider_row = ingestion.get_or_create_provider(
                    session,
                    code=provider.code,
                    name=provider.name,
                    capabilities=provider.capabilities().as_dict(),
                    trust_weight=0.4,
                )

                start = _window_start(session, instrument, provider_row.id, entry, now)
                result = ingestion.ingest_ohlcv(
                    session,
                    provider=provider,
                    provider_row=provider_row,
                    instrument=instrument,
                    timeframe=entry.timeframe,
                    start=start,
                    end=now,
                    raw_symbol=entry.raw_symbol,
                )
                report.ingested += 1
                report.written += result.written

                if result.error:
                    report.failures.append(f"{entry.key}: {result.error}")

                # Features follow immediately: a bar without its features is a
                # gap the next phase would have to backfill anyway.
                if result.written:
                    report.features_written += _materialize(
                        session, instrument, entry.timeframe, now
                    )

                # Checked on every cycle, including the ones that wrote
                # nothing. A cycle that fetched no bars is the case this exists
                # for, so running it only after a successful write would skip
                # exactly the symbol that went quiet.
                report.stale_findings += _record_staleness(
                    session, instrument, provider_row.id, entry.timeframe, now
                )
        except MolidoError as exc:
            report.failures.append(f"{entry.key}: {exc.code}: {exc.message}")
            log.error("collector.entry_failed", entry=entry.key, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - one bad symbol must not stop the sweep
            report.failures.append(f"{entry.key}: {type(exc).__name__}: {exc}")
            log.error("collector.entry_crashed", entry=entry.key, error=str(exc))

    with session_scope() as session:
        audit.record(
            session,
            AuditEventType.INGESTION_COMPLETED,
            service="collector",
            severity=Severity.WARNING if report.failures else Severity.INFO,
            summary=f"Collection cycle: {report.written} bar(s), "
            f"{report.features_written} feature value(s)",
            payload=report.as_payload(),
        )
    log.info("collector.cycle_complete", **report.as_payload())
    return report


def _window_start(
    session, instrument: Instrument, provider_id, entry: WatchEntry, now: datetime
) -> datetime:
    """Backfill deeply on first sight, then only refresh the recent window."""
    from app.models.ingestion import IngestionCheckpoint

    checkpoint = session.scalar(
        select(IngestionCheckpoint).where(
            IngestionCheckpoint.provider_id == provider_id,
            IngestionCheckpoint.instrument_id == instrument.id,
            IngestionCheckpoint.timeframe == entry.timeframe,
        )
    )
    if checkpoint is None or checkpoint.last_event_time is None:
        depth = BACKFILL_DEPTH.get(entry.timeframe, timedelta(days=365))
        log.info(
            "collector.backfilling",
            symbol=entry.symbol,
            timeframe=entry.timeframe.value,
            days=depth.days,
        )
        return now - depth
    return min(checkpoint.last_event_time, now - REFRESH_WINDOW)


def _record_staleness(
    session,
    instrument: Instrument,
    provider_id: uuid.UUID,
    timeframe: Timeframe,
    now: datetime,
) -> int:
    """Write a finding when a feed has stopped producing bars.

    The four detectors `evaluate_bars` runs all examine bars that arrived, and
    none of them can see bars that did not. So a feed that dies quietly is the
    one defect the quality report cannot describe - which is the opposite of
    what a quality report is for.

    Reads the latest stored bar rather than the batch just fetched: an empty
    fetch is exactly the case worth catching, and a batch-derived timestamp
    would be missing precisely when it matters.
    """
    latest = (
        session.query(Bar.event_time)
        .filter(Bar.instrument_id == instrument.id, Bar.timeframe == timeframe)
        .order_by(Bar.event_time.desc())
        .limit(1)
        .scalar()
    )
    finding = data_quality.check_staleness(latest, timeframe, now=now)
    if finding is None:
        return 0
    return data_quality.persist_findings(
        session,
        instrument_id=instrument.id,
        provider_id=provider_id,
        timeframe=timeframe,
        findings=[finding],
        detected_at=now,
    )


def _materialize(session, instrument: Instrument, timeframe: Timeframe, now: datetime) -> int:
    """Materialize features over the recently-touched window."""
    try:
        result = feature_store.materialize(
            session,
            instrument.id,
            timeframe,
            start=now - REFRESH_WINDOW - timeframe.delta * 200,
            end=now,
        )
        return result.values_written
    except InsufficientDataError:
        # Normal early in an instrument's life: not enough history to warm up.
        return 0


# ------------------------------------------------------------------ arq glue
def sample_equity() -> dict[str, Any]:
    """Record one equity snapshot from the bridge, if an account is connected.

    Runs on the collection cadence rather than the bridge's twenty seconds. A
    trailing floor is recalculated daily and the peak it trails moves slowly, so
    a sample every fifteen minutes places it correctly while a sample every
    twenty seconds would write four thousand rows a day per account to answer
    the same question.

    Silent when no account is connected. That is not a failure - it is the
    normal state of a deployment nobody has linked a broker to yet, and logging
    it as an error every cycle would bury the cycles that matter.
    """
    from app.providers.metatrader import MetaTraderBridge, bridge_dirs
    from app.services import equity as equity_series

    # Every configured terminal, not just the built-in one. The risk brain
    # refuses any account whose equity has never been recorded, so an account
    # sampled by nothing is an account that can never trade - and the sampler
    # reading only the main bridge produced exactly that for every spare.
    recorded: dict[str, Any] = {}
    with session_scope() as session:
        for _key, directory in sorted(bridge_dirs().items()):
            published = MetaTraderBridge(directory=directory).account()
            if not published.get("available"):
                continue
            login = str(published.get("login") or "")
            if not login:
                continue
            recorded[login] = equity_series.record(
                session,
                account_key=login,
                equity=float(published.get("equity") or 0.0),
                balance=float(published.get("balance") or 0.0),
                margin=float(published.get("margin") or 0.0),
                currency=str(published.get("currency") or "USD"),
            )
    if not recorded:
        return {"recorded": False, "reason": "no terminal published an account"}
    return {"recorded": True, "accounts": recorded}


#: The provider the twenty-one year daily series was loaded from. It ends on
#: 2025-12-31 and serves nothing after, so it measures history and cannot
#: carry forward evidence.
DEEP_HISTORY_SOURCE = "dukascopy"

#: Where live daily bars come from: folded from the hourly series, which is
#: current. See `app/workers/aggregate.py`.
#:
#: This is deliberately a different feed from the one the historical result
#: was measured on, and that is a real caveat rather than a detail. The rule
#: is cross-sectional and should not care whose ticks built the bar, but
#: "should not" is a claim about the rule, not a measurement of it - so the
#: forward series is recorded under its own provider and can be compared
#: against the historical one rather than assumed to continue it.
LIVE_DAILY_SOURCE = "aggregated"


def _sources_for(timeframe: Any) -> tuple[str, ...]:
    """Which price series can answer at this timeframe.

    Asking a provider for a timeframe it does not carry costs a query and
    returns "considered: none", which reads in the report exactly like a
    cross-section that was too small to rank - a real and different condition.

    The daily series comes from the aggregator and from nowhere else. The
    public feed carries no D1, the terminal publishes only what the expert was
    compiled to write, and the deep-history provider - which carries the
    twenty-one years the historical result was measured on - stops at the end
    of 2025. A series that cannot reach today cannot carry forward evidence,
    whatever it proved about the past.
    """
    from app.core.enums import Timeframe
    from app.models.journal import SOURCE_BROKER, SOURCE_PUBLIC

    if timeframe is Timeframe.D1:
        return (LIVE_DAILY_SOURCE,)
    return (SOURCE_PUBLIC, SOURCE_BROKER)


def _forward_timeframes() -> tuple:
    """Which timeframes the rule records decisions on.

    Unreadable names are dropped with the rest kept rather than failing the
    cycle: a typo in one environment variable should not stop the hourly
    decisions the account is actually trading on. H1 is always included for
    the same reason - the live rule decides on it, and a deployment that
    fat-fingers this must not silently stop deciding.
    """
    from app.core.enums import Timeframe

    raw = str(getattr(get_settings(), "forward_timeframes", "H1") or "H1")
    chosen = [Timeframe.H1]
    for name in raw.split(","):
        name = name.strip().upper()
        if not name:
            continue
        try:
            timeframe = Timeframe(name)
        except ValueError:
            continue
        if timeframe not in chosen:
            chosen.append(timeframe)
    return tuple(chosen)


def _broker_timeframes() -> tuple:
    """Which timeframes to pull from the terminal.

    H1 is what the live rule decides on. The faster three are pulled so the
    same rule can be *measured* at speed before anything is traded at speed:
    the spread is a constant and the bar range falls with the square root of
    time, so a decision costs more the shorter the timeframe, and the only
    honest way to find out whether the edge survives that is to have the bars.
    """
    from app.core.enums import Timeframe

    # M1 is not here, and its absence is a measurement rather than a
    # preference: the round trip costs about 0.52 R at one minute against a
    # 0.25 R ceiling, so no M1 decision can ever pass the spread gate. Pulling
    # those bars was a quarter of every cycle's work for a timeframe that
    # cannot produce a trade - and the cycle was timing out before it reached
    # the step that sends orders.
    return (Timeframe.H1, Timeframe.M15, Timeframe.M5)


def record_forward() -> dict[str, Any]:
    """Write what the rule proposes - on both price series, every cycle.

    Its own session, and its own commit. Sharing the collection's transaction
    would mean a failure here rolls back the bars, and the bars are the thing
    this worker exists for.

    Both series in the same call, for the same reason the control is written in
    the same call as the rule: a public-feed series built over months beside a
    broker series that was skipped whenever something else broke is a comparison
    with a hole in it, and the hole is invisible afterwards.

    Each is recorded independently. A failure on one is reported under its own
    name and the other still runs - the broker series is three weeks old and
    barely clears the minimum cross-section, so it will fail to rank far more
    often than the public one, and that must not stop the public one.
    """
    from app.core.enums import Timeframe
    from app.workers.forward import record_cycle

    reports: dict[str, Any] = {}
    for timeframe in _forward_timeframes():
        for source in _sources_for(timeframe):
            key = source if timeframe is Timeframe.H1 else f"{source}:{timeframe.value}"
            try:
                with session_scope() as session:
                    reports[key] = record_cycle(
                        session, price_source=source, timeframe=timeframe
                    )
            except Exception as problem:  # noqa: BLE001 - reported, never fatal
                reports[key] = {
                    "recorded": 0,
                    "reason": (
                        f"{type(problem).__name__} while recording on {key}"
                    ),
                }

    return {
        "recorded": sum(int(r.get("recorded") or 0) for r in reports.values()),
        "by_source": reports,
        "why": (
            "the two series price the same instrument 33-39% of a stop apart and "
            "the edge being measured is 0.021 R, so one of them alone answers "
            "half the question"
        ),
    }


def resolve_forward() -> dict[str, Any]:
    """Close the open entries the market has now answered."""
    from app.workers.resolve import resolve_open

    with session_scope() as session:
        return resolve_open(session)


def send_orders() -> dict[str, Any]:
    """Turn this cycle's fresh decisions into orders, behind every gate.

    Its own session and its own commit, like the forward record: a failure here
    must not roll back the bars or the decisions. Decisions are the thing that
    survives a bad day; orders can be re-derived from them, and are, on the
    next cycle.
    """
    from app.workers.autotrade import run_all_accounts

    with session_scope() as session:
        return run_all_accounts(session)


def ingest_broker_bars() -> dict[str, Any]:
    """Read the bars the terminal publishes into the metatrader provider.

    Every timeframe the expert writes, not just the hourly one. The bridge has
    been publishing M15 for weeks and none of it reached the database, because
    this called `ingest` with its default and the default was H1 - so the
    faster timeframes existed as files on the server and as nothing at all in
    any query. That is the failure mode worth naming: not a crash, just a
    quiet absence that looks like the feed never sent anything.

    Each timeframe commits on its own. A malformed M1 file must not roll back
    the hourly bars, which are the ones the live rule is deciding on.
    """
    from app.providers.metatrader import MetaTraderBridge, bridge_dirs
    from app.workers.broker_bars import ingest

    # Whichever terminal is actually signed in, not the built-in one.
    #
    # This read the single default bridge, which was the main terminal - and
    # a terminal with no account publishes no quotes. Stopping that empty
    # terminal stopped the broker price series without stopping anything that
    # said so: the collector kept succeeding, the recorder kept ranking, and
    # every decision it produced was against yesterday's 16:00 bars. Orders
    # then failed the freshness window, which reads as "the rule chose
    # nothing" rather than "the prices stopped seventeen hours ago".
    #
    # A live account is the requirement, not a name: the bars only exist
    # because a logged-in terminal is streaming them.
    source = None
    for _key, directory in sorted(bridge_dirs().items()):
        try:
            if MetaTraderBridge(directory=directory).account().get("available"):
                source = directory
                break
        except Exception:  # noqa: BLE001, S112 - an unreadable bridge is not this one
            continue

    reports: dict[str, Any] = {}
    # A preference, not a precondition: with nothing signed in the default
    # bridge is still read, which is exactly what happened before and keeps
    # whatever a terminal left behind. The note is what makes the difference
    # visible, because "no bars" and "no terminal" look identical downstream.
    note = (
        None
        if source is not None
        else "no terminal reports an account, so the default bridge was read"
    )
    for timeframe in _broker_timeframes():
        try:
            with session_scope() as session:
                reports[timeframe.value] = ingest(
                    session, timeframe=timeframe, directory=source
                )
        except Exception as problem:  # noqa: BLE001 - reported, never fatal
            reports[timeframe.value] = {
                "recorded": 0,
                "reason": f"{type(problem).__name__} on {timeframe.value}",
            }

    return {
        "recorded": sum(int(r.get("recorded") or 0) for r in reports.values()),
        "by_timeframe": reports,
        **({"note": note} if note else {}),
    }


async def collect(ctx: dict) -> dict[str, Any]:
    """ARQ task wrapper.

    The collection body is synchronous (SQLAlchemy, blocking HTTP), so it runs
    in a thread rather than blocking the event loop and starving the worker's
    own heartbeat.
    """
    report = await asyncio.to_thread(run_cycle)
    payload = report.as_payload()

    # The equity sample rides on the same cycle. Its failure must not fail the
    # collection: bars are the thing this worker exists for, and a bridge that
    # is down is a normal state that must not stop market data being recorded.
    try:
        payload["equity"] = await asyncio.to_thread(sample_equity)
    except Exception as problem:  # noqa: BLE001 - reported, never fatal
        payload["equity"] = {
            "recorded": False,
            "reason": f"{type(problem).__name__} while sampling equity",
        }

    # The broker's own bars, under their own provider. They have been published
    # every twenty seconds since the bridge was built and nothing read them, so
    # every bar in this database came from a public feed while the account
    # trades somewhere else.
    #
    # Before the forward record, not after: the rule now decides on this series
    # too, and ingesting afterwards would mean every broker-side decision was
    # taken on bars one collection cycle stale.
    try:
        payload["broker_bars"] = await asyncio.to_thread(ingest_broker_bars)
    except Exception as problem:  # noqa: BLE001 - reported, never fatal
        payload["broker_bars"] = {
            "ingested": 0,
            "reason": f"{type(problem).__name__} while reading the bridge",
        }

    # The forward record rides here too, and for the same reason: it needs the
    # bars this cycle just wrote, and a separate schedule would drift out of
    # step with them. Its failure is reported and never fatal - the forward
    # measurement matters, and it matters less than not losing market data.
    try:
        payload["forward"] = await asyncio.to_thread(record_forward)
    except Exception as problem:  # noqa: BLE001 - reported, never fatal
        payload["forward"] = {
            "recorded": 0,
            "reason": f"{type(problem).__name__} while recording the forward series",
        }

    # Orders last, after the decisions they come from exist and after the
    # market has been read. A cycle that fails before this point simply does
    # not trade, which is the right failure: the decision is recorded either
    # way and the next cycle can act on it.
    try:
        payload["orders"] = await asyncio.to_thread(send_orders)
    except Exception as problem:  # noqa: BLE001 - reported, never fatal
        payload["orders"] = {
            "orders": 0,
            "reason": f"{type(problem).__name__} while sending orders",
        }

    # And close whatever the market has answered. Without this the journal
    # fills up and never produces a number - every entry open, `resolved` at
    # zero, and the comparison reporting nothing for months in a way that looks
    # like patience rather than silence.
    try:
        payload["resolved"] = await asyncio.to_thread(resolve_forward)
    except Exception as problem:  # noqa: BLE001 - reported, never fatal
        payload["resolved"] = {
            "resolved": 0,
            "reason": f"{type(problem).__name__} while resolving open entries",
        }

    # Logged rather than only returned. This result used to travel purely as
    # the task's return value, which arq stores and nobody reads, so a cycle
    # that learned nothing explained itself in a sentence that reached no one -
    # while `collector.cycle_complete` beside it reported six entries ingested
    # and no failures, which is exactly what a healthy collector looks like.
    # The journal sat at zero for as long as that was true.
    forward = payload.get("forward") or {}
    resolved = payload.get("resolved") or {}
    log.info(
        "collector.forward_complete",
        recorded=forward.get("recorded", 0),
        # Present only when nothing was written, and it is the whole point of
        # this line: it names which gate stopped the cycle.
        reason=forward.get("reason"),
        considered=forward.get("considered"),
        resolved=resolved.get("resolved", 0),
    )

    # And the same for orders, for exactly the same reason.
    #
    # The comment above says the forward result used to travel only as arq's
    # return value and so reached nobody. Orders were doing that still: the
    # log said 22 decisions recorded and 220 resolved and never once said
    # whether any of them became a position. "Did it trade?" was answerable
    # only by opening a terminal, which is not a thing anybody does at four
    # in the morning.
    #
    # Per account rather than as a fleet total, because zero is the common
    # answer and the whole question is *which* account and *why* - a paused
    # one, a logged-out one and one whose brains all disagreed are the same
    # zero and want three different responses. The first named refusal is
    # carried rather than the whole list: it is the one that will be read.
    orders = payload.get("orders") or {}
    by_account = orders.get("by_account") or {}
    log.info(
        "collector.orders_complete",
        orders=orders.get("orders", 0),
        accounts=orders.get("accounts", 0),
        reason=orders.get("reason"),
        per_account={
            str(key): (
                report.get("refused")
                or report.get("skipped")
                or report.get("orders", 0)
            )
            for key, report in by_account.items()
            if isinstance(report, dict)
        },
    )

    return payload


async def startup(ctx: dict) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    bind_trace()
    log.info(
        "collector.startup",
        provider=settings.collector_provider,
        watchlist=settings.watchlist,
        interval_seconds=settings.collector_interval_seconds,
    )

    # A watchlist shorter than the cross-section's floor can never produce a
    # ranking, so the deployment collects bars indefinitely and learns nothing
    # from any of them. That is knowable here, before a single cycle runs,
    # rather than only by counting an empty journal weeks later and reading
    # source to find out why. Deferred import for the same reason the forward
    # recorder defers its own: the brain package pulls in the model layer.
    from app.brain.crosssection import MIN_CROSS_SECTION

    counts: dict[str, int] = {}
    for entry in parse_watchlist(settings.watchlist):
        counts[entry.timeframe.value] = counts.get(entry.timeframe.value, 0) + 1
    for timeframe, count in sorted(counts.items()):
        if count < MIN_CROSS_SECTION:
            # A warning rather than a refusal to start. Collection is worth
            # doing on its own - the bars are still real and still kept - and
            # a deployment being filled up towards the floor is a legitimate
            # state to run in. What is not legitimate is doing it silently.
            log.warning(
                "collector.watchlist_below_cross_section",
                timeframe=timeframe,
                instruments=count,
                required=MIN_CROSS_SECTION,
                detail=(
                    "The cross-section will not rank fewer instruments than "
                    "this, so no forward entry can be written on this "
                    "timeframe and nothing will be learned from it."
                ),
            )


# How often the DNA profiles are recomputed. Daily rather than per cycle: they
# describe an instrument's character over thousands of bars, and a character
# that changed every fifteen minutes would not be one. Recomputing them at the
# collection cadence would also read five thousand bars per instrument per
# sweep for numbers that had not moved.
DNA_REFRESH_HOUR = 2


def refresh_dna(entries: list[WatchEntry] | None = None) -> dict[str, Any]:
    """Compute and store the symbol-DNA profiles for every watched instrument.

    This existed, was tested, and was never called in production - the market
    map found it by reporting forty instruments as unmeasured rather than
    drawing a correlation grid out of nothing.

    `compute_dna` sources its own peer list for the correlation facet, so
    this only has to walk the watchlist.
    """
    settings = get_settings()
    entries = entries or parse_watchlist(settings.watchlist)
    now = datetime.now(UTC)
    written = 0
    failures: list[str] = []

    for entry in entries:
        try:
            with session_scope() as session:
                instrument = get_instrument_by_symbol(session, entry.symbol)
                if instrument is None:
                    continue
                profiles = symbol_dna.compute_dna(
                    session, instrument.id, entry.timeframe, now
                )
                written += symbol_dna.persist_dna(
                    session, instrument.id, entry.timeframe, now, profiles
                )
        except MolidoError as exc:
            # A single instrument short of history must not stop the sweep, and
            # the reason is recorded rather than swallowed.
            failures.append(f"{entry.key}: {exc.code}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{entry.key}: {type(exc).__name__}")

    log.info(
        "collector.dna_refreshed",
        entries=len(entries),
        profiles_written=written,
        failures=len(failures),
    )
    return {
        "entries": len(entries),
        "profiles_written": written,
        "failures": failures,
    }


# Retention runs weekly and for real rather than dry. A dry-run-forever
# retention job is a disk that fills at the same rate as before, with a log
# line saying what could have been done about it.
RETENTION_HOUR = 4
RETENTION_WEEKDAY = 6  # Sunday, when the market is shut and nothing is mid-write


def prune_old_rows() -> dict[str, Any]:
    """Apply the retention policies.

    Written after the disk filled, then never scheduled - a fix for an incident
    that could not run. Every policy protects the rows it must never touch, and
    the report says what each one removed rather than only a total.
    """
    with session_scope() as session:
        report = retention.prune(session, dry_run=False)

    payload = report.as_dict() if hasattr(report, "as_dict") else {"removed": str(report)}
    log.info("collector.retention_pruned", **{"summary": str(payload)[:400]})
    return payload


async def prune_old_rows_job(ctx: dict) -> dict[str, Any]:
    """ARQ wrapper. Threaded for the same reason `collect` is."""
    return await asyncio.to_thread(prune_old_rows)


# Episodes are built a day behind rather than up to now. An episode is only
# honest once its outcome window has closed, and `build` skips the immature
# ones anyway - reaching for today's bars would spend the sweep discovering
# that today has not finished yet.
EPISODE_BUILD_HOUR = 3
EPISODE_WINDOW = timedelta(days=7)
# Consecutive bars produce near-identical episodes, and a library of
# near-duplicates makes similarity search confidently wrong: it returns a
# hundred matches that are really one moment counted a hundred times.
EPISODE_STEP = 4


def build_episodes(entries: list[WatchEntry] | None = None) -> dict[str, Any]:
    """Build episodes for every watched instrument over the recent window.

    Written because the table was empty in production while its builder was
    fully tested. The same gap as symbol DNA, found the same way: by asking the
    database what was in it rather than asking the test suite whether the code
    worked.
    """
    settings = get_settings()
    entries = entries or parse_watchlist(settings.watchlist)
    now = datetime.now(UTC)
    built = 0
    immature = 0
    existing = 0
    failures: list[str] = []

    for entry in entries:
        try:
            with session_scope() as session:
                instrument = get_instrument_by_symbol(session, entry.symbol)
                if instrument is None:
                    continue
                result = episodes.build(
                    session,
                    instrument.id,
                    entry.timeframe,
                    start=now - EPISODE_WINDOW,
                    end=now,
                    as_of=now,
                    step=EPISODE_STEP,
                )
                built += result.built
                immature += result.skipped_immature
                existing += result.skipped_existing
        except MolidoError as exc:
            # One instrument short of history must not stop the sweep, and the
            # reason is recorded rather than swallowed.
            failures.append(f"{entry.key}: {exc.code}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{entry.key}: {type(exc).__name__}")

    log.info(
        "collector.episodes_built",
        entries=len(entries),
        built=built,
        skipped_immature=immature,
        skipped_existing=existing,
        failures=len(failures),
    )
    return {
        "entries": len(entries),
        "built": built,
        "skipped_immature": immature,
        "skipped_existing": existing,
        "failures": failures,
    }


# A day behind the episode sweep. Nothing here is urgent: a conflict between
# feeds is a standing condition, not an event, and checking it hourly would
# rewrite the same finding row all day.
CONFLICT_CHECK_HOUR = 4
CONFLICT_WINDOW = timedelta(days=14)


def compare_providers(entries: list[WatchEntry] | None = None) -> dict[str, Any]:
    """Compare what each provider stored, for every watched instrument.

    `data_quality.detect_provider_conflicts` was written in phase 3 and had
    never run. It compares two feeds, and `evaluate_bars` walks one normalised
    series, so there was no path from ingestion to the detector at all - the
    one issue in `DataQualityIssue` needing a second opinion could not be
    raised.

    Harmless while this deployment has a single provider. Not harmless the
    moment MetaTrader lands beside yfinance, which is why it is wired now.
    """
    settings = get_settings()
    entries = entries or parse_watchlist(settings.watchlist)
    now = datetime.now(UTC)
    compared = 0
    single_provider = 0
    conflicts = 0
    written = 0
    failures: list[str] = []

    for entry in entries:
        try:
            with session_scope() as session:
                instrument = get_instrument_by_symbol(session, entry.symbol)
                if instrument is None:
                    continue
                result = data_quality.compare_providers(
                    session,
                    instrument.id,
                    entry.timeframe,
                    since=now - CONFLICT_WINDOW,
                    detected_at=now,
                )
                if result["compared"]:
                    compared += 1
                    conflicts += result["conflicts"]
                    written += result["written"]
                else:
                    single_provider += 1
        except MolidoError as exc:
            failures.append(f"{entry.key}: {exc.code}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{entry.key}: {type(exc).__name__}")

    log.info(
        "collector.providers_compared",
        entries=len(entries),
        compared=compared,
        single_provider=single_provider,
        conflicts=conflicts,
        findings_written=written,
        failures=len(failures),
    )
    return {
        "entries": len(entries),
        # Counted apart from `compared` on purpose. A series with one feed was
        # not found clean; it was not checked, and folding the two together is
        # how an unmeasured system reports itself healthy.
        "compared": compared,
        "single_provider": single_provider,
        "conflicts": conflicts,
        "findings_written": written,
        "failures": failures,
    }


async def compare_providers_job(ctx: dict) -> dict[str, Any]:
    """ARQ wrapper. Threaded for the same reason `collect` is."""
    return await asyncio.to_thread(compare_providers)


async def build_episodes_job(ctx: dict) -> dict[str, Any]:
    """ARQ wrapper. Threaded for the same reason `collect` is."""
    return await asyncio.to_thread(build_episodes)


async def refresh_dna_job(ctx: dict) -> dict[str, Any]:
    """ARQ wrapper. Threaded for the same reason `collect` is."""
    return await asyncio.to_thread(refresh_dna)


#: Hours at which to retry the deep-history backfill.
#:
#: The feed refused every request today - three runs, twenty-eight symbols,
#: zero bars - and single probes still answer about one time in three. That is
#: a cooldown counted from cumulative load on this address, and it lifts at an
#: hour nobody can predict, which makes it exactly the wrong thing to poke by
#: hand. So it retries itself.
#:
#: Six times a day rather than hourly: each attempt that fails still costs the
#: feed twenty-eight symbols' worth of requests, and hammering a cooldown is
#: how it got here.
DEEP_HISTORY_HOURS = {1, 5, 9, 13, 17, 21}


#: When the daily fold runs: ten minutes after the UTC day it folds has ended.
#:
#: This was 23:10 on the reasoning that a day finished in London is still
#: trading in New York. That reasoning was wrong for a UTC-bounded bar - the
#: session spanning midnight belongs to the *next* UTC day, so a day ending at
#: 00:00 UTC is complete by definition - and the timing it produced was worse
#: than untidy. At 23:10 the current day is unfinished, so the fold reaches
#: only the previous one, whose bar closed twenty-three hours earlier. A
#: decision recorded on it arrives already outside its freshness window and
#: can never be traded. Measured: 23.2 hours stale at 23:10, 0.2 at 00:10.
AGGREGATE_HOUR = 0


async def aggregate_daily_job(ctx: dict) -> dict[str, Any]:
    """Fold yesterday's hourly bars into a daily one.

    Runs nightly rather than on the collection cycle. A fold is cheap per day
    and expensive over two years of history, and the only day that changes
    between one cycle and the next is the one that has not closed - which this
    excludes on purpose.
    """
    from app.workers.aggregate import build

    def run() -> dict[str, Any]:
        with session_scope() as session:
            return build(session)

    return await asyncio.to_thread(run)


async def deep_history_job(ctx: dict) -> dict[str, Any]:
    """Try the deep-history backfill, and stop trying once it has landed.

    Self-cancelling by checking what is already stored. A job that re-fetches
    twenty years every four hours forever would be a permanent load on a feed
    that has already objected once, and the upsert would make it invisible.
    """
    return await asyncio.to_thread(run_deep_history)


def run_deep_history() -> dict[str, Any]:
    from app.brain.crosssection import MIN_CROSS_SECTION
    from app.core.enums import Timeframe
    from app.workers.deep_history import OFFERED, PROVIDER_CODE, backfill

    with session_scope() as session:
        stored = session.execute(
            select(func.count(func.distinct(Bar.instrument_id))).where(
                Bar.timeframe == Timeframe.D1.value,
                Bar.provider_id.in_(
                    select(Provider.id).where(Provider.code == PROVIDER_CODE)
                ),
            )
        ).scalar_one()

    if stored >= MIN_CROSS_SECTION:
        # Enough to rank. Anything further is load on a feed that has already
        # objected, in exchange for bars nothing is waiting for.
        return {
            "skipped": True,
            "reason": (
                f"{stored} instruments already have deep daily history, which "
                f"clears the {MIN_CROSS_SECTION} the rule needs to rank"
            ),
        }

    with session_scope() as session:
        report = backfill(
            session, symbols=list(OFFERED), timeframe=Timeframe.D1
        )
    return {k: v for k, v in report.items() if k != "periods_with_no_file"}


async def weekly_scorecard_job(ctx: dict) -> dict[str, Any]:
    """Log every brain's week beside its own control, Sunday mornings.

    The journal fills every fifteen minutes and, until this, nobody read it
    on a schedule - so the question the fleet exists to answer had no
    standing answer. Logged in full so it lands where the operator already
    looks, whichever way the numbers came out.
    """
    from app.learning.weekly import build_report

    with session_scope() as session:
        report = build_report(session)
    log.info("weekly.scorecard", **{
        "brains": report["brains"],
        "accounts": report["accounts"],
        "window_days": report["window_days"],
    })
    return report


def _cron_jobs() -> list:
    from arq import cron

    settings = get_settings()
    minutes = max(1, min(30, settings.collector_interval_seconds // 60))
    # Fixed minute marks rather than "every N seconds": two workers started at
    # different times then land on the same schedule instead of drifting into
    # overlapping sweeps of the same symbols.
    marks = set(range(0, 60, minutes))
    return [
        cron(collect, minute=marks, run_at_startup=True, max_tries=1),
        # Once a day, off the hour the market is busiest.
        cron(refresh_dna_job, hour={DNA_REFRESH_HOUR}, minute={0}, max_tries=1),
        # An hour after the DNA sweep rather than beside it: both walk the whole
        # watchlist, and two full sweeps at once on a two-core box starve the
        # collection cycle that has to land on the minute.
        cron(build_episodes_job, hour={EPISODE_BUILD_HOUR}, minute={0}, max_tries=1),
        cron(compare_providers_job, hour={CONFLICT_CHECK_HOUR}, minute={0}, max_tries=1),
        # Ten minutes after the day it folds has ended, so the decision it
        # produces is inside its freshness window rather than a day past it.
        cron(aggregate_daily_job, hour={AGGREGATE_HOUR}, minute={10}, max_tries=1),
        # The chat channel is NOT here. It ran on this schedule and arrived
        # twenty-five minutes late, because one collection cycle takes
        # minutes and everything behind it waits - so an operator got
        # silence and then nine answers at once. It has its own process
        # now: app.workers.chat.
        # Sunday, before the week opens: the standing answer to "which brain
        # is earning its vote", from the journal the week just filled.
        cron(
            weekly_scorecard_job,
            weekday={6},
            hour={9},
            minute={30},
            max_tries=1,
        ),
        # Retries itself until the history is in, then reports that it skipped.
        # max_tries=1 on purpose: a failed attempt means the feed is closed,
        # and arq retrying it immediately is the opposite of waiting.
        cron(
            deep_history_job,
            hour=DEEP_HISTORY_HOURS,
            minute={40},
            max_tries=1,
        ),
        # Weekly, on the shut market, after the two daily sweeps.
        cron(
            prune_old_rows_job,
            weekday={RETENTION_WEEKDAY},
            hour={RETENTION_HOUR},
            minute={0},
            max_tries=1,
        ),
    ]


def _redis_settings():
    from arq.connections import RedisSettings

    return RedisSettings.from_dsn(get_settings().redis_url)


class WorkerSettings:
    """`arq app.workers.collector.WorkerSettings`

    ARQ reads these as plain class attributes and never calls them, so they are
    evaluated once at import. Defining `cron_jobs` as a method instead makes the
    worker die at startup with `'staticmethod' object is not iterable` — a
    message that points nowhere near the actual mistake.
    """

    functions = [
        collect,
        refresh_dna_job,
        build_episodes_job,
        prune_old_rows_job,
        compare_providers_job,
        deep_history_job,
    ]
    on_startup = startup
    max_jobs = 2
    #: One cycle now collects 150 watchlist entries, materialises their
    #: features, ingests four broker timeframes, records two price series on
    #: three timeframes each, sends orders and resolves what closed. At 900s
    #: that cycle began timing out - and a timed-out cycle is worse than a
    #: slow one: the orders step never runs, so the system stops trading and
    #: the only evidence is one line in a log nobody greps.
    #:
    #: Raised rather than trimmed, because every step in that list is load
    #: somebody asked for. The interval is fifteen minutes and arq will not
    #: start a second copy of a cron job, so a long cycle delays the next one
    #: rather than overlapping it.
    job_timeout = 1500
    keep_result = 3600
    cron_jobs = _cron_jobs()
    redis_settings = _redis_settings()
    # Pinned, because arq's default is the *system* timezone and this host
    # displays Iran time (+03:30). Left unpinned, the :00/:15/:30/:45 marks
    # slide half an hour off the bar closes and every decision is taken
    # thirty minutes late - trading the delay rather than the rule. The
    # cycle's rhythm belongs to the bars, and the bars are UTC.
    timezone = UTC


def main() -> None:
    """Run one cycle from the command line, for smoke-testing a deployment."""
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    bind_trace()
    report = run_cycle()
    print(report.as_payload())  # noqa: T201 - this entrypoint is a CLI


if __name__ == "__main__":
    main()
