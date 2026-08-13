"""Retention for the operational tables (spec §68).

The market data looks after itself: TimescaleDB compresses `ohlcv` and
`feature_values` after 180 days and drops `ticks` after 400, so 5,400 bars a
day costs well under a gigabyte a year.

The operational tables are the ones that grow without a ceiling, and they grow
faster than the data they describe. Measured on the live server: `ingestion_runs`
gains about 5,300 rows a day — one per instrument per cycle — which is more rows
per day than the market produces bars. Left alone it reaches a gigabyte a year
on a 23 GB volume, and it fills the disk describing work rather than doing it.

Deleting operational history is a real loss, so every window here is justified
rather than picked, and each policy names rows it must never touch:

**A finding nobody resolved is not old news.** An open data-quality finding is
a live defect whatever its age, and the record of it is the only thing that
will make somebody look. Unresolved findings are protected regardless of the
window.

**A run that has not finished is not history.** Deleting a row that ingestion is
still using as its checkpoint would make the resume logic start from nothing.

**A critical audit event is kept.** The audit trail exists for the moments
somebody needs to reconstruct what the system did before it went wrong, and
those are exactly the events worth keeping past the ordinary window.

`prune` is dry-run by default. Every destructive default in this codebase
refuses, and a retention job that deletes on first call is a retention job that
deletes during the first experiment with it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.ingestion import IngestionRun


@dataclass(frozen=True)
class Policy:
    """One table's window, and what it refuses to delete inside it."""

    table: str
    timestamp_column: str
    keep: timedelta
    reason: str
    # SQL predicate for rows this policy must never remove, whatever their age.
    protect: str | None = None
    protect_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "keep_days": self.keep.days,
            "reason": self.reason,
            "protected": self.protect,
            "protect_reason": self.protect_reason,
        }


POLICIES: tuple[Policy, ...] = (
    Policy(
        table="ingestion_runs",
        timestamp_column="started_at",
        keep=timedelta(days=30),
        reason=(
            "a run older than a month is no longer diagnostic — the provider, the "
            "schedule and the symbol list have all moved since"
        ),
        protect="finished_at IS NULL",
        protect_reason="an unfinished run is a live checkpoint, not history",
    ),
    Policy(
        table="data_quality_findings",
        timestamp_column="detected_at",
        keep=timedelta(days=90),
        reason="a resolved finding is kept a quarter so a recurrence is visible as one",
        protect="resolved_at IS NULL",
        protect_reason="an unresolved finding is a live defect at any age",
    ),
    Policy(
        table="audit_events",
        timestamp_column="occurred_at",
        keep=timedelta(days=365),
        reason=(
            "the audit trail answers 'what did it do before it went wrong', which is "
            "asked long after the fact"
        ),
        protect="severity = 'critical'",
        protect_reason="the events most worth reconstructing are the ones kept longest",
    ),
)


@dataclass
class TableResult:
    table: str
    eligible: int
    protected: int
    deleted: int
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "eligible": self.eligible,
            "protected": self.protected,
            "deleted": self.deleted,
            "reason": self.reason,
        }


@dataclass
class PruneReport:
    dry_run: bool
    ran_at: datetime
    tables: list[TableResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def total_deleted(self) -> int:
        return sum(t.deleted for t in self.tables)

    def as_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "ran_at": self.ran_at.isoformat(),
            "total_deleted": self.total_deleted,
            "tables": [t.as_dict() for t in self.tables],
            "errors": self.errors,
            "policies": [p.as_dict() for p in POLICIES],
        }


def prune(
    session: Session,
    *,
    now: datetime | None = None,
    dry_run: bool = True,
    policies: tuple[Policy, ...] = POLICIES,
) -> PruneReport:
    """Count what each policy would remove, and remove it only when asked.

    The count is taken before the delete and reported either way, so a dry run
    and a real run produce the same numbers for the same input. A retention job
    whose dry run says something different from its real run is a job nobody
    can check before trusting.
    """
    moment = now or datetime.now(UTC)
    report = PruneReport(dry_run=dry_run, ran_at=moment)

    for policy in policies:
        cutoff = moment - policy.keep
        older = f"{policy.timestamp_column} < :cutoff"
        try:
            eligible = session.execute(
                text(f"SELECT count(*) FROM {policy.table} WHERE {older}"),  # noqa: S608
                {"cutoff": cutoff},
            ).scalar_one()

            protected = 0
            if policy.protect:
                protected = session.execute(
                    text(
                        f"SELECT count(*) FROM {policy.table} "  # noqa: S608
                        f"WHERE {older} AND ({policy.protect})"
                    ),
                    {"cutoff": cutoff},
                ).scalar_one()

            removable = eligible - protected
            deleted = 0
            if not dry_run and removable > 0:
                condition = older
                if policy.protect:
                    condition = f"{older} AND NOT ({policy.protect})"
                result = session.execute(
                    text(f"DELETE FROM {policy.table} WHERE {condition}"),  # noqa: S608
                    {"cutoff": cutoff},
                )
                # A driver that does not report a row count is not evidence
                # that nothing was deleted, so the counted figure stands in.
                deleted = getattr(result, "rowcount", None) or removable
                session.flush()

            report.tables.append(
                TableResult(
                    table=policy.table,
                    eligible=eligible,
                    protected=protected,
                    deleted=deleted,
                    reason=policy.reason,
                )
            )
        except Exception as exc:  # noqa: BLE001 - reported, never silently skipped
            # A table this job cannot read is a table nobody is pruning, which is
            # exactly the situation that fills a disk quietly.
            report.errors.append(f"{policy.table}: {exc}")

    return report


def operational_row_counts(session: Session) -> dict[str, int]:
    """Current size of each managed table, for the health endpoint."""
    counts: dict[str, int] = {}
    for policy in POLICIES:
        try:
            counts[policy.table] = session.execute(
                text(f"SELECT count(*) FROM {policy.table}")  # noqa: S608
            ).scalar_one()
        except Exception:  # noqa: BLE001, S110 - a missing table is reported as absent
            counts[policy.table] = -1
    return counts


def oldest_row(session: Session, policy: Policy) -> datetime | None:
    """When the oldest surviving row in this table is from."""
    model = {"ingestion_runs": IngestionRun, "audit_events": AuditEvent}.get(policy.table)
    if model is None:
        return None
    column = getattr(model, policy.timestamp_column, None)
    if column is None:
        return None
    return session.execute(select(func.min(column))).scalar_one_or_none()


__all__ = [
    "POLICIES",
    "Policy",
    "PruneReport",
    "TableResult",
    "delete",
    "operational_row_counts",
    "oldest_row",
    "prune",
]
