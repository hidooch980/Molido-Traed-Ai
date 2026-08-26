"""Ingestion pipeline (spec §4).

    Provider adapter -> raw -> validation -> normalization -> canonical
                     -> point-in-time storage

Properties this module is responsible for:

* **Idempotency.** A run is keyed by (provider, instrument, timeframe, window).
  Re-running an identical request writes nothing new and reports the duplicate
  count rather than importing twice.
* **Resumability.** Progress is checkpointed per target, so a crash mid-history
  costs one chunk, not the whole download.
* **Retry with backoff.** Transient provider failures back off exponentially;
  rate limits honour the provider's own retry hint.
* **Revisions, not overwrites.** A changed bar becomes a new revision with a
  fresh `ingested_at`. Nothing is ever mutated in place, because overwriting
  destroys the historical knowledge state that point-in-time reads depend on.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import AuditEventType, IngestionStatus, Severity, Timeframe
from app.core.errors import ProviderError, RateLimitedError, ValidationFailedError
from app.core.logging import get_logger
from app.models.ingestion import IngestionCheckpoint, IngestionRun
from app.models.instruments import Instrument, Provider
from app.models.market_data import Bar
from app.providers.base import MarketDataProvider, RawBar
from app.services import audit, data_quality, sessions

log = get_logger(__name__)


@dataclass
class IngestionResult:
    run_id: uuid.UUID
    status: IngestionStatus
    fetched: int
    written: int
    duplicates: int
    rejected: int
    quality_score: float
    findings: dict[str, int]
    error: str | None = None


def make_idempotency_key(
    provider_code: str,
    instrument_symbol: str,
    timeframe: Timeframe,
    start: datetime,
    end: datetime,
) -> str:
    raw = (
        f"{provider_code}|{instrument_symbol}|{timeframe.value}"
        f"|{start.isoformat()}|{end.isoformat()}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:64]


def _normalize(bars: list[RawBar]) -> tuple[list[RawBar], int]:
    """Drop structurally unusable rows. Returns (kept, rejected_count).

    Only rows that cannot be stored at all are dropped — a naive timestamp has
    no defined instant, a non-positive price is not a price. Everything else,
    including suspicious data, is kept: the quality engine records it, and
    discarding it here would hide feed problems instead of surfacing them.
    """
    kept: list[RawBar] = []
    rejected = 0
    for bar in bars:
        if bar.event_time.tzinfo is None:
            rejected += 1
            continue
        if min(bar.open, bar.high, bar.low, bar.close) <= 0:
            rejected += 1
            continue
        kept.append(
            RawBar(
                event_time=bar.event_time.astimezone(UTC),
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                tick_volume=bar.tick_volume,
                spread=bar.spread,
                source_ref=bar.source_ref,
            )
        )
    kept.sort(key=lambda b: b.event_time)
    return kept, rejected


def _fetch_with_retry(
    provider: MarketDataProvider,
    raw_symbol: str,
    timeframe: Timeframe,
    start: datetime,
    end: datetime,
    *,
    max_retries: int,
    backoff_base: float,
    sleep=time.sleep,
) -> list[RawBar]:
    """Fetch one window, retrying transient failures with exponential backoff."""
    attempt = 0
    while True:
        try:
            return provider.fetch_ohlcv(raw_symbol, timeframe, start, end)
        except RateLimitedError as exc:
            attempt += 1
            if attempt > max_retries:
                raise
            delay = exc.retry_after_seconds or backoff_base * (2 ** (attempt - 1))
            log.warning(
                "provider.rate_limited",
                provider=provider.code,
                symbol=raw_symbol,
                attempt=attempt,
                delay_seconds=delay,
            )
            sleep(delay)
        except ProviderError:
            attempt += 1
            if attempt > max_retries:
                raise
            delay = backoff_base * (2 ** (attempt - 1))
            log.warning(
                "provider.retrying",
                provider=provider.code,
                symbol=raw_symbol,
                attempt=attempt,
                delay_seconds=delay,
            )
            sleep(delay)


def _existing_bars(
    session: Session,
    instrument_id: uuid.UUID,
    provider_id: uuid.UUID,
    timeframe: Timeframe,
    moments: Sequence[datetime],
) -> dict[datetime, Bar]:
    """Newest stored revision for each of these instants.

    Looked up by the timestamps actually returned rather than by the window
    they were requested for, because a provider does not promise to stay
    inside it. Yahoo answers a fifteen-minute request with whatever its
    session boundaries produce, and a bar arriving from outside the window was
    invisible to a window-shaped lookup - so the insert that followed collided
    with a row already stored and took the whole symbol down with it. Seven of
    a hundred and twenty-five entries failed that way on every sweep, and each
    failure is one instrument that stops collecting.
    """
    if not moments:
        return {}

    rows = session.scalars(
        select(Bar)
        .where(
            Bar.instrument_id == instrument_id,
            Bar.provider_id == provider_id,
            Bar.timeframe == timeframe,
            Bar.event_time.in_(list(moments)),
        )
        .order_by(Bar.event_time, Bar.revision)
    )
    latest: dict[datetime, Bar] = {}
    for row in rows:
        latest[row.event_time] = row  # ascending revision -> last wins
    return latest


def _values_changed(existing: Bar, incoming: RawBar) -> bool:
    def same(a, b) -> bool:
        if a is None or b is None:
            return a is None and b is None
        return abs(float(a) - float(b)) < 1e-9

    return not (
        same(existing.open, incoming.open)
        and same(existing.high, incoming.high)
        and same(existing.low, incoming.low)
        and same(existing.close, incoming.close)
        and same(existing.volume, incoming.volume)
        and same(existing.tick_volume, incoming.tick_volume)
    )


def _chunks(start: datetime, end: datetime, days: int):
    cursor = start
    step = timedelta(days=max(1, days))
    while cursor < end:
        yield cursor, min(cursor + step, end)
        cursor += step


def ingest_ohlcv(
    session: Session,
    *,
    provider: MarketDataProvider,
    provider_row: Provider,
    instrument: Instrument,
    timeframe: Timeframe,
    start: datetime,
    end: datetime,
    raw_symbol: str | None = None,
    resume: bool = True,
    sleep=time.sleep,
) -> IngestionResult:
    """Ingest one (provider, instrument, timeframe) window.

    The caller owns the transaction. On provider failure the run is marked
    FAILED and the exception is swallowed into the result — a failed download
    is an operational fact to record, not a crash — but any data already
    written in earlier chunks is kept and the checkpoint reflects it, so a
    retry resumes rather than restarts.
    """
    settings = get_settings()
    raw_symbol = raw_symbol or instrument.symbol

    if start.tzinfo is None or end.tzinfo is None:
        raise ValidationFailedError("start and end must be timezone-aware (UTC)")
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    if end <= start:
        raise ValidationFailedError("end must be after start", start=str(start), end=str(end))

    checkpoint = session.scalar(
        select(IngestionCheckpoint).where(
            IngestionCheckpoint.provider_id == provider_row.id,
            IngestionCheckpoint.instrument_id == instrument.id,
            IngestionCheckpoint.timeframe == timeframe,
        )
    )
    effective_start = start
    if resume and checkpoint is not None and checkpoint.last_event_time is not None:
        # Re-fetch the last known bar: providers frequently revise the most
        # recent candle, and skipping it would freeze a partial bar forever.
        effective_start = max(start, checkpoint.last_event_time)

    key = make_idempotency_key(provider_row.code, instrument.symbol, timeframe, start, end)
    existing_run = session.scalar(
        select(IngestionRun).where(IngestionRun.idempotency_key == key)
    )
    if existing_run is not None and existing_run.status == IngestionStatus.SUCCEEDED:
        log.info(
            "ingestion.skipped_duplicate",
            run_id=str(existing_run.id),
            symbol=instrument.symbol,
            timeframe=timeframe.value,
        )
        return IngestionResult(
            run_id=existing_run.id,
            status=IngestionStatus.SUCCEEDED,
            fetched=existing_run.rows_fetched,
            written=0,
            duplicates=existing_run.rows_written,
            rejected=existing_run.rows_rejected,
            quality_score=1.0,
            findings={},
        )

    run = existing_run or IngestionRun(
        provider_id=provider_row.id,
        instrument_id=instrument.id,
        timeframe=timeframe,
        idempotency_key=key,
        requested_start=start,
        requested_end=end,
        attempts=0,
        rows_fetched=0,
        rows_written=0,
        rows_rejected=0,
        rows_duplicate=0,
    )
    run.status = IngestionStatus.RUNNING
    run.started_at = datetime.now(UTC)
    # Column defaults are applied at flush time, so a freshly constructed row
    # still has None here; count the attempt against the persisted value.
    run.attempts = (run.attempts or 0) + 1
    session.add(run)
    session.flush()

    audit.record(
        session,
        AuditEventType.INGESTION_STARTED,
        summary=f"Ingest {instrument.symbol} {timeframe.value} from {provider_row.code}",
        payload={
            "run_id": str(run.id),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "resumed_from": effective_start.isoformat(),
        },
    )

    fetched: list[RawBar] = []
    written = duplicates = rejected = 0
    error: str | None = None
    now = datetime.now(UTC)

    try:
        # The provider declares how much history it will answer in one call;
        # the configured value is only a fallback for adapters that don't say.
        chunk_days = provider.capabilities().chunk_days(
            timeframe, settings.ingest_chunk_days
        )
        for chunk_start, chunk_end in _chunks(effective_start, end, chunk_days):
            raw = _fetch_with_retry(
                provider,
                raw_symbol,
                timeframe,
                chunk_start,
                chunk_end,
                max_retries=settings.ingest_max_retries,
                backoff_base=settings.ingest_backoff_base_seconds,
                sleep=sleep,
            )
            fetched.extend(raw)

            normalized, chunk_rejected = _normalize(raw)
            rejected += chunk_rejected
            if not normalized:
                continue

            stored = _existing_bars(
                session,
                instrument.id,
                provider_row.id,
                timeframe,
                # The instants in hand, not the window they were asked for.
                [bar.event_time for bar in normalized],
            )
            seen_in_batch: set[datetime] = set()

            for bar in normalized:
                if bar.event_time in seen_in_batch:
                    duplicates += 1
                    continue
                seen_in_batch.add(bar.event_time)

                previous = stored.get(bar.event_time)
                if previous is not None and not _values_changed(previous, bar):
                    duplicates += 1
                    continue

                session.add(
                    Bar(
                        instrument_id=instrument.id,
                        provider_id=provider_row.id,
                        timeframe=timeframe,
                        event_time=bar.event_time,
                        revision=(previous.revision + 1) if previous else 1,
                        ingested_at=now,
                        open=bar.open,
                        high=bar.high,
                        low=bar.low,
                        close=bar.close,
                        volume=bar.volume,
                        tick_volume=bar.tick_volume,
                        spread=bar.spread,
                        source_ref=bar.source_ref,
                    )
                )
                written += 1

            session.flush()
            _save_checkpoint(
                session,
                checkpoint,
                provider_row.id,
                instrument.id,
                timeframe,
                last_event_time=max(b.event_time for b in normalized),
                run_id=run.id,
            )
            checkpoint = session.scalar(
                select(IngestionCheckpoint).where(
                    IngestionCheckpoint.provider_id == provider_row.id,
                    IngestionCheckpoint.instrument_id == instrument.id,
                    IngestionCheckpoint.timeframe == timeframe,
                )
            )

        status = IngestionStatus.SUCCEEDED
    except (ProviderError, ValidationFailedError) as exc:
        status = IngestionStatus.PARTIAL if written else IngestionStatus.FAILED
        error = str(exc)
        run.error_code = getattr(exc, "code", "provider_error")
        run.error_message = error
        log.error(
            "ingestion.failed",
            run_id=str(run.id),
            symbol=instrument.symbol,
            timeframe=timeframe.value,
            error=error,
        )

    # Quality assessment runs over whatever was actually fetched, including on
    # a partial run - a truncated download is exactly when quality matters.
    normalized_all, _ = _normalize(fetched)
    calendar = sessions.build_calendar(
        session,
        instrument,
        start=start.date(),
        end=end.date(),
    )
    report = data_quality.evaluate_bars(normalized_all, timeframe, calendar)
    data_quality.persist_findings(
        session,
        instrument_id=instrument.id,
        provider_id=provider_row.id,
        timeframe=timeframe,
        findings=report.findings,
        run_id=run.id,
    )
    coverage_start, coverage_end = data_quality.coverage_window(normalized_all)
    data_quality.update_dataset_quality(
        session,
        instrument_id=instrument.id,
        provider_id=provider_row.id,
        timeframe=timeframe,
        report=report,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
    )

    run.status = status
    run.finished_at = datetime.now(UTC)
    run.rows_fetched = len(fetched)
    run.rows_written = written
    run.rows_duplicate = duplicates
    run.rows_rejected = rejected
    session.flush()

    audit.record(
        session,
        AuditEventType.INGESTION_COMPLETED
        if status == IngestionStatus.SUCCEEDED
        else AuditEventType.INGESTION_FAILED,
        severity=Severity.INFO if status == IngestionStatus.SUCCEEDED else Severity.ERROR,
        summary=f"{instrument.symbol} {timeframe.value}: {status.value}",
        payload={
            "run_id": str(run.id),
            "fetched": len(fetched),
            "written": written,
            "duplicates": duplicates,
            "rejected": rejected,
            "quality_score": round(report.score, 3),
            "findings": report.count_by_issue(),
        },
    )

    return IngestionResult(
        run_id=run.id,
        status=status,
        fetched=len(fetched),
        written=written,
        duplicates=duplicates,
        rejected=rejected,
        quality_score=round(report.score, 3),
        findings=report.count_by_issue(),
        error=error,
    )


def _save_checkpoint(
    session: Session,
    checkpoint: IngestionCheckpoint | None,
    provider_id: uuid.UUID,
    instrument_id: uuid.UUID,
    timeframe: Timeframe,
    *,
    last_event_time: datetime,
    run_id: uuid.UUID,
) -> None:
    if checkpoint is None:
        checkpoint = IngestionCheckpoint(
            provider_id=provider_id,
            instrument_id=instrument_id,
            timeframe=timeframe,
        )
        session.add(checkpoint)
    # Never move a checkpoint backwards: an out-of-order chunk must not cause
    # a later resume to re-download history that is already complete.
    if checkpoint.last_event_time is None or last_event_time > checkpoint.last_event_time:
        checkpoint.last_event_time = last_event_time
    checkpoint.last_run_id = run_id
    checkpoint.last_success_at = datetime.now(UTC)
    session.flush()


def get_or_create_provider(
    session: Session,
    code: str,
    name: str,
    *,
    capabilities: dict | None = None,
    trust_weight: float = 0.5,
) -> Provider:
    provider = session.scalar(select(Provider).where(Provider.code == code))
    if provider is None:
        provider = Provider(
            code=code,
            name=name,
            capabilities=capabilities or {},
            trust_weight=trust_weight,
        )
        session.add(provider)
        session.flush()
    elif capabilities is not None:
        provider.capabilities = capabilities
        session.flush()
    return provider
