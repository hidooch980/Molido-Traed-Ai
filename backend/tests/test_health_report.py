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
            job, table, column, cadence = entry
            assert job and table and column
            assert cadence > timedelta(0)

    def test_no_table_is_watched_twice_under_two_names(self):
        """Two jobs sharing one table means one of them is not really being
        checked, and the report would say both are fine when one had died."""
        tables = [table for _, table, _, _ in health_report.WATCHED]

        assert len(tables) == len(set(tables))

    def test_the_frequent_jobs_are_watched_at_the_cycle_cadence(self):
        by_job = {job: cadence for job, _, _, cadence in health_report.WATCHED}

        assert by_job["collect"] <= timedelta(minutes=15)
        assert by_job["decisions"] <= timedelta(minutes=15)


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


class _One:
    def __init__(self, row):
        self._row = row

    def one(self):
        return self._row
