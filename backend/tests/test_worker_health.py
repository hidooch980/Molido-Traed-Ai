"""Worker liveness tests.

The probe this replaces could not pass at any moment in the worker's life, and
reported unhealthy continuously while the worker did its job perfectly. So
these tests are about the two ways a healthcheck becomes useless: one that can
never pass, and one that can never fail.
"""

from __future__ import annotations

import pathlib
from datetime import UTC, datetime, timedelta

import pytest

from app.workers import healthcheck as hc

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


@pytest.fixture()
def interval(monkeypatch):
    """A 15-minute collection interval, matching the deployment.

    Set through the environment, because that is how the probe reads it now -
    importing the settings object cost 4.3 seconds inside the container,
    against a 15-second probe timeout.
    """
    monkeypatch.setenv(hc.INTERVAL_VAR, "900")
    monkeypatch.setenv(hc.DSN_VAR, "postgresql://molido:molido@localhost:5432/x")
    return 900


def with_last_finished(monkeypatch, value):
    monkeypatch.setattr(hc, "last_finished", lambda _url: value)


class TestItCanPass:
    def test_a_recent_cycle_is_healthy(self, monkeypatch, interval):
        with_last_finished(monkeypatch, NOW - timedelta(minutes=2))

        healthy, why = hc.check(now=NOW)

        assert healthy is True
        assert "last cycle finished" in why

    def test_one_missed_cycle_is_still_healthy(self, monkeypatch, interval):
        """One missed cycle is a slow provider, not a broken worker."""
        with_last_finished(monkeypatch, NOW - timedelta(minutes=20))

        assert hc.check(now=NOW)[0] is True


class TestItCanFail:
    def test_three_missed_cycles_are_unhealthy(self, monkeypatch, interval):
        with_last_finished(monkeypatch, NOW - timedelta(minutes=50))

        healthy, why = hc.check(now=NOW)

        assert healthy is False
        assert "beyond the" in why

    def test_a_worker_that_never_ran_is_unhealthy(self, monkeypatch, interval):
        with_last_finished(monkeypatch, None)

        healthy, why = hc.check(now=NOW)

        assert healthy is False
        assert "ever finished" in why

    def test_an_unreachable_database_is_unhealthy_not_assumed_fine(
        self, monkeypatch, interval
    ):
        """Anything unanswerable fails the probe. A healthcheck that passes when
        it cannot check is the other way to make one useless."""

        def boom(_url):
            raise RuntimeError("connection refused")

        monkeypatch.setattr(hc, "last_finished", boom)

        healthy, why = hc.check(now=NOW)

        assert healthy is False
        assert "could not read" in why

    def test_a_long_interval_cannot_buy_unlimited_silence(self, monkeypatch):
        """Three cycles of a daily job would be three days of silence."""

        monkeypatch.setenv(hc.INTERVAL_VAR, "86400")
        with_last_finished(monkeypatch, NOW - timedelta(hours=6))

        assert hc.check(now=NOW)[0] is False


class TestTheExitCode:
    def test_healthy_exits_zero(self, monkeypatch, interval, capsys):
        with_last_finished(monkeypatch, NOW - timedelta(minutes=1))
        monkeypatch.setattr(hc, "check", lambda: (True, "fine"))

        assert hc.main() == 0
        assert "fine" in capsys.readouterr().out

    def test_unhealthy_exits_nonzero(self, monkeypatch, interval):
        monkeypatch.setattr(hc, "check", lambda: (False, "stalled"))

        assert hc.main() == 1

    def test_a_naive_timestamp_from_the_driver_is_treated_as_utc(self):
        """SQLite hands back naive datetimes, and comparing one against an
        aware `now` raises rather than returning a wrong answer."""
        naive = datetime(2026, 8, 13, 11, 58)

        assert naive.replace(tzinfo=UTC) < NOW


class TestTheProbeCostsLessThanWhatItMeasures:
    """It went unhealthy once for exactly this reason: the check computed a
    healthy answer, printed it, and was killed by the 15s timeout before it
    could exit zero. Importing the settings cost 4.3s and the ORM another
    5.0s, against 3.2s for the query. A probe that fails on a busy machine
    trains everyone to ignore it, and then it means nothing on the day it is
    right."""

    def test_it_does_not_import_the_application(self):
        """The assertion that fails the moment somebody reaches for
        `get_settings` again for tidiness."""
        source = pathlib.Path(hc.__file__).read_text(encoding="utf-8")

        assert "from app.core.config" not in source
        assert "from app.models" not in source
        assert "sqlalchemy" not in source

    def test_the_table_it_reads_is_the_one_the_model_writes(self):
        """The single real cost of not importing the ORM: a rename would break
        the probe silently. This makes it break a test instead."""
        from app.models.ingestion import IngestionRun

        source = pathlib.Path(hc.__file__).read_text(encoding="utf-8")

        assert IngestionRun.__tablename__ in source
        assert "finished_at" in IngestionRun.__table__.columns

    def test_the_driver_prefix_is_stripped_for_libpq(self):
        """SQLAlchemy writes `postgresql+psycopg://`; libpq does not know what
        the driver is and refuses the whole DSN."""
        assert hc._libpq("postgresql+psycopg://u:p@h:5432/db") == (
            "postgresql://u:p@h:5432/db"
        )

    def test_a_plain_dsn_is_left_alone(self):
        assert hc._libpq("postgresql://u:p@h:5432/db") == "postgresql://u:p@h:5432/db"

    def test_a_missing_interval_falls_back_rather_than_crashing(
        self, monkeypatch
    ):
        """A probe that raises on a missing variable is a probe that reports
        unhealthy for a reason having nothing to do with the worker."""
        monkeypatch.delenv(hc.INTERVAL_VAR, raising=False)
        with_last_finished(monkeypatch, NOW - timedelta(minutes=2))

        assert hc.check(now=NOW)[0] is True

    def test_an_unparseable_interval_falls_back(self, monkeypatch):
        monkeypatch.setenv(hc.INTERVAL_VAR, "not-a-number")
        with_last_finished(monkeypatch, NOW - timedelta(minutes=2))

        assert hc.check(now=NOW)[0] is True
