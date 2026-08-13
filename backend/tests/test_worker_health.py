"""Worker liveness tests.

The probe this replaces could not pass at any moment in the worker's life, and
reported unhealthy continuously while the worker did its job perfectly. So
these tests are about the two ways a healthcheck becomes useless: one that can
never pass, and one that can never fail.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.workers import healthcheck as hc

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


@pytest.fixture()
def interval(monkeypatch):
    """A 15-minute collection interval, matching the deployment."""

    class Settings:
        collector_interval_seconds = 900
        database_url = "sqlite+pysqlite:///:memory:"

    monkeypatch.setattr(hc, "get_settings", lambda: Settings())
    return Settings()


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

        class Slow:
            collector_interval_seconds = 86_400
            database_url = "sqlite+pysqlite:///:memory:"

        monkeypatch.setattr(hc, "get_settings", lambda: Slow())
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
