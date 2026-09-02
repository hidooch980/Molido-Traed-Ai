"""Service-level observations, kept where a restart cannot lose them.

`observability.SLO` measured latency and availability into a list in memory,
and `slo_window_populated` asked whether that list held a hundred points. It
never did for long: the API restarts on every deploy, the list restarts with
it, and an objective measured against a window that empties itself is not
measured.

So observations go to a table. Two writers:

- the API middleware records every request's latency and status, buffered
  in memory and flushed in batches so a dashboard polling twice a second
  does not turn into a database write per poll;
- the collector records, once per cycle, what a request cannot see:
  ingestion health, data freshness, execution health, the error rate of the
  cycle itself.

`window` counts what landed in the last `WINDOW`. The readiness check reads
that count and nothing else - a hundred observations is the threshold the
check has always used, and the table is what makes it reachable.

Nothing is fabricated. If the API served no requests and the collector ran no
cycle, the window is empty and the check fails, which is the truth.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.slo import SloObservation

#: How far back an observation counts. One day: an objective is a statement
#: about a period somebody could act on, not about the last five minutes and
#: not about last quarter.
WINDOW = timedelta(hours=24)

#: The threshold `readiness` has always used.
MIN_OBSERVATIONS = 100

#: Flush the request buffer at this many entries or this many seconds,
#: whichever comes first. Fifty requests is a few seconds of dashboard
#: polling; thirty seconds is how long a quiet API waits to write.
FLUSH_EVERY = 50
FLUSH_SECONDS = 30.0

METRIC_LATENCY = "api.latency_ms"
METRIC_AVAILABILITY = "api.availability"
METRIC_ERROR_RATE = "api.error_rate"
METRIC_INGESTION = "ingestion.health"
METRIC_FRESHNESS = "data.freshness_bars"
METRIC_EXECUTION = "execution.health"
METRIC_CYCLE_ERRORS = "cycle.error_rate"


@dataclass
class Buffer:
    """Request observations waiting to be written, and when they were last."""

    entries: list[dict[str, Any]] = field(default_factory=list)
    last_flush: float = field(default_factory=time.monotonic)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, **observation: Any) -> bool:
        """Queue one observation; True when a flush is due."""
        with self.lock:
            self.entries.append(observation)
            due = (
                len(self.entries) >= FLUSH_EVERY
                or time.monotonic() - self.last_flush >= FLUSH_SECONDS
            )
        return due

    def drain(self) -> list[dict[str, Any]]:
        with self.lock:
            out, self.entries = self.entries, []
            self.last_flush = time.monotonic()
        return out


#: One buffer per process. The API is one process; the collector writes
#: directly and does not use it.
REQUESTS = Buffer()


def observe_request(path: str, status: int, latency_ms: float) -> bool:
    """Queue a request observation. Returns True when the caller should flush.

    Health probes are excluded: a docker healthcheck every ten seconds is a
    request, and it is not one anybody's objective is about.
    """
    if path in ("/health", "/health/ready", "/health/live", "/"):
        return False
    return REQUESTS.add(
        at=datetime.now(UTC),
        path=path,
        status=int(status),
        latency_ms=float(latency_ms),
    )


def flush_requests(session: Session) -> int:
    """Write the buffered request observations. Returns how many."""
    entries = REQUESTS.drain()
    if not entries:
        return 0
    for entry in entries:
        session.add(
            SloObservation(
                observed_at=entry["at"],
                metric=METRIC_LATENCY,
                value=entry["latency_ms"],
                detail={"path": entry["path"], "status": entry["status"]},
            )
        )
        session.add(
            SloObservation(
                observed_at=entry["at"],
                metric=METRIC_AVAILABILITY,
                value=0.0 if entry["status"] >= 500 else 1.0,
                detail={"path": entry["path"], "status": entry["status"]},
            )
        )
    session.commit()
    return len(entries)


def record(
    session: Session,
    metric: str,
    value: float,
    *,
    detail: dict[str, Any] | None = None,
    at: datetime | None = None,
) -> SloObservation:
    """Write one observation now. Used by the collector, once per cycle."""
    row = SloObservation(
        observed_at=(at or datetime.now(UTC)).astimezone(UTC),
        metric=metric,
        value=float(value),
        detail=detail or {},
    )
    session.add(row)
    return row


@dataclass(frozen=True)
class Window:
    since: datetime
    until: datetime
    observations: int
    by_metric: dict[str, int]
    latency_p95_ms: float | None
    availability: float | None
    error_rate: float | None

    @property
    def populated(self) -> bool:
        return self.observations >= MIN_OBSERVATIONS

    def as_dict(self) -> dict[str, Any]:
        return {
            "since": self.since.isoformat(),
            "until": self.until.isoformat(),
            "window_hours": WINDOW.total_seconds() / 3600,
            "observations": self.observations,
            "min_observations": MIN_OBSERVATIONS,
            "populated": self.populated,
            "by_metric": self.by_metric,
            "latency_p95_ms": self.latency_p95_ms,
            "availability": self.availability,
            "error_rate": self.error_rate,
        }


def window(session: Session, *, now: datetime | None = None) -> Window:
    """What the last `WINDOW` holds, counted from the table."""
    until = (now or datetime.now(UTC)).astimezone(UTC)
    since = until - WINDOW
    rows = session.execute(
        select(SloObservation.metric, func.count())
        .where(SloObservation.observed_at >= since)
        .group_by(SloObservation.metric)
    ).all()
    by_metric = {str(metric): int(count) for metric, count in rows}
    total = sum(by_metric.values())

    latencies = [
        float(v)
        for (v,) in session.execute(
            select(SloObservation.value).where(
                SloObservation.observed_at >= since,
                SloObservation.metric == METRIC_LATENCY,
            )
        )
    ]
    p95 = None
    if latencies:
        ordered = sorted(latencies)
        p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
    availability = None
    served = [
        float(v)
        for (v,) in session.execute(
            select(SloObservation.value).where(
                SloObservation.observed_at >= since,
                SloObservation.metric == METRIC_AVAILABILITY,
            )
        )
    ]
    if served:
        availability = sum(served) / len(served)
    return Window(
        since=since,
        until=until,
        observations=total,
        by_metric=by_metric,
        latency_p95_ms=round(p95, 1) if p95 is not None else None,
        availability=round(availability, 4) if availability is not None else None,
        error_rate=round(1 - availability, 4) if availability is not None else None,
    )


__all__ = [
    "MIN_OBSERVATIONS",
    "WINDOW",
    "Window",
    "flush_requests",
    "observe_request",
    "record",
    "window",
    "METRIC_LATENCY",
    "METRIC_AVAILABILITY",
    "METRIC_INGESTION",
    "METRIC_FRESHNESS",
    "METRIC_EXECUTION",
    "METRIC_CYCLE_ERRORS",
]
