"""A report that cannot say a dead job is fine.

Twice this week a scheduled job was found to have been silently stopped for
weeks, both times by accident. So the tests that matter here are the ones
about calling something stale: an empty table, a table nobody has written to
since last month, a clock that disagrees. Getting a green line out of this
module should be hard.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.workers import health_report
from app.workers.health_report import Check

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def check(**over) -> Check:
    base = dict(
        job="collect",
        table="ingestion_runs",
        rows=100,
        newest=NOW - timedelta(minutes=5),
        cadence=timedelta(minutes=15),
    )
    base.update(over)
    return Check(**base)


class TestStalenessIsTheJobsOwnCadence:
    """Not a number anybody chose: a daily job that has not written in two
    days has missed one, and that is the first moment the evidence can tell
    late from stopped."""

    def test_a_recent_write_is_fresh(self):
        assert check().stale(NOW) is False

    def test_one_missed_run_is_not_yet_stale(self):
        """Late is not stopped. A job that runs at 03:00 must not go red at
        03:00 the next day because a clock is a minute out."""
        assert check(newest=NOW - timedelta(minutes=20)).stale(NOW) is False

    def test_two_missed_runs_is_stale(self):
        assert check(newest=NOW - timedelta(minutes=31)).stale(NOW) is True

    def test_a_daily_job_gets_two_days(self):
        daily = dict(job="episodes", cadence=timedelta(days=1))

        assert check(**daily).stale(NOW) is False
        assert (
            check(**daily, newest=NOW - timedelta(days=1, hours=12)).stale(NOW)
            is False
        )
        assert (
            check(**daily, newest=NOW - timedelta(days=2, hours=1)).stale(NOW)
            is True
        )


class TestAnEmptyTableIsNotAFreshOne:
    """The failure this exists to catch is a job that never ran, and a report
    that treats "no rows" as "nothing to complain about" would miss exactly
    that."""

    def test_never_written_is_stale(self):
        assert check(newest=None, rows=0).stale(NOW) is True

    def test_never_written_says_so_rather_than_printing_an_age(self):
        assert "never written" in check(newest=None, rows=0).line(NOW)

    def test_rows_without_a_timestamp_are_still_stale(self):
        """A table with a million rows and no recent one is a job that used
        to work."""
        assert check(newest=None, rows=1_000_000).stale(NOW) is True


class TestAClockProblemIsNotHidden:
    def test_a_row_stamped_in_the_future_reads_as_negative(self):
        line = check(newest=NOW + timedelta(hours=3)).line(NOW)

        assert "-3h ago" in line

    def test_it_is_not_reported_as_stale(self):
        """A clock skew is a different fault from a stopped job, and calling
        it staleness would send somebody to restart the wrong thing."""
        assert check(newest=NOW + timedelta(hours=3)).stale(NOW) is False


class TestTheAgeReadsAtAGlance:
    @pytest.mark.parametrize(
        ("span", "expected"),
        [
            (timedelta(seconds=9), "9s"),
            (timedelta(minutes=20), "20m"),
            (timedelta(hours=5), "5h"),
            (timedelta(days=3), "3d"),
        ],
    )
    def test_units_are_chosen_for_the_size(self, span, expected):
        assert health_report._ago(span) == expected


class TestEveryWatchedJobNamesRealEvidence:
    def test_each_entry_is_a_job_a_table_a_column_and_a_cadence(self):
        for entry in health_report.WATCHED:
            job, table, column, cadence, open_only, symbol_column, quorum = entry
            assert job and table and column
            assert cadence > timedelta(0)
            assert isinstance(open_only, bool)
            assert symbol_column is None or symbol_column
            assert quorum >= 1

    def test_no_two_jobs_read_the_same_evidence(self):
        """Two jobs reading one column means one of them is not really being
        checked, and the report would say both are fine when one had died.

        The table alone is not the evidence. Writing decisions and scoring
        them are different jobs that share `journal_entries` and fail
        separately - which is exactly how a resolver that had stopped for
        three days sat under a green line while the journal filled."""
        evidence = [
            (table, column) for _, table, column, _, _, _, _ in health_report.WATCHED
        ]

        assert len(evidence) == len(set(evidence))

    def test_scoring_the_journal_is_watched_as_well_as_filling_it(self):
        jobs = {job for job, *_ in health_report.WATCHED}

        assert {"decisions", "resolutions"} <= jobs

    def test_the_bar_driven_jobs_are_watched_at_the_bar(self):
        """Every frequent job here writes when a bar closes, not when the
        cycle runs: the cycle skips an entry whose next bar cannot have closed
        yet, and the journal is unique on (symbol, bar, arm). On a weekend the
        only open market is crypto on H1, so all four write once an hour and
        are meant to - judged against the cycle they went red every weekend."""
        by_job = {job: cadence for job, _, _, cadence, _, _, _ in health_report.WATCHED}

        for job in ("collect", "features", "bars", "decisions"):
            assert by_job[job] == timedelta(hours=1), job

    def test_two_hours_of_silence_on_an_open_market_is_still_caught(self):
        """The relaxation must not go so far that the check stops working.
        Whatever the cadence, `GRACE` misses are the alarm."""
        by_job = {job: cadence for job, _, _, cadence, _, _, _ in health_report.WATCHED}

        assert by_job["collect"] * health_report.GRACE <= timedelta(hours=2)


class TestTheReportRefusesToLookHealthyWhenItIsNot:
    class FakeSession:
        def __init__(self, rows):
            self._rows = rows
            self.seen: list[str] = []

        def execute(self, statement):
            self.seen.append(str(statement))
            return _One(self._rows.pop(0))

    def rows_for(self, newest):
        return [(10, newest) for _ in health_report.WATCHED]

    def test_all_fresh_reports_healthy(self):
        session = self.FakeSession(self.rows_for(NOW - timedelta(minutes=1)))

        healthy, text = health_report.report(session, now=NOW)

        assert healthy is True
        assert "all cycles fresh" in text

    def test_one_dead_job_fails_the_whole_report(self):
        rows = self.rows_for(NOW - timedelta(minutes=1))
        rows[-1] = (10, NOW - timedelta(days=30))
        session = self.FakeSession(rows)

        healthy, text = health_report.report(session, now=NOW)

        assert healthy is False
        assert "STALE" in text

    def test_the_geometry_and_risk_are_printed_beside_the_freshness(self):
        """"Everything is running" and "running the geometry you think it
        is" are different reassurances, and both get asked for at once."""
        session = self.FakeSession(self.rows_for(NOW - timedelta(minutes=1)))

        _, text = health_report.report(session, now=NOW)

        assert "geometry stop" in text
        assert "risk" in text


class TestFreshnessIsReadFromAWriteTime:
    """The bar's own timestamp is not evidence that a job ran.

    `features` and `bars` were read from `event_time`. The newest H1 bar's
    event_time is never fresher than the last hourly close, so against a
    fifteen-minute threshold both lines went red for three quarters of every
    hour while both jobs were running perfectly - and a check that is red
    most of the time is a check nobody reads.
    """

    def test_no_watched_column_is_an_event_time(self):
        columns = {job: column for job, _, column, _, _, _, _ in health_report.WATCHED}

        assert columns["features"] == "computed_at"
        assert columns["bars"] == "ingested_at"
        assert "event_time" not in set(columns.values())


class TestAShutMarketIsNotAStoppedJob:
    """A job that only has work while a market trades goes quiet at the
    weekend by design. The calendar is consulted only when wall-clock time
    has already failed, because open time can never exceed wall-clock time."""

    class AlwaysShut:
        def is_open(self, moment):
            return False

    class AlwaysOpen:
        def is_open(self, moment):
            return True

    def open_check(self, **over):
        base = dict(
            job="decisions",
            table="journal_entries",
            rows=100,
            newest=NOW - timedelta(hours=6),
            cadence=timedelta(minutes=15),
            open_only=True,
        )
        base.update(over)
        return Check(**base)

    def test_six_quiet_weekend_hours_are_not_stale(self):
        assert self.open_check().stale(NOW, open_age=timedelta(0)) is False

    def test_the_same_six_hours_on_an_open_market_are_stale(self):
        assert self.open_check().stale(NOW, open_age=timedelta(hours=6)) is True

    def test_a_job_that_runs_regardless_gets_no_such_excuse(self):
        """`equity` samples whether or not anything is trading, so a calendar
        must not be able to explain its silence away."""
        entry = self.open_check(job="equity", open_only=False)

        assert entry.stale(NOW, open_age=timedelta(0)) is True

    def test_the_line_says_how_much_of_the_age_was_open(self):
        line = self.open_check().line(NOW, open_age=timedelta(0))

        assert "6h ago" in line
        assert "0s of it open" in line

    def test_a_fresh_job_never_mentions_open_time(self):
        """On an open market the two numbers are the same, and a column that
        repeats itself is a column nobody reads."""
        line = self.open_check(newest=NOW - timedelta(minutes=5)).line(
            NOW, open_age=timedelta(minutes=5)
        )

        assert "of it open" not in line


class TestAJobIsAgedAgainstTheMarketsItActsOn:
    """Crypto trades every hour of the weekend and never reaches the journal:
    the ranking is narrowed to what the broker offers before it runs. Aging
    `decisions` against the whole watchlist would therefore report a correct
    Sunday silence as a dead cycle, every weekend."""

    def test_decisions_are_narrowed_by_the_symbols_they_wrote(self):
        by_job = {
            job: symbol_column
            for job, _, _, _, _, symbol_column, _ in health_report.WATCHED
        }

        assert by_job["decisions"] == "symbol"

    def test_the_sweeping_jobs_are_not_narrowed(self):
        """`collect`, `features` and `bars` cover the whole watchlist, so one
        open market anywhere is work they owed."""
        by_job = {
            job: symbol_column
            for job, _, _, _, _, symbol_column, _ in health_report.WATCHED
        }

        assert by_job["collect"] is None
        assert by_job["features"] is None
        assert by_job["bars"] is None


class TestTheCalendarLookupActuallyResolves:
    """The lookup is wrapped in a catch-all, because a health check that
    raises instead of printing is the least useful thing in the room - but
    that also means a wrong import reads exactly like a shut market.

    It did: the first deployment of this returned no calendars at all and
    every market-hours line went red on a Sunday morning for a second wrong
    reason. So the lookup is exercised against a real session here rather than
    trusted to a name."""

    def test_a_watched_instrument_yields_a_calendar(self, session):
        from app.core.enums import AssetClass
        from app.models.instruments import Instrument

        session.add(
            Instrument(symbol="EURUSD", name="Euro", asset_class=AssetClass.FOREX)
        )
        session.flush()
        entry = Check(
            job="collect",
            table="ingestion_runs",
            rows=1,
            newest=NOW,
            cadence=timedelta(minutes=15),
            open_only=True,
        )

        calendars = health_report._calendars(session, entry)

        assert calendars, "the watchlist's instruments must produce calendars"
        assert all(hasattr(c, "is_open") for c in calendars)


class TestOpenTimeIsCountedNotGuessed:
    def test_a_shut_market_contributes_nothing(self):
        span = health_report.open_time_since(
            [TestAShutMarketIsNotAStoppedJob.AlwaysShut()],
            NOW - timedelta(hours=6),
            NOW,
            stop_after=timedelta(minutes=30),
        )

        assert span == timedelta(0)

    def test_one_open_market_is_enough(self):
        """The union, not the average: these jobs sweep the whole watchlist,
        so one open market gives them work to do."""
        span = health_report.open_time_since(
            [
                TestAShutMarketIsNotAStoppedJob.AlwaysShut(),
                TestAShutMarketIsNotAStoppedJob.AlwaysOpen(),
            ],
            NOW - timedelta(hours=6),
            NOW,
            stop_after=timedelta(minutes=30),
        )

        assert span > timedelta(minutes=30)

    def test_no_calendar_grants_no_excuse(self):
        """A caller with no calendar to offer is exactly where the report was
        before there was one."""
        span = health_report.open_time_since(
            [], NOW - timedelta(hours=6), NOW, stop_after=timedelta(minutes=30)
        )

        assert span == timedelta(hours=6)

    def test_the_walk_is_bounded_by_the_longest_plausible_closure(self):
        """No exchange shuts for ten days, so past that the feed is the
        explanation - and the bound stops a dead job walking a year of
        fifteen-minute slots."""
        span = health_report.open_time_since(
            [TestAShutMarketIsNotAStoppedJob.AlwaysOpen()],
            NOW - timedelta(days=365),
            NOW,
            stop_after=timedelta(days=400),
        )

        assert span > timedelta(days=354)


class _One:
    def __init__(self, row):
        self._row = row

    def one(self):
        return self._row


class TestACrossSectionNeedsMoreThanOneOpenMarket:
    """`decisions` and `resolutions` come from a ranking, and a ranking of
    four is not a ranking. On a Sunday the only open markets are the four
    crypto series - which do reach the journal, contrary to what the first
    version of this assumed - so a quorum of one called a correctly silent
    weekend a dead cycle, every week."""

    class Open:
        def is_open(self, moment):
            return True

    def test_the_ranking_jobs_need_the_cross_section_minimum(self):
        by_job = {job: quorum for job, _, _, _, _, _, quorum in health_report.WATCHED}

        assert by_job["decisions"] == health_report.MIN_TO_RANK
        assert by_job["resolutions"] == health_report.MIN_TO_RANK

    def test_the_sweeping_jobs_need_only_one(self):
        by_job = {job: quorum for job, _, _, _, _, _, quorum in health_report.WATCHED}

        for job in ("collect", "features", "bars"):
            assert by_job[job] == 1, job

    def test_four_open_markets_do_not_meet_a_quorum_of_twenty(self):
        span = health_report.open_time_since(
            [self.Open() for _ in range(4)],
            NOW - timedelta(hours=6),
            NOW,
            stop_after=timedelta(hours=2),
            quorum=20,
        )

        assert span == timedelta(0)

    def test_twenty_open_markets_do(self):
        span = health_report.open_time_since(
            [self.Open() for _ in range(20)],
            NOW - timedelta(hours=6),
            NOW,
            stop_after=timedelta(hours=2),
            quorum=20,
        )

        assert span > timedelta(hours=2)

    def test_the_minimum_is_the_ranking_s_own(self):
        """Taken from the cross-section rather than chosen here, or the two
        drift and this check starts excusing a real outage."""
        from app.brain.crosssection import MIN_CROSS_SECTION

        assert health_report.MIN_TO_RANK == MIN_CROSS_SECTION
