"""Host evidence: stale is unknown, malformed is unknown, and only a real
drill counts as a restore."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from app.ops import evidence

NOW = datetime(2026, 9, 2, 20, 0, tzinfo=UTC)


def write(tmp_path, name, **body):
    body.setdefault("written_at", NOW.isoformat())
    (tmp_path / f"{name}.json").write_text(json.dumps(body), encoding="utf-8")


class TestANoteMustBeRecentAndWellFormed:
    def test_missing_is_none(self, tmp_path):
        assert evidence.read("log-rotation", directory=tmp_path, now=NOW) is None

    def test_malformed_is_none(self, tmp_path):
        (tmp_path / "log-rotation.json").write_text("{not json", encoding="utf-8")
        assert evidence.read("log-rotation", directory=tmp_path, now=NOW) is None

    def test_stale_is_none(self, tmp_path):
        write(tmp_path, "log-rotation", written_at=(NOW - timedelta(hours=7)).isoformat())
        assert evidence.read("log-rotation", directory=tmp_path, now=NOW) is None

    def test_naive_timestamp_is_none(self, tmp_path):
        """Somebody's local time is how a six-hour age reads as fresh."""
        write(tmp_path, "log-rotation", written_at="2026-09-02T19:59:00")
        assert evidence.read("log-rotation", directory=tmp_path, now=NOW) is None

    def test_future_is_none(self, tmp_path):
        write(tmp_path, "log-rotation", written_at=(NOW + timedelta(hours=2)).isoformat())
        assert evidence.read("log-rotation", directory=tmp_path, now=NOW) is None

    def test_fresh_reads(self, tmp_path):
        write(tmp_path, "log-rotation", written_at=(NOW - timedelta(minutes=10)).isoformat())
        note = evidence.read("log-rotation", directory=tmp_path, now=NOW)
        assert note is not None and note.age == timedelta(minutes=10)


class TestLogRotation:
    def test_every_container_bounded_is_true(self, tmp_path):
        write(tmp_path, "log-rotation", containers=[{"name": "a", "bounded": True}, {"name": "b", "bounded": True}])
        assert evidence.log_rotation_configured(directory=tmp_path, now=NOW) is True

    def test_one_unbounded_container_is_false(self, tmp_path):
        write(tmp_path, "log-rotation", containers=[{"name": "a", "bounded": True}, {"name": "b", "bounded": False}])
        assert evidence.log_rotation_configured(directory=tmp_path, now=NOW) is False

    def test_no_containers_is_unknown(self, tmp_path):
        write(tmp_path, "log-rotation", containers=[])
        assert evidence.log_rotation_configured(directory=tmp_path, now=NOW) is None


class TestRestoreDrill:
    def test_a_verified_restore_returns_when_it_happened(self, tmp_path):
        when = NOW - timedelta(days=2)
        write(tmp_path, "restore-drill", written_at=when.isoformat(), performed_at=when.isoformat(), succeeded=True, rows_verified=1_649_553)
        assert evidence.last_successful_restore(directory=tmp_path, now=NOW) == when

    def test_a_failed_drill_is_none(self, tmp_path):
        write(tmp_path, "restore-drill", performed_at=NOW.isoformat(), succeeded=False, rows_verified=10)
        assert evidence.last_successful_restore(directory=tmp_path, now=NOW) is None

    def test_a_restore_that_verified_nothing_is_none(self, tmp_path):
        """A database nobody queried proves a file decompresses."""
        write(tmp_path, "restore-drill", performed_at=NOW.isoformat(), succeeded=True, rows_verified=0)
        assert evidence.last_successful_restore(directory=tmp_path, now=NOW) is None

    def test_a_drill_older_than_a_month_is_none(self, tmp_path):
        when = NOW - timedelta(days=31)
        write(tmp_path, "restore-drill", written_at=when.isoformat(), performed_at=when.isoformat(), succeeded=True, rows_verified=5)
        assert evidence.last_successful_restore(directory=tmp_path, now=NOW) is None


class TestSecrets:
    def test_only_secret_severity_fails(self, tmp_path):
        write(tmp_path, "secrets-scan", complete=True, findings=[
            {"path": "frontend/.env.local", "category": "env-file", "severity": "shape"},
            {"path": "infra/.env.prod", "category": "credential-assignment", "severity": "secret"},
        ])
        assert evidence.secrets_in_repository(directory=tmp_path, now=NOW) == ["infra/.env.prod"]

    def test_shape_only_is_a_pass(self, tmp_path):
        write(tmp_path, "secrets-scan", complete=True, findings=[
            {"path": "frontend/.env.local", "category": "env-file", "severity": "shape"},
        ])
        assert evidence.secrets_in_repository(directory=tmp_path, now=NOW) == []

    def test_an_incomplete_scan_is_unknown(self, tmp_path):
        write(tmp_path, "secrets-scan", complete=False, findings=[])
        assert evidence.secrets_in_repository(directory=tmp_path, now=NOW) is None
