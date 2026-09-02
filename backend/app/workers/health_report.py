"""Every scheduled cycle, in one command, so nobody has to go looking.

`healthcheck` answers one question for Docker - did a cycle finish recently -
and is deliberately too thin to answer any other, because it has to run in
under fifteen seconds on a busy machine. This is the other half: what an
operator wants when they ask "is anything broken", which is a different
question and can afford a second.

The check nobody had was per *job*. The collector runs nine schedules and
eight of them are daily, so their logs have rotated away long before anybody
looks - and the container is recreated on every deploy, which throws the log
away entirely. Twice this week a job was found to have been silently dead for
weeks, both times by accident and neither time by a check.

So freshness is read from what each job *writes* rather than from what it
logged. A row is evidence that survives a redeploy; a log line is not.

**Every threshold is the job's own schedule, doubled.** Not a number anybody
chose: a daily job that has not written in two days has missed one, and that
is the earliest moment the evidence can distinguish "late" from "stopped".
Doubling is what keeps a job that runs at 03:00 from being called stale at
03:00 the next day by a clock a minute out.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

#: What each schedule writes, and how often it is meant to write it. The
#: table and column are the evidence; the interval is the job's own cadence
#: taken from `collector._cron_jobs`, not an opinion about how fresh is fresh.
#:
#: A job absent from here is a job this report cannot see, which is why the
#: list is checked against the worker's schedule by a test rather than left
#: to drift as jobs are added.
WATCHED: tuple[tuple[str, str, str, timedelta], ...] = (
    ("collect", "ingestion_runs", "started_at", timedelta(minutes=15)),
    ("features", "feature_values", "event_time", timedelta(minutes=15)),
    ("bars", "ohlcv", "event_time", timedelta(minutes=15)),
    ("decisions", "journal_entries", "created_at", timedelta(minutes=15)),
    ("equity", "equity_samples", "recorded_at", timedelta(minutes=15)),
    ("episodes", "episodes", "created_at", timedelta(days=1)),
    ("provider conflicts", "data_quality_findings", "created_at", timedelta(days=1)),
    ("instrument dna", "symbol_profiles", "updated_at", timedelta(days=1)),
)

#: How many times its own cadence a job may miss before it is called stale.
#: Two: one missed run is late, and the run after that is the first evidence
#: nobody is coming.
GRACE = 2


@dataclass(frozen=True)
class Check:
    """One job, and whether it has written recently enough."""

    job: str
    table: str
    rows: int
    newest: datetime | None
    cadence: timedelta

    def age(self, now: datetime) -> timedelta | None:
        return None if self.newest is None else now - self.newest

    def stale(self, now: datetime) -> bool:
        """Never written counts as stale. An empty table is not a fresh one.

        The one exception a caller has to make is a job that has legitimately
        never run on a young deployment, and that is a judgement about the
        deployment rather than about the job.
        """
        age = self.age(now)
        return age is None or age > self.cadence * GRACE

    def line(self, now: datetime) -> str:
        if self.newest is None:
            return f"  STALE  {self.job:<20} {self.table:<24} never written"
        age = self.age(now)
        assert age is not None
        mark = "STALE " if self.stale(now) else "  ok  "
        return (
            f"  {mark} {self.job:<20} {self.table:<24} "
            f"{self.rows:>10,} rows, {_ago(age)} ago"
        )


def _ago(span: timedelta) -> str:
    seconds = int(span.total_seconds())
    if seconds < 0:
        # A row stamped in the future is a clock problem and saying "0s ago"
        # would hide it.
        return f"-{_ago(-span)}"
    if seconds < 90:
        return f"{seconds}s"
    if seconds < 5400:
        return f"{seconds // 60}m"
    if seconds < 172800:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def gather(session: Session, *, watched: Any = WATCHED) -> list[Check]:
    """One aggregate per watched table.

    Count and max in the same pass. Two queries per table would let the row
    count and the timestamp come from different instants, which is a small
    lie that shows up exactly when the system is busy and somebody is
    reading this because it is busy.
    """
    checks: list[Check] = []
    for job, table, column, cadence in watched:
        # The table and column names come from the constant above, never from
        # a caller, so there is nothing here for a parameter to bind.
        row = session.execute(
            text(f"select count(*), max({column}) from {table}")  # noqa: S608
        ).one()
        newest = row[1]
        if newest is not None and newest.tzinfo is None:
            newest = newest.replace(tzinfo=UTC)
        checks.append(
            Check(
                job=job,
                table=table,
                rows=int(row[0] or 0),
                newest=newest,
                cadence=cadence,
            )
        )
    return checks


def report(session: Session, *, now: datetime | None = None) -> tuple[bool, str]:
    """Every cycle, one line each. True when nothing is stale."""
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    checks = gather(session)
    stale = [c for c in checks if c.stale(moment)]

    lines = [f"cycles at {moment.isoformat(timespec='seconds')}"]
    lines.extend(c.line(moment) for c in checks)

    # The settings that decide what a trade looks like, printed beside the
    # freshness because "everything is running" and "running the geometry you
    # think it is" are different reassurances and both get asked for at once.
    from app.core.config import get_settings
    from app.workers.forward import STOP_MULTIPLE, TARGET_MULTIPLE

    settings = get_settings()
    lines.append(
        f"  ---   geometry stop {STOP_MULTIPLE}x ATR, target "
        f"{TARGET_MULTIPLE}R; risk "
        f"{getattr(settings, 'autotrade_risk_percent', '?')}% per trade"
    )
    strategies = str(getattr(settings, "account_strategies", "") or "")
    for piece in [p for p in strategies.split(",") if p.strip()]:
        lines.append(f"  ---   {piece.strip()}")

    if stale:
        lines.append(
            f"STALE: {', '.join(c.job for c in stale)} - "
            "each has missed at least two of its own runs"
        )
    else:
        lines.append("all cycles fresh")
    return not stale, "\n".join(lines)


def main() -> int:
    """Print the report; exit non-zero when something is stale.

        docker exec molidotrade-collector-1 python -m app.workers.health_report
    """
    from app.db.session import session_scope

    with session_scope() as session:
        healthy, text_out = report(session)
    print(text_out)
    return 0 if healthy else 1


if __name__ == "__main__":  # pragma: no cover - a command, not a code path
    raise SystemExit(main())
