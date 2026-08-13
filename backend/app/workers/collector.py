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
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.core.config import get_settings
from app.core.enums import AuditEventType, Severity, Timeframe
from app.core.errors import InsufficientDataError, MolidoError
from app.core.logging import bind_trace, configure_logging, get_logger
from app.db.session import session_scope
from app.models.instruments import Instrument
from app.providers.base import MarketDataProvider
from app.providers.registry import get_provider, install_defaults, register
from app.services import audit, feature_store, ingestion, sessions, symbol_dna
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
    failures: list[str] = field(default_factory=list)

    def as_payload(self) -> dict[str, Any]:
        return {
            "entries": self.entries,
            "skipped_closed": self.skipped_closed,
            "ingested": self.ingested,
            "bars_written": self.written,
            "features_written": self.features_written,
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
async def collect(ctx: dict) -> dict[str, Any]:
    """ARQ task wrapper.

    The collection body is synchronous (SQLAlchemy, blocking HTTP), so it runs
    in a thread rather than blocking the event loop and starving the worker's
    own heartbeat.
    """
    report = await asyncio.to_thread(run_cycle)
    return report.as_payload()


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


async def refresh_dna_job(ctx: dict) -> dict[str, Any]:
    """ARQ wrapper. Threaded for the same reason `collect` is."""
    return await asyncio.to_thread(refresh_dna)


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

    functions = [collect, refresh_dna_job]
    on_startup = startup
    max_jobs = 2
    job_timeout = 900
    keep_result = 3600
    cron_jobs = _cron_jobs()
    redis_settings = _redis_settings()


def main() -> None:
    """Run one cycle from the command line, for smoke-testing a deployment."""
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    bind_trace()
    report = run_cycle()
    print(report.as_payload())  # noqa: T201 - this entrypoint is a CLI


if __name__ == "__main__":
    main()
