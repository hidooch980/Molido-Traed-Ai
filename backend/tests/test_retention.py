"""Retention tests.

A retention job is trusted precisely once and then runs unattended for years,
so these are mostly about what it must refuse to delete — and about the dry run
telling the truth, because the dry run is the only thing anybody checks before
trusting it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.core.enums import AuditEventType, DataQualityIssue, Severity, Timeframe
from app.models.audit import AuditEvent
from app.models.ingestion import DataQualityFinding, IngestionRun
from app.services import retention

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def add_run(session, *, days_old: int, finished: bool = True, instrument_id=None, provider_id=None):
    started = NOW - timedelta(days=days_old)
    row = IngestionRun(
        instrument_id=instrument_id,
        provider_id=provider_id,
        timeframe=Timeframe.H1,
        requested_start=started,
        requested_end=started + timedelta(hours=1),
        started_at=started,
        finished_at=started + timedelta(seconds=5) if finished else None,
        status="succeeded" if finished else "running",
        idempotency_key=str(uuid.uuid4()),
    )
    session.add(row)
    session.flush()
    return row


def add_audit(session, *, days_old: int, severity=Severity.INFO):
    row = AuditEvent(
        event_type=AuditEventType.INGESTION_COMPLETED,
        severity=severity,
        summary="cycle complete",
        occurred_at=NOW - timedelta(days=days_old),
        service="collector",
    )
    session.add(row)
    session.flush()
    return row


class TestTheDryRunTellsTheTruth:
    def test_a_dry_run_deletes_nothing(self, session, instrument, provider):
        for age in (5, 60, 120):
            add_run(session, days_old=age, instrument_id=instrument.id, provider_id=provider.id)

        report = retention.prune(session, now=NOW, dry_run=True)

        assert report.total_deleted == 0
        assert session.execute(text("SELECT count(*) FROM ingestion_runs")).scalar_one() == 3

    def test_the_dry_run_counts_what_the_real_run_removes(self, session, instrument, provider):
        """A dry run that disagrees with the real run cannot be checked first."""
        for age in (5, 60, 120):
            add_run(session, days_old=age, instrument_id=instrument.id, provider_id=provider.id)

        rehearsal = retention.prune(session, now=NOW, dry_run=True)
        real = retention.prune(session, now=NOW, dry_run=False)

        rehearsed = next(t for t in rehearsal.tables if t.table == "ingestion_runs")
        removed = next(t for t in real.tables if t.table == "ingestion_runs")

        assert rehearsed.eligible - rehearsed.protected == removed.deleted

    def test_the_policies_are_published_with_their_reasons(self, session):
        payload = retention.prune(session, now=NOW).as_dict()

        assert len(payload["policies"]) == len(retention.POLICIES)
        assert all(p["reason"] for p in payload["policies"])


class TestWhatItRefusesToDelete:
    def test_an_unfinished_run_survives_however_old(self, session, instrument, provider):
        """It is a live checkpoint, not history."""
        add_run(
            session, days_old=400, finished=False,
            instrument_id=instrument.id, provider_id=provider.id,
        )

        retention.prune(session, now=NOW, dry_run=False)

        assert session.execute(text("SELECT count(*) FROM ingestion_runs")).scalar_one() == 1

    def test_an_unresolved_finding_survives_however_old(self, session, instrument, provider):
        """An open defect is live at any age, and the record is what makes
        somebody look at it."""
        session.add(
            DataQualityFinding(
                instrument_id=instrument.id,
                provider_id=provider.id,
                timeframe=Timeframe.H1,
                issue=DataQualityIssue.MISSING_CANDLE,
                severity=Severity.WARNING,
                window_start=NOW - timedelta(days=500),
                window_end=NOW - timedelta(days=499),
                detected_at=NOW - timedelta(days=500),
                affected_rows=3,
            )
        )
        session.flush()

        retention.prune(session, now=NOW, dry_run=False)

        remaining = session.execute(
            text("SELECT count(*) FROM data_quality_findings")
        ).scalar_one()
        assert remaining == 1

    def test_a_critical_audit_event_outlives_the_window(self, session):
        add_audit(session, days_old=800, severity=Severity.CRITICAL)
        add_audit(session, days_old=800, severity=Severity.INFO)

        retention.prune(session, now=NOW, dry_run=False)

        rows = session.execute(text("SELECT severity FROM audit_events")).scalars().all()
        assert [str(r) for r in rows] == ["critical"]

    def test_protected_rows_are_counted_not_hidden(self, session, instrument, provider):
        add_run(
            session, days_old=400, finished=False,
            instrument_id=instrument.id, provider_id=provider.id,
        )

        report = retention.prune(session, now=NOW, dry_run=True)
        runs = next(t for t in report.tables if t.table == "ingestion_runs")

        assert runs.eligible == 1
        assert runs.protected == 1


class TestWhatItDeletes:
    def test_a_finished_run_past_the_window_goes(self, session, instrument, provider):
        add_run(session, days_old=120, instrument_id=instrument.id, provider_id=provider.id)

        report = retention.prune(session, now=NOW, dry_run=False)

        assert report.total_deleted == 1
        assert session.execute(text("SELECT count(*) FROM ingestion_runs")).scalar_one() == 0

    def test_a_recent_run_stays(self, session, instrument, provider):
        add_run(session, days_old=3, instrument_id=instrument.id, provider_id=provider.id)

        retention.prune(session, now=NOW, dry_run=False)

        assert session.execute(text("SELECT count(*) FROM ingestion_runs")).scalar_one() == 1

    def test_each_table_keeps_its_own_window(self, session):
        """A single window would either lose the audit trail or keep every run."""
        add_audit(session, days_old=100)  # inside the 365-day audit window

        report = retention.prune(session, now=NOW, dry_run=False)
        audit = next(t for t in report.tables if t.table == "audit_events")

        assert audit.deleted == 0
        assert session.execute(text("SELECT count(*) FROM audit_events")).scalar_one() == 1

    def test_an_unreadable_table_is_reported_not_skipped_silently(self, session):
        """A table nobody prunes is what fills a disk quietly."""
        bogus = (
            retention.Policy(
                table="table_that_does_not_exist",
                timestamp_column="created_at",
                keep=timedelta(days=1),
                reason="test",
            ),
        )

        report = retention.prune(session, now=NOW, dry_run=False, policies=bogus)

        assert report.errors
        assert "table_that_does_not_exist" in report.errors[0]


class TestReporting:
    def test_row_counts_are_available_for_the_health_view(self, session, instrument, provider):
        add_run(session, days_old=1, instrument_id=instrument.id, provider_id=provider.id)

        counts = retention.operational_row_counts(session)

        assert counts["ingestion_runs"] == 1
        assert "audit_events" in counts

    def test_the_oldest_row_is_reportable(self, session):
        add_audit(session, days_old=10)

        policy = next(p for p in retention.POLICIES if p.table == "audit_events")
        oldest = retention.oldest_row(session, policy)

        assert oldest is not None
