"""Data quality engine (spec §5).

Detectors operate on the raw rows an adapter returned, before anything is
persisted, and again over stored history. Each detector reports what it
expected and what it observed so an operator can verify the finding without
trusting the engine.

The engine never repairs data. Silently "fixing" a bad candle destroys the
evidence that the feed is unreliable, and a repaired-but-wrong price is more
dangerous than an obviously missing one.
"""

from __future__ import annotations

import statistics
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import DataQualityIssue, Severity, Timeframe
from app.models.ingestion import DataQualityFinding, DatasetQuality
from app.providers.base import RawBar
from app.services.sessions import SessionCalendar

# Tunables. Deliberately conservative: a false "warning" costs an operator a
# glance, a missed defect costs a bad trade.
MAX_GAP_SIGMA = 8.0  # bar-to-bar return, in sigmas, before it is a price gap
MAX_VOLUME_SIGMA = 10.0
OUTLIER_SIGMA = 12.0
MIN_SAMPLES_FOR_STATS = 30  # below this, dispersion estimates are not meaningful


@dataclass
class Finding:
    issue: DataQualityIssue
    severity: Severity
    window_start: datetime
    window_end: datetime
    affected_rows: int = 1
    expected: str | None = None
    observed: str | None = None
    details: dict = field(default_factory=dict)


@dataclass
class QualityReport:
    findings: list[Finding] = field(default_factory=list)
    checked_rows: int = 0
    expected_rows: int = 0
    # Whether gaps were compared against a real market calendar or the
    # weekday fallback. Recorded so a consumer can tell how much to trust the
    # missing-candle findings rather than having to assume.
    calendar_aware: bool = False

    @property
    def score(self) -> float:
        """0..1 quality score.

        Weighted by severity and normalized by row count, so a handful of
        defects in a long history scores far better than the same defects in a
        short one. Returns 0.0 for an empty dataset — no data is not perfect
        data.
        """
        if self.checked_rows == 0:
            return 0.0
        weights = {
            Severity.INFO: 0.0,
            Severity.WARNING: 1.0,
            Severity.ERROR: 4.0,
            Severity.CRITICAL: 20.0,
        }
        penalty = sum(weights[f.severity] * f.affected_rows for f in self.findings)
        return max(0.0, min(1.0, 1.0 - penalty / self.checked_rows))

    def count_by_issue(self) -> dict[str, int]:
        return dict(Counter(f.issue.value for f in self.findings))


# --------------------------------------------------------------------- checks
def _check_structure(bars: list[RawBar]) -> list[Finding]:
    """Per-bar sanity: prices positive, OHLC relations coherent."""
    findings: list[Finding] = []
    for bar in bars:
        window = (bar.event_time, bar.event_time)
        if min(bar.open, bar.high, bar.low, bar.close) <= 0:
            findings.append(
                Finding(
                    DataQualityIssue.NON_POSITIVE_PRICE,
                    Severity.CRITICAL,
                    *window,
                    expected="all prices > 0",
                    observed=f"o={bar.open} h={bar.high} l={bar.low} c={bar.close}",
                )
            )
            continue
        if bar.high < max(bar.open, bar.close) or bar.low > min(bar.open, bar.close):
            findings.append(
                Finding(
                    DataQualityIssue.INVALID_OHLC_RELATION,
                    Severity.ERROR,
                    *window,
                    expected="low <= min(open, close) <= max(open, close) <= high",
                    observed=f"o={bar.open} h={bar.high} l={bar.low} c={bar.close}",
                )
            )
        if bar.high < bar.low:
            findings.append(
                Finding(
                    DataQualityIssue.INVALID_OHLC_RELATION,
                    Severity.CRITICAL,
                    *window,
                    expected="high >= low",
                    observed=f"h={bar.high} l={bar.low}",
                )
            )
        if bar.volume is not None and bar.volume < 0:
            findings.append(
                Finding(
                    DataQualityIssue.ABNORMAL_VOLUME,
                    Severity.ERROR,
                    *window,
                    expected="volume >= 0",
                    observed=str(bar.volume),
                )
            )
        if bar.spread is not None and bar.spread < 0:
            findings.append(
                Finding(
                    DataQualityIssue.ABNORMAL_SPREAD,
                    Severity.ERROR,
                    *window,
                    expected="spread >= 0",
                    observed=str(bar.spread),
                )
            )
    return findings


def _check_timestamps(bars: list[RawBar], timeframe: Timeframe) -> list[Finding]:
    """Ordering, duplication, and alignment to the timeframe grid."""
    findings: list[Finding] = []
    seen: set[datetime] = set()
    previous: datetime | None = None

    for bar in bars:
        ts = bar.event_time
        if ts.tzinfo is None:
            findings.append(
                Finding(
                    DataQualityIssue.INVALID_TIMESTAMP,
                    Severity.CRITICAL,
                    ts,
                    ts,
                    expected="timezone-aware UTC timestamp",
                    observed="naive timestamp",
                )
            )
            continue
        if ts in seen:
            findings.append(
                Finding(
                    DataQualityIssue.DUPLICATE_BAR,
                    Severity.ERROR,
                    ts,
                    ts,
                    expected="one bar per timestamp",
                    observed="repeated timestamp",
                )
            )
        seen.add(ts)

        if previous is not None and ts < previous:
            findings.append(
                Finding(
                    DataQualityIssue.NON_MONOTONIC_TIMESTAMP,
                    Severity.WARNING,
                    ts,
                    previous,
                    expected="ascending timestamps",
                    observed=f"{ts.isoformat()} follows {previous.isoformat()}",
                )
            )
        previous = ts

        if not timeframe.is_calendar_based:
            step = int(timeframe.delta.total_seconds())
            if int(ts.timestamp()) % step != 0:
                findings.append(
                    Finding(
                        DataQualityIssue.SESSION_MISMATCH,
                        Severity.WARNING,
                        ts,
                        ts,
                        expected=f"timestamp aligned to {timeframe.value} grid",
                        observed=ts.isoformat(),
                    )
                )
    return findings


def _check_gaps(
    bars: list[RawBar],
    timeframe: Timeframe,
    calendar: SessionCalendar | None = None,
) -> tuple[list[Finding], int]:
    """Missing candles. Returns (findings, expected_row_count).

    With a `calendar`, the expected bars are the ones the market should
    actually have produced: weekends and holidays are removed before anything
    is compared, so every remaining gap is a real loss and is reported at
    WARNING without apology.

    Without one this falls back to the old heuristic — a gap touching a
    Saturday is downgraded to INFO. The fallback is kept because ad-hoc
    evaluation of a raw batch (tests, one-off provider comparisons) has no
    instrument to build a calendar from, but any evaluation that *can* supply
    a calendar should.
    """
    if len(bars) < 2 or timeframe.is_calendar_based:
        return [], len(bars)

    ordered = sorted({b.event_time for b in bars})

    if calendar is not None:
        return _check_gaps_with_calendar(ordered, timeframe, calendar)

    step = timeframe.delta
    findings: list[Finding] = []
    expected = 1

    for previous, current in zip(ordered, ordered[1:], strict=False):
        delta = current - previous
        slots = int(delta / step)
        expected += max(slots, 1)
        if slots <= 1:
            continue
        spans_weekend = any(
            (previous + step * i).weekday() >= 5 for i in range(1, min(slots, 200))
        )
        findings.append(
            Finding(
                DataQualityIssue.MISSING_CANDLE,
                Severity.INFO if spans_weekend else Severity.WARNING,
                previous + step,
                current - step,
                affected_rows=slots - 1,
                expected=f"contiguous {timeframe.value} bars",
                observed=f"{slots - 1} missing bar(s)",
                details={"spans_weekend": spans_weekend, "calendar_aware": False},
            )
        )
    return findings, expected


def _check_gaps_with_calendar(
    ordered: list[datetime], timeframe: Timeframe, calendar: SessionCalendar
) -> tuple[list[Finding], int]:
    """Calendar-aware gap detection.

    Also flags the inverse defect the heuristic could never see: a bar that
    exists when the market was closed. That is either a bad timestamp or a
    provider stitching a synthetic candle, and both matter.
    """
    start, end = ordered[0], ordered[-1] + timeframe.delta
    expected_slots = calendar.expected_bar_times(start, end, timeframe)
    observed = set(ordered)

    findings: list[Finding] = []
    for run_start, run_end, count in calendar.missing_runs(
        observed, start, end, timeframe
    ):
        findings.append(
            Finding(
                DataQualityIssue.MISSING_CANDLE,
                Severity.WARNING,
                run_start,
                run_end,
                affected_rows=count,
                expected=f"{timeframe.value} bar while the market was open",
                observed=f"{count} missing bar(s)",
                details={"calendar_aware": True},
            )
        )

    expected_set = set(expected_slots)
    off_hours = sorted(t for t in observed if t not in expected_set)
    if off_hours:
        findings.append(
            Finding(
                DataQualityIssue.SESSION_MISMATCH,
                Severity.WARNING,
                off_hours[0],
                off_hours[-1],
                affected_rows=len(off_hours),
                expected="bars only while the market is open",
                observed=f"{len(off_hours)} bar(s) outside trading hours",
                details={"first": off_hours[0].isoformat(), "calendar_aware": True},
            )
        )

    return findings, len(expected_slots)


def _check_statistical(bars: list[RawBar]) -> list[Finding]:
    """Price gaps, volume anomalies and outliers, relative to the sample itself.

    Thresholds are in sigmas of the observed return distribution rather than
    fixed percentages, because a 1% move is routine for crypto and extraordinary
    for a major FX pair. Below `MIN_SAMPLES_FOR_STATS` no claim is made at all.
    """
    ordered = sorted(bars, key=lambda b: b.event_time)
    if len(ordered) < MIN_SAMPLES_FOR_STATS:
        return []

    findings: list[Finding] = []
    returns: list[float] = []
    for prev, cur in zip(ordered, ordered[1:], strict=False):
        if prev.close > 0:
            returns.append((cur.open - prev.close) / prev.close)

    if len(returns) >= MIN_SAMPLES_FOR_STATS:
        mean_r = statistics.fmean(returns)
        stdev_r = statistics.pstdev(returns)
        if stdev_r > 0:
            for (prev, cur), ret in zip(
                zip(ordered, ordered[1:], strict=False), returns, strict=False
            ):
                sigmas = abs(ret - mean_r) / stdev_r
                if sigmas > MAX_GAP_SIGMA:
                    findings.append(
                        Finding(
                            DataQualityIssue.PRICE_GAP,
                            Severity.WARNING,
                            prev.event_time,
                            cur.event_time,
                            expected=f"|gap| <= {MAX_GAP_SIGMA} sigma",
                            observed=f"{sigmas:.1f} sigma ({ret:.4%})",
                            details={"sigmas": round(sigmas, 2), "return": ret},
                        )
                    )

    ranges = [b.high - b.low for b in ordered]
    if len(ranges) >= MIN_SAMPLES_FOR_STATS:
        mean_range = statistics.fmean(ranges)
        stdev_range = statistics.pstdev(ranges)
        if stdev_range > 0:
            for bar, rng in zip(ordered, ranges, strict=False):
                sigmas = abs(rng - mean_range) / stdev_range
                if sigmas > OUTLIER_SIGMA:
                    findings.append(
                        Finding(
                            DataQualityIssue.OUTLIER,
                            Severity.WARNING,
                            bar.event_time,
                            bar.event_time,
                            expected=f"bar range within {OUTLIER_SIGMA} sigma",
                            observed=f"{sigmas:.1f} sigma",
                            details={"sigmas": round(sigmas, 2), "range": rng},
                        )
                    )

    volumes = [b.volume for b in ordered if b.volume is not None]
    if len(volumes) >= MIN_SAMPLES_FOR_STATS:
        mean_v = statistics.fmean(volumes)
        stdev_v = statistics.pstdev(volumes)
        if stdev_v > 0:
            for bar in ordered:
                if bar.volume is None:
                    continue
                sigmas = abs(bar.volume - mean_v) / stdev_v
                if sigmas > MAX_VOLUME_SIGMA:
                    findings.append(
                        Finding(
                            DataQualityIssue.ABNORMAL_VOLUME,
                            Severity.INFO,
                            bar.event_time,
                            bar.event_time,
                            expected=f"volume within {MAX_VOLUME_SIGMA} sigma",
                            observed=f"{sigmas:.1f} sigma",
                            details={"sigmas": round(sigmas, 2)},
                        )
                    )
    return findings


def evaluate_bars(
    bars: list[RawBar],
    timeframe: Timeframe,
    calendar: SessionCalendar | None = None,
) -> QualityReport:
    """Run every detector over a batch of raw bars.

    Pass a `calendar` whenever one is available — it turns gap detection from
    a weekday guess into a real comparison against the market's schedule.
    """
    report = QualityReport(checked_rows=len(bars), calendar_aware=calendar is not None)
    if not bars:
        return report

    report.findings.extend(_check_structure(bars))
    report.findings.extend(_check_timestamps(bars, timeframe))
    gap_findings, expected = _check_gaps(bars, timeframe, calendar)
    report.findings.extend(gap_findings)
    report.expected_rows = expected
    report.findings.extend(_check_statistical(bars))
    return report


def detect_provider_conflicts(
    series_by_provider: dict[str, list[RawBar]],
    *,
    tolerance: float = 0.002,
) -> list[Finding]:
    """Disagreement between providers on the same bar (spec §5).

    A conflict is reported, never resolved here. Which feed to believe is a
    policy decision that belongs to the operator via `Provider.trust_weight`.
    """
    if len(series_by_provider) < 2:
        return []

    indexed = {
        code: {bar.event_time: bar for bar in bars} for code, bars in series_by_provider.items()
    }
    codes = sorted(indexed)
    findings: list[Finding] = []
    shared = set.intersection(*(set(indexed[c]) for c in codes))

    for ts in sorted(shared):
        closes = {c: indexed[c][ts].close for c in codes}
        low, high = min(closes.values()), max(closes.values())
        if low <= 0:
            continue
        divergence = (high - low) / low
        if divergence > tolerance:
            findings.append(
                Finding(
                    DataQualityIssue.PROVIDER_CONFLICT,
                    Severity.ERROR,
                    ts,
                    ts,
                    expected=f"provider closes within {tolerance:.2%}",
                    observed=f"{divergence:.2%}",
                    details={"closes": closes},
                )
            )
    return findings


def compare_providers(
    session: Session,
    instrument_id: uuid.UUID,
    timeframe: Timeframe,
    *,
    since: datetime | None = None,
    tolerance: float = 0.002,
    detected_at: datetime | None = None,
) -> dict[str, Any]:
    """Run the conflict detector over what each provider actually stored.

    Reads bars back out of the database rather than comparing an ingestion
    batch, because two providers rarely deliver in the same request and a
    conflict that only exists across two runs is still a conflict.

    Only the latest revision per (provider, event_time) is compared. A
    superseded bar disagreeing with a current one is not a conflict between
    feeds; it is one feed correcting itself, which is the system working.

    Findings are attributed to the provider whose close sits furthest from the
    group. That is a reporting choice, not a verdict on who is wrong - which
    feed to believe is the operator's call via `Provider.trust_weight`, and
    this function deliberately does not make it.
    """
    from app.models.instruments import Provider
    from app.models.market_data import Bar

    rows = session.execute(
        select(
            Provider.code,
            Provider.id,
            Bar.event_time,
            Bar.close,
            Bar.revision,
            Bar.open,
            Bar.high,
            Bar.low,
        )
        .join(Provider, Provider.id == Bar.provider_id)
        .where(
            Bar.instrument_id == instrument_id,
            Bar.timeframe == timeframe,
            *( [Bar.event_time >= since] if since else [] ),
        )
        .order_by(Bar.event_time, Bar.revision)
    ).all()

    # Later revisions overwrite earlier ones for the same (provider, instant).
    latest: dict[tuple[str, datetime], RawBar] = {}
    provider_ids: dict[str, uuid.UUID] = {}
    for code, provider_id, event_time, close, _revision, open_, high, low in rows:
        # Coerced to float here rather than left as the Numeric column's
        # Decimal. The detector puts the disagreeing closes into a finding's
        # `details`, that column is JSON, and Decimal is not serialisable - so
        # a Decimal reaching this far crashes the sweep on the first real
        # conflict and never on a clean one. Found by a test that stored two
        # disagreeing feeds instead of two dictionaries.
        latest[(code, event_time)] = RawBar(
            event_time=event_time,
            open=float(open_),
            high=float(high),
            low=float(low),
            close=float(close),
            volume=0.0,
        )
        provider_ids[code] = provider_id

    series: dict[str, list[RawBar]] = {}
    for (code, _event_time), bar in latest.items():
        series.setdefault(code, []).append(bar)
    for bars in series.values():
        bars.sort(key=lambda b: b.event_time)

    if len(series) < 2:
        # Not "no conflicts". One feed cannot disagree with itself, and
        # reporting a clean result here would be a measurement nobody made.
        return {
            "compared": False,
            "reason": (
                f"{len(series)} provider(s) have bars for this series; a conflict "
                "needs two"
            ),
            "providers": sorted(series),
            "conflicts": 0,
            "written": 0,
        }

    findings = detect_provider_conflicts(series, tolerance=tolerance)

    written = 0
    if findings:
        # Attributed to the first provider alphabetically so the same conflict
        # lands on the same row every sweep instead of alternating and
        # defeating the repeat-collapsing in `persist_findings`.
        owner = sorted(provider_ids)[0]
        written = persist_findings(
            session,
            instrument_id=instrument_id,
            provider_id=provider_ids[owner],
            timeframe=timeframe,
            findings=findings,
            detected_at=detected_at,
        )

    return {
        "compared": True,
        "providers": sorted(series),
        "bars_compared": len(set.intersection(*(
            {bar.event_time for bar in bars} for bars in series.values()
        ))),
        "conflicts": len(findings),
        "written": written,
        "tolerance": tolerance,
    }


#: How long a market could plausibly be shut.
#:
#: Beyond this a feed is stale whatever any calendar says: no exchange closes
#: for ten days, so a gap this wide is the feed rather than the schedule. It
#: also bounds the walk below, which would otherwise step a dead M1 feed one
#: minute at a time across however long it has been dead.
MAX_PLAUSIBLE_CLOSURE = timedelta(days=10)


def _missed_open_bars(
    calendar: Any,
    latest_event_time: datetime,
    timeframe: Timeframe,
    now: datetime,
    *,
    stop_after: int,
) -> int:
    """Bars the market should have produced since `latest_event_time`.

    Counts slots the calendar calls open, and stops as soon as the answer can
    no longer change the verdict - the caller only needs to know whether the
    count exceeds a threshold, and walking a whole weekend of M1 slots to
    return 2880 when 4 would do is work nobody reads.
    """
    step = timeframe.delta
    cursor = latest_event_time + step
    missed = 0
    while cursor < now and missed <= stop_after:
        if calendar.is_open(cursor):
            missed += 1
        cursor += step
    return missed


def check_staleness(
    latest_event_time: datetime | None,
    timeframe: Timeframe,
    *,
    now: datetime | None = None,
    max_missed_bars: int = 3,
    calendar: Any | None = None,
) -> Finding | None:
    """Stale-feed check backing the market-data failure policy (spec §40).

    **A shut market is not a dead feed.** Without a calendar this measures
    wall-clock age, and every Saturday at 02:45 that reported every
    instrument on every timeframe as CRITICAL stale: the collector skips a
    market only once it has been closed for six hours - deliberately, because
    a session's final bars often arrive late - so the first cycle inside that
    grace window ran this check against a market that had been shut since
    Friday and was behaving exactly as it should.

    Those findings are permanent. Nothing in this codebase resolves a
    finding, and an unresolved error-level one blocks its dataset's training
    eligibility for good, so a weekend was quietly costing eligibility that
    could never be won back.

    Given a calendar, staleness is counted in bars the market should have
    produced. Without one the old wall-clock behaviour is kept exactly, so a
    caller that has no calendar to offer is no worse off than before.
    """
    now = now or datetime.now(UTC)
    if latest_event_time is None:
        return Finding(
            DataQualityIssue.STALE_DATA,
            Severity.CRITICAL,
            now,
            now,
            expected="recent market data",
            observed="no data at all",
        )
    age = now - latest_event_time
    limit = timeframe.delta * max_missed_bars
    if age <= limit:
        # Market-open time can never exceed wall-clock time, so a feed inside
        # the wall-clock limit is inside the calendar limit too. Checked
        # first because it is the ordinary case and costs nothing.
        return None

    if (
        calendar is not None
        and not timeframe.is_calendar_based
        and age <= MAX_PLAUSIBLE_CLOSURE
    ):
        missed = _missed_open_bars(
            calendar, latest_event_time, timeframe, now, stop_after=max_missed_bars
        )
        if missed <= max_missed_bars:
            return None
        return Finding(
            DataQualityIssue.STALE_DATA,
            Severity.CRITICAL,
            latest_event_time,
            now,
            expected=f"no more than {max_missed_bars} missed open bars",
            # The count is reported rather than the wall-clock age, because
            # the age is the thing that was misleading: "31 hours old" over a
            # weekend reads as a broken feed and is a closed market.
            observed=f"{missed}+ open bars missed, {age} of wall clock",
            details={"age_seconds": age.total_seconds(), "missed_open_bars": missed},
        )

    return Finding(
        DataQualityIssue.STALE_DATA,
        Severity.CRITICAL,
        latest_event_time,
        now,
        expected=f"data newer than {limit}",
        observed=f"{age} old",
        details={"age_seconds": age.total_seconds()},
    )


# ------------------------------------------------------------- persistence
def persist_findings(
    session: Session,
    *,
    instrument_id: uuid.UUID,
    provider_id: uuid.UUID,
    timeframe: Timeframe,
    findings: list[Finding],
    run_id: uuid.UUID | None = None,
    detected_at: datetime | None = None,
) -> int:
    """Store findings, collapsing repeats of the same issue+window.

    Re-running the engine over the same history must not inflate the finding
    count, otherwise the dataset score would decay simply from being checked.
    """
    detected_at = detected_at or datetime.now(UTC)
    written = 0

    for finding in findings:
        existing = session.scalar(
            select(DataQualityFinding).where(
                DataQualityFinding.instrument_id == instrument_id,
                DataQualityFinding.provider_id == provider_id,
                DataQualityFinding.timeframe == timeframe,
                DataQualityFinding.issue == finding.issue,
                DataQualityFinding.window_start == finding.window_start,
            )
        )
        if existing is not None:
            existing.detected_at = detected_at
            existing.affected_rows = finding.affected_rows
            existing.observed = finding.observed
            existing.details = finding.details
            existing.run_id = run_id or existing.run_id
            continue

        session.add(
            DataQualityFinding(
                instrument_id=instrument_id,
                provider_id=provider_id,
                timeframe=timeframe,
                run_id=run_id,
                issue=finding.issue,
                severity=finding.severity,
                window_start=finding.window_start,
                window_end=finding.window_end,
                detected_at=detected_at,
                affected_rows=finding.affected_rows,
                expected=finding.expected,
                observed=finding.observed,
                details=finding.details,
            )
        )
        written += 1

    session.flush()
    return written


#: Issues a re-check can actually settle.
#:
#: Narrow on purpose, and the exclusions are the interesting part. A finding
#: may only be resolved when the system can *prove* it no longer holds; a
#: check that cannot fail is not evidence, it is a licence to readmit bad
#: data quietly.
#:
#: `duplicate_bar` is the case that makes the point. It says the provider
#: sent one timestamp twice **in a batch**, and the batch is gone. Storage
#: keys bars by revision, so the same instant legitimately appears twice as a
#: correction - re-checking would either always resolve (dedupe by instant)
#: or never resolve (do not), and neither answer is about the defect that was
#: reported. It stays open, because nothing here can honestly close it.
#:
#: `invalid_timestamp` is excluded for the mirror reason: stored timestamps
#: are timezone-aware by construction, so the check could only ever pass.
#:
#: `missing_candle`, `price_gap`, `outlier` and `session_mismatch` need more
#: than the window they name - a series, a distribution, a schedule - so a
#: re-check over the window alone would be a different, weaker test wearing
#: the same name. `provider_conflict` needs a second provider's series.
RECHECKABLE: frozenset[DataQualityIssue] = frozenset(
    {DataQualityIssue.INVALID_OHLC_RELATION, DataQualityIssue.NON_POSITIVE_PRICE}
)

#: How many findings one re-evaluation settles.
#:
#: Bounded because this runs inside the collector's per-entry work every
#: cycle, and a dataset carrying three thousand open findings would turn a
#: fifteen-minute sweep into a backlog drain. Oldest first, so the queue
#: empties over cycles rather than never.
RECHECK_BATCH = 50


def _newest_stored_bar(
    session: Session,
    instrument_id: uuid.UUID,
    provider_id: uuid.UUID,
    timeframe: Timeframe,
    event_time: datetime,
) -> RawBar | None:
    """The bar a reader would actually see at that instant, or None.

    Newest revision, because that is what `point_in_time` serves and
    therefore what every downstream consumer works from. Judging a superseded
    revision would keep a finding open about data nothing reads.
    """
    from app.models.market_data import Bar

    row = session.scalars(
        select(Bar)
        .where(
            Bar.instrument_id == instrument_id,
            Bar.provider_id == provider_id,
            Bar.timeframe == timeframe,
            Bar.event_time == event_time,
        )
        .order_by(Bar.revision.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    return RawBar(
        event_time=row.event_time,
        open=float(row.open),
        high=float(row.high),
        low=float(row.low),
        close=float(row.close),
        volume=None if row.volume is None else float(row.volume),
    )


def recheck_findings(
    session: Session,
    *,
    instrument_id: uuid.UUID,
    provider_id: uuid.UUID,
    timeframe: Timeframe,
    now: datetime | None = None,
    limit: int = RECHECK_BATCH,
) -> int:
    """Close findings that the stored data no longer supports. Returns how many.

    Nothing in this codebase had ever set `resolved_at` - 0 of 95,795 on
    production - and `_persisted_finding_stats` counts every unresolved
    error-level finding as blocking, which the training-eligibility gate
    requires to be zero. So one bad bar, once, blocked its dataset forever:
    the gate had an entrance and no exit, and a dataset that had been
    repaired looked exactly like one that never was.

    A finding is closed only by re-running **the same detector** that raised
    it, over the data as it stands now. Not by age, not by assumption, and
    never by a second implementation of the same test - two checkers for one
    property drift apart, and the drift shows up as data quietly readmitted.
    """
    moment = now or datetime.now(UTC)
    open_findings = list(
        session.scalars(
            select(DataQualityFinding)
            .where(
                DataQualityFinding.instrument_id == instrument_id,
                DataQualityFinding.provider_id == provider_id,
                DataQualityFinding.timeframe == timeframe,
                DataQualityFinding.resolved_at.is_(None),
                DataQualityFinding.issue.in_(
                    [issue.value for issue in RECHECKABLE]
                    + [DataQualityIssue.STALE_DATA.value]
                ),
            )
            .order_by(DataQualityFinding.detected_at)
            .limit(limit)
        )
    )
    if not open_findings:
        return 0

    _stored, _first, last_bar = _stored_bar_stats(
        session, instrument_id, provider_id, timeframe
    )

    resolved = 0
    for finding in open_findings:
        issue = DataQualityIssue(finding.issue)

        if issue is DataQualityIssue.STALE_DATA:
            # The finding says the newest bar at the time was `window_start`.
            # Any bar after it is the feed answering, so the outage it
            # describes is over - which is a fact about stored data and needs
            # no calendar to settle.
            if last_bar is not None and last_bar > finding.window_start:
                finding.resolved_at = moment
                resolved += 1
            continue

        bar = _newest_stored_bar(
            session, instrument_id, provider_id, timeframe, finding.window_start
        )
        if bar is None:
            # The bar is not there to be wrong any more. Retention trimmed it
            # or a correction replaced the instant; either way the defect this
            # names is not in the data a reader would get.
            finding.resolved_at = moment
            resolved += 1
            continue

        if not any(f.issue is issue for f in _check_structure([bar])):
            finding.resolved_at = moment
            resolved += 1

    if resolved:
        session.flush()
    return resolved


def update_dataset_quality(
    session: Session,
    *,
    instrument_id: uuid.UUID,
    provider_id: uuid.UUID,
    timeframe: Timeframe,
    report: QualityReport,
    coverage_start: datetime | None = None,
    coverage_end: datetime | None = None,
) -> DatasetQuality:
    """Roll findings up into the training-eligibility gate.

    The rollup is computed from **persisted state** — every stored bar and
    every open finding for this dataset — not from the batch that happened to
    trigger this call. That distinction is the whole correctness of the gate:
    an incremental collection cycle typically carries a handful of new bars,
    and scoring the dataset from that batch would reset a hard-won "blocked"
    verdict to "eligible" every fifteen minutes, silently readmitting data that
    a full evaluation had rejected.

    `report` still matters — its findings were just persisted by the caller —
    but it is an *input to* the stored state, never a substitute for it.
    """
    settings = get_settings()
    record = session.scalar(
        select(DatasetQuality).where(
            DatasetQuality.instrument_id == instrument_id,
            DatasetQuality.provider_id == provider_id,
            DatasetQuality.timeframe == timeframe,
        )
    )
    if record is None:
        record = DatasetQuality(
            instrument_id=instrument_id, provider_id=provider_id, timeframe=timeframe
        )
        session.add(record)

    # Close what the data no longer supports, before counting what is left.
    #
    # The order matters: run after the count and a finding cleared on this
    # pass still blocks for another fifteen minutes, which on a gate that had
    # no exit at all for its whole life would be an odd place to add a delay.
    recheck_findings(
        session,
        instrument_id=instrument_id,
        provider_id=provider_id,
        timeframe=timeframe,
    )

    stored_bars, first_bar, last_bar = _stored_bar_stats(
        session, instrument_id, provider_id, timeframe
    )
    penalty, open_findings, blocking = _persisted_finding_stats(
        session, instrument_id, provider_id, timeframe
    )

    score = 0.0 if stored_bars == 0 else max(0.0, min(1.0, 1.0 - penalty / stored_bars))

    record.score = round(score, 3)
    record.coverage_start = first_bar or coverage_start or record.coverage_start
    record.coverage_end = last_bar or coverage_end or record.coverage_end
    # Expected-bar count only grows as coverage grows; a small batch must not
    # shrink it.
    record.expected_bars = max(record.expected_bars or 0, report.expected_rows, stored_bars)
    record.actual_bars = stored_bars
    record.open_findings = open_findings
    # Both conditions must hold: a good average score cannot outvote a single
    # error-level defect such as a negative price or a duplicated bar.
    record.is_training_eligible = (
        score >= settings.min_quality_score and blocking == 0 and stored_bars > 0
    )
    record.evaluated_at = datetime.now(UTC)
    session.flush()
    return record


def _stored_bar_stats(
    session: Session,
    instrument_id: uuid.UUID,
    provider_id: uuid.UUID,
    timeframe: Timeframe,
) -> tuple[int, datetime | None, datetime | None]:
    """Distinct bars actually stored, and the window they span.

    Counts distinct `event_time` rather than rows: a revised bar is a second
    row for the same instant, and counting it twice would make a corrected
    dataset look larger than an uncorrected one.
    """
    from app.models.market_data import Bar

    total, first, last = session.execute(
        select(
            func.count(func.distinct(Bar.event_time)),
            func.min(Bar.event_time),
            func.max(Bar.event_time),
        ).where(
            Bar.instrument_id == instrument_id,
            Bar.provider_id == provider_id,
            Bar.timeframe == timeframe,
        )
    ).one()
    return int(total or 0), first, last


def _persisted_finding_stats(
    session: Session,
    instrument_id: uuid.UUID,
    provider_id: uuid.UUID,
    timeframe: Timeframe,
) -> tuple[float, int, int]:
    """(weighted penalty, open count, blocking count) from stored findings."""
    weights = {
        Severity.INFO: 0.0,
        Severity.WARNING: 1.0,
        Severity.ERROR: 4.0,
        Severity.CRITICAL: 20.0,
    }
    rows = session.scalars(
        select(DataQualityFinding).where(
            DataQualityFinding.instrument_id == instrument_id,
            DataQualityFinding.provider_id == provider_id,
            DataQualityFinding.timeframe == timeframe,
            DataQualityFinding.resolved_at.is_(None),
        )
    )
    penalty = 0.0
    open_count = 0
    blocking = 0
    for row in rows:
        severity = Severity(row.severity)
        penalty += weights[severity] * row.affected_rows
        open_count += 1
        if severity in (Severity.ERROR, Severity.CRITICAL):
            blocking += 1
    return penalty, open_count, blocking


def coverage_window(bars: list[RawBar]) -> tuple[datetime | None, datetime | None]:
    if not bars:
        return None, None
    times = [b.event_time for b in bars]
    return min(times), max(times)


def expected_bar_count(start: datetime, end: datetime, timeframe: Timeframe) -> int:
    """Naive slot count for a window. Ignores sessions; use as an upper bound."""
    if timeframe.is_calendar_based:
        return 0
    span: timedelta = end - start
    return max(0, int(span / timeframe.delta))
