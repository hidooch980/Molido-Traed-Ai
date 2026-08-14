"""Where the waste is, which is rarely where the noise is (spec §54, §69).

An outage announces itself. A bottleneck does not: it is a job that retries
four times and succeeds, a sweep that takes eleven minutes instead of one, a
symbol re-fetched every cycle because nothing was written. Nothing fails, no
alert fires, and the cost accumulates in wall-clock and in a two-core box that
has none to spare.

Everything here is derived from data the system already stores - ingestion
runs, data-quality findings, incident counts, bar coverage. No new
instrumentation, no timing sidecar, no extra process. That is a constraint
worth stating: on this host, a profiler with its own memory footprint would be
measuring a slowdown it partly caused.

Findings are ranked by estimated cost rather than by severity, and the two
disagree constantly. A critical seen once is an event; a warning seen ninety
times is a condition, and the condition is usually what is actually expensive.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.incidents import Incident
from app.models.ingestion import IngestionRun
from app.models.market_data import Bar

#: How far back to look. Long enough for a pattern, short enough that something
#: fixed last week stops being reported as a current cost.
WINDOW = timedelta(days=3)

#: A run slower than this many times the median is worth naming. Not an
#: absolute threshold: what counts as slow depends on the instrument and the
#: timeframe, and a fixed number would flag every daily bar or none of them.
SLOW_MULTIPLE = 3.0

#: Below this many runs there is no median worth comparing against, and
#: "slower than usual" is a claim about two data points.
MIN_RUNS_FOR_MEDIAN = 12


@dataclass
class Finding:
    """One place effort is going that produces nothing."""

    kind: str
    subject: str
    detail: str
    #: Rough wasted seconds over the window. Rough is the honest word: it is an
    #: ordering signal, not a measurement, and it is labelled that way in the
    #: payload so nobody reports it as one.
    estimated_cost_seconds: float
    evidence: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "subject": self.subject,
            "detail": self.detail,
            "estimated_cost_seconds": round(self.estimated_cost_seconds, 1),
            "evidence": self.evidence,
        }


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def retry_waste(session: Session, *, now: datetime | None = None) -> list[Finding]:
    """Ingestion that succeeds only after retrying.

    Invisible to every failure count, because it succeeds. The cost is real:
    each retry is a request, a backoff and a slot on a machine with two cores.
    """
    moment = now or datetime.now(UTC)
    rows = session.execute(
        select(
            IngestionRun.instrument_id,
            func.count(IngestionRun.id),
            func.sum(IngestionRun.attempts),
        )
        .where(IngestionRun.started_at >= moment - WINDOW)
        .group_by(IngestionRun.instrument_id)
    ).all()

    findings: list[Finding] = []
    for instrument_id, runs, attempts in rows:
        runs = int(runs or 0)
        attempts = int(attempts or 0)
        if runs == 0 or attempts <= runs:
            continue
        wasted = attempts - runs
        findings.append(
            Finding(
                kind="retries",
                subject=str(instrument_id),
                detail=(
                    f"{wasted} extra attempt(s) across {runs} run(s) - these "
                    "succeed, so nothing counts them as failures"
                ),
                # A retry costs its backoff more than its request. Two seconds
                # apiece is a deliberate under-estimate: over-stating a cost to
                # win an argument is the same error as ignoring it.
                estimated_cost_seconds=wasted * 2.0,
                evidence={"runs": runs, "attempts": attempts, "extra": wasted},
            )
        )
    return findings


def slow_runs(session: Session, *, now: datetime | None = None) -> list[Finding]:
    """Runs far slower than the same series usually takes.

    Compared against that series' own median rather than a fixed threshold. A
    daily bar and a fifteen-minute bar have nothing to say to each other about
    what "slow" means.
    """
    moment = now or datetime.now(UTC)
    rows = session.execute(
        select(IngestionRun.instrument_id, IngestionRun.started_at, IngestionRun.finished_at)
        .where(
            IngestionRun.started_at >= moment - WINDOW,
            IngestionRun.finished_at.is_not(None),
        )
    ).all()

    by_instrument: dict[Any, list[float]] = {}
    for instrument_id, started, finished in rows:
        if started is None or finished is None:
            continue
        by_instrument.setdefault(instrument_id, []).append(
            (finished - started).total_seconds()
        )

    findings: list[Finding] = []
    for instrument_id, durations in by_instrument.items():
        if len(durations) < MIN_RUNS_FOR_MEDIAN:
            continue
        median = _median(durations)
        if median <= 0:
            continue
        slow = [d for d in durations if d > median * SLOW_MULTIPLE]
        if not slow:
            continue
        findings.append(
            Finding(
                kind="slow_runs",
                subject=str(instrument_id),
                detail=(
                    f"{len(slow)} run(s) took over {SLOW_MULTIPLE:g}x this series' "
                    f"median of {median:.1f}s"
                ),
                estimated_cost_seconds=sum(slow) - median * len(slow),
                evidence={
                    "median_seconds": round(median, 2),
                    "slow_runs": len(slow),
                    "total_runs": len(durations),
                    "slowest_seconds": round(max(slow), 2),
                },
            )
        )
    return findings


def empty_work(session: Session, *, now: datetime | None = None) -> list[Finding]:
    """Runs that fetched and wrote nothing, over and over.

    A feed with nothing new is normal once. The same series returning nothing
    on every cycle for days is a symbol nobody trades, a mapping that is wrong,
    or a provider that has quietly stopped - and all three cost a request per
    cycle forever.
    """
    moment = now or datetime.now(UTC)
    rows = session.execute(
        select(
            IngestionRun.instrument_id,
            func.count(IngestionRun.id),
            func.sum(IngestionRun.rows_written),
        )
        .where(IngestionRun.started_at >= moment - WINDOW)
        .group_by(IngestionRun.instrument_id)
    ).all()

    findings: list[Finding] = []
    for instrument_id, runs, written in rows:
        runs = int(runs or 0)
        written = int(written or 0)
        if runs < MIN_RUNS_FOR_MEDIAN or written > 0:
            continue
        findings.append(
            Finding(
                kind="empty_work",
                subject=str(instrument_id),
                detail=(
                    f"{runs} run(s) wrote nothing at all - a wrong symbol "
                    "mapping, an untraded instrument, or a feed that stopped"
                ),
                estimated_cost_seconds=runs * 1.0,
                evidence={"runs": runs, "rows_written": 0},
            )
        )
    return findings


def recurring_incidents(session: Session, *, now: datetime | None = None) -> list[Finding]:
    """Conditions rather than events.

    The loud failure already has somebody's attention. The warning that has
    fired ninety times is the one still costing something, and it is the one a
    severity-ordered list buries.
    """
    moment = now or datetime.now(UTC)
    rows = session.scalars(
        select(Incident).where(
            Incident.occurrences >= 5, Incident.last_seen_at >= moment - WINDOW
        )
    )

    return [
        Finding(
            kind="recurring_incident",
            subject=incident.source,
            detail=f"{incident.summary} - seen {incident.occurrences} times",
            # Not a time measurement and not pretending to be one: it orders
            # this against the others, and the evidence carries the real count.
            estimated_cost_seconds=float(incident.occurrences),
            evidence={
                "occurrences": incident.occurrences,
                "severity": incident.severity,
                "open": incident.resolved_at is None,
                "has_confirmed_remedy": incident.remedy_confirmed,
            },
        )
        for incident in rows
    ]


def unused_coverage(session: Session, *, now: datetime | None = None) -> list[Finding]:
    """Instruments being collected that nothing reads.

    Storage and a request per cycle for a series no decision consults. Named
    rather than deleted: whether an instrument matters is the operator's call,
    and a tool that quietly stopped collecting things would be worse than one
    that says what it suspects.
    """
    moment = now or datetime.now(UTC)
    recent = session.execute(
        select(Bar.instrument_id, func.count(Bar.event_time))
        .where(Bar.ingested_at >= moment - WINDOW)
        .group_by(Bar.instrument_id)
    ).all()

    return [
        Finding(
            kind="thin_coverage",
            subject=str(instrument_id),
            detail=(
                f"only {count} bar(s) arrived in {WINDOW.days} days - a series "
                "this thin cannot support a measurement, and it costs a request "
                "every cycle"
            ),
            estimated_cost_seconds=float(WINDOW.days * 96),
            evidence={"bars_in_window": int(count)},
        )
        for instrument_id, count in recent
        if int(count) < 10
    ]


def analyse(session: Session, *, now: datetime | None = None) -> dict[str, Any]:
    """Every finding, ranked by estimated cost.

    Ranked by cost rather than severity on purpose. The two disagree
    constantly, and the expensive thing is usually the quiet one - which is
    exactly why nobody has fixed it.
    """
    moment = now or datetime.now(UTC)
    findings = (
        retry_waste(session, now=moment)
        + slow_runs(session, now=moment)
        + empty_work(session, now=moment)
        + recurring_incidents(session, now=moment)
        + unused_coverage(session, now=moment)
    )
    findings.sort(key=lambda f: f.estimated_cost_seconds, reverse=True)

    return {
        "window_days": WINDOW.days,
        "findings": [finding.as_dict() for finding in findings],
        "total": len(findings),
        "by_kind": {
            kind: sum(1 for f in findings if f.kind == kind)
            for kind in sorted({f.kind for f in findings})
        },
        "biggest": findings[0].as_dict() if findings else None,
        "cost_is_estimated": True,
        "note": (
            "costs are ordering signals, not measurements - they come from run "
            "counts and durations the system already stores, because a profiler "
            "with its own memory footprint on a two-core host would be measuring "
            "a slowdown it partly caused"
        ),
        "nothing_found_means": (
            "no waste crossed the thresholds in this window, not that the "
            "system is optimal. Several checks need a minimum sample and say "
            "nothing below it"
        ),
    }
