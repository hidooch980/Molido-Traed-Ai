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

Two things the first version of this got wrong, both of which made it cry
wolf, which is the one failure a check like this cannot survive:

*The evidence has to be a write time.* `features` and `bars` were read from
`event_time`, which is the bar's own timestamp. An H1 bar's newest event_time
is never fresher than the last hourly close, so against a fifteen-minute
threshold those two lines went red for three quarters of every hour while
both jobs ran perfectly. `computed_at` and `ingested_at` are when the row was
written, which is the question this file says it asks.

*A shut market is not a stopped job.* `decisions` are written when the rule
ranks a fresh bar, so on a Sunday morning the newest one is from Friday's
close and nothing is wrong. Jobs marked `open_only` are aged in market-open
time, using the same calendar the collector consults before skipping a closed
market - the same seam, and the same fix, as `check_staleness`.
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
#: The fifth field says the job only has work while a market trades; the
#: sixth names a column holding the symbol each row is about, when the table
#: has one. That column is what makes the weekend judgement specific: a job is
#: aged against the markets it has actually been writing about lately, not
#: against the whole watchlist. `decisions` are the case that needs it -
#: crypto trades every hour of the weekend and never appears in the journal,
#: because the ranking is narrowed to what the broker offers before it runs,
#: so a union that included it would call a correctly quiet Sunday a failure.
WATCHED: tuple[tuple[str, str, str, timedelta, bool, str | None], ...] = (
    ("collect", "ingestion_runs", "started_at", timedelta(minutes=15), True, None),
    ("features", "feature_values", "computed_at", timedelta(minutes=15), True, None),
    ("bars", "ohlcv", "ingested_at", timedelta(minutes=15), True, None),
    # An hour, not the cycle's fifteen minutes: the journal is unique on
    # (symbol, bar, arm), so a cycle that runs four times inside one H1 bar
    # writes on the first and is idempotent on the other three. The cadence a
    # job can achieve is the one it must be judged against.
    ("decisions", "journal_entries", "created_at", timedelta(hours=1), True, "symbol"),
    ("equity", "equity_samples", "recorded_at", timedelta(minutes=15), False, None),
    ("episodes", "episodes", "created_at", timedelta(days=1), False, None),
    ("provider conflicts", "data_quality_findings", "created_at", timedelta(days=1), False, None),
    ("instrument dna", "symbol_profiles", "updated_at", timedelta(days=1), False, None),
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
    #: True when this job only has work to do while a market is open. Such a
    #: job goes quiet on a weekend by design, and calling that a failure
    #: teaches an operator to ignore the report.
    open_only: bool = False
    #: A column in the same table naming the market each row is about, when
    #: the table has one. Used to age this job against the markets it is
    #: actually writing about rather than against every symbol watched.
    symbol_column: str | None = None

    def age(self, now: datetime) -> timedelta | None:
        return None if self.newest is None else now - self.newest

    @property
    def limit(self) -> timedelta:
        return self.cadence * GRACE

    def stale(self, now: datetime, *, open_age: timedelta | None = None) -> bool:
        """Never written counts as stale. An empty table is not a fresh one.

        The one exception a caller has to make is a job that has legitimately
        never run on a young deployment, and that is a judgement about the
        deployment rather than about the job.

        `open_age` is how much of that wall-clock age the market was open for.
        It is only ever consulted for an `open_only` job that has already
        failed the wall-clock test - open time cannot exceed wall-clock time,
        so a job inside the wall-clock limit is inside the open-time limit and
        the calendar is never walked for it.
        """
        age = self.age(now)
        if age is None:
            return True
        if age <= self.limit:
            return False
        if self.open_only and open_age is not None:
            return open_age > self.limit
        return True

    def line(self, now: datetime, *, open_age: timedelta | None = None) -> str:
        if self.newest is None:
            return f"  STALE  {self.job:<20} {self.table:<24} never written"
        age = self.age(now)
        assert age is not None
        mark = "STALE " if self.stale(now, open_age=open_age) else "  ok  "
        # The open-time figure is printed only when it is what decided the
        # verdict, because on an open market it always equals the age and a
        # column that repeats itself is a column nobody reads.
        aside = ""
        if self.open_only and open_age is not None and age > self.limit:
            aside = f" ({_ago(open_age)} of it open)"
        return (
            f"  {mark} {self.job:<20} {self.table:<24} "
            f"{self.rows:>10,} rows, {_ago(age)} ago{aside}"
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


#: How long a market could plausibly be shut. Past this the calendar is not
#: the explanation whatever it says, and it also bounds the walk below.
MAX_PLAUSIBLE_CLOSURE = timedelta(days=10)

#: The resolution the open-time walk steps at. Fifteen minutes because that is
#: the cycle's own cadence: a finer step would cost more and could not change
#: any verdict this file reaches.
OPEN_STEP = timedelta(minutes=15)


def open_time_since(
    calendars: list[Any], since: datetime, now: datetime, *, stop_after: timedelta
) -> timedelta:
    """How long *any* watched market was open between `since` and `now`.

    The union rather than an average: these jobs sweep the whole watchlist, so
    one open market is enough to give them work, and asking whether the median
    instrument was trading would excuse a job that had stopped while crypto
    was still running.

    Stops as soon as the answer can no longer change a verdict - the caller
    only needs to know whether the span exceeds a threshold, and counting a
    whole dead fortnight to return it exactly is work nobody reads.
    """
    if not calendars:
        # No calendar to offer, so no excuse to grant: the wall-clock verdict
        # stands, which is exactly where this report was before.
        return now - since
    # Anything older than the longest plausible closure counts as open without
    # being checked. Nothing shuts that long, so past there the calendar is
    # not the explanation whatever it would say - and the walk stays bounded.
    cursor = max(since, now - MAX_PLAUSIBLE_CLOSURE)
    span = cursor - since
    while cursor < now and span <= stop_after:
        if any(c.is_open(cursor) for c in calendars):
            span += OPEN_STEP
        cursor += OPEN_STEP
    return span


def _calendars(session: Session, check: Check) -> list[Any]:
    """The calendars of the markets this job is answerable for.

    Ordinarily the whole watchlist: `collect`, `features` and `bars` sweep all
    of it, and one open market anywhere is enough to give them work.

    A job whose table names its own symbols is narrowed to those - the ones it
    has written about in the last month. `decisions` is why: the ranking is
    narrowed to what the broker offers before it runs, so crypto never reaches
    the journal however many weekend hours it trades, and judging a Sunday
    against a market this job cannot act on would report a correct silence as
    a dead cycle every single weekend.

    A failure here must not take the report down: an operator running this is
    usually running it because something is already wrong, and a health check
    that raises instead of printing is the least useful thing in the room.
    """
    try:
        from app.core.config import get_settings
        from app.db.models import Instrument
        from app.services import sessions as session_service
        from app.workers.watchlist import parse_watchlist

        symbols = {e.symbol for e in parse_watchlist(get_settings().watchlist)}
        if check.symbol_column is not None:
            # Table and column both come from the constant above, never from a
            # caller, so there is nothing here for a parameter to bind.
            written = {
                row[0]
                for row in session.execute(
                    text(
                        f"select distinct {check.symbol_column} "  # noqa: S608
                        f"from {check.table} "
                        "where created_at > now() - interval '30 days'"
                    )
                )
                if row[0]
            }
            # An empty answer means this job has written nothing for a month,
            # which is the failure being looked for - so it must not quietly
            # become "no market to check" and pass.
            symbols = written or symbols
        if not symbols:
            return []
        instruments = (
            session.query(Instrument).filter(Instrument.symbol.in_(symbols)).all()
        )
        return [session_service.build_calendar(session, i) for i in instruments]
    except Exception:  # noqa: BLE001 - a missing calendar is not a health failure
        return []


def gather(session: Session, *, watched: Any = WATCHED) -> list[Check]:
    """One aggregate per watched table.

    Count and max in the same pass. Two queries per table would let the row
    count and the timestamp come from different instants, which is a small
    lie that shows up exactly when the system is busy and somebody is
    reading this because it is busy.
    """
    checks: list[Check] = []
    for job, table, column, cadence, open_only, symbol_column in watched:
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
                open_only=open_only,
                symbol_column=symbol_column,
            )
        )
    return checks


def report(session: Session, *, now: datetime | None = None) -> tuple[bool, str]:
    """Every cycle, one line each. True when nothing is stale."""
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    checks = gather(session)

    # Only the checks that already failed on wall-clock time are worth a
    # calendar, and only the ones that go quiet on a shut market. On an open
    # market that set is empty and no calendar is built at all.
    suspect = [
        c
        for c in checks
        if c.open_only and c.newest is not None and (moment - c.newest) > c.limit
    ]
    open_ages: dict[str, timedelta] = {}
    for check in suspect:
        assert check.newest is not None
        open_ages[check.job] = open_time_since(
            _calendars(session, check), check.newest, moment, stop_after=check.limit
        )

    stale = [c for c in checks if c.stale(moment, open_age=open_ages.get(c.job))]

    lines = [f"cycles at {moment.isoformat(timespec='seconds')}"]
    lines.extend(c.line(moment, open_age=open_ages.get(c.job)) for c in checks)

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
