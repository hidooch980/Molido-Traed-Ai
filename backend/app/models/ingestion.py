"""Ingestion runs, resumable checkpoints, and data-quality findings."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import DataQualityIssue, IngestionStatus, Severity, Timeframe
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import JSONType, TimestampType, UUIDType


class IngestionRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One attempt to pull a range of data from one provider.

    `idempotency_key` makes a repeated request for the same window a no-op
    rather than a duplicate import.
    """

    __tablename__ = "ingestion_runs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_ingestion_runs_idempotency"),
        Index("ix_ingestion_runs_target", "instrument_id", "timeframe", "status"),
    )

    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("providers.id", ondelete="CASCADE"), index=True
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("instruments.id", ondelete="CASCADE"), index=True
    )
    timeframe: Mapped[Timeframe] = mapped_column(String(8), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)

    requested_start: Mapped[datetime] = mapped_column(TimestampType, nullable=False)
    requested_end: Mapped[datetime] = mapped_column(TimestampType, nullable=False)

    status: Mapped[IngestionStatus] = mapped_column(
        String(16), default=IngestionStatus.PENDING, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)

    rows_fetched: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    rows_written: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    rows_rejected: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    rows_duplicate: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class IngestionCheckpoint(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Resume marker per (provider, instrument, timeframe).

    A crashed run resumes from `last_event_time` instead of re-downloading the
    whole history.
    """

    __tablename__ = "ingestion_checkpoints"
    __table_args__ = (
        UniqueConstraint(
            "provider_id", "instrument_id", "timeframe", name="uq_ingestion_checkpoint_target"
        ),
    )

    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("providers.id", ondelete="CASCADE")
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("instruments.id", ondelete="CASCADE")
    )
    timeframe: Mapped[Timeframe] = mapped_column(String(8), nullable=False)

    last_event_time: Mapped[datetime | None] = mapped_column(
        TimestampType, nullable=True
    )
    last_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("ingestion_runs.id", ondelete="SET NULL"), nullable=True
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        TimestampType, nullable=True
    )
    cursor: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)


class DataQualityFinding(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One detected defect in a dataset (spec §5).

    Findings are facts about data, not opinions: each records what was expected,
    what was observed, and the window it applies to, so an operator can verify
    it independently.
    """

    __tablename__ = "data_quality_findings"
    __table_args__ = (
        Index("ix_dq_lookup", "instrument_id", "timeframe", "issue", "detected_at"),
        UniqueConstraint(
            "instrument_id",
            "provider_id",
            "timeframe",
            "issue",
            "window_start",
            name="uq_dq_finding_window",
        ),
    )

    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("instruments.id", ondelete="CASCADE"), index=True
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("providers.id", ondelete="CASCADE"), index=True
    )
    timeframe: Mapped[Timeframe] = mapped_column(String(8), nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("ingestion_runs.id", ondelete="SET NULL"), nullable=True
    )

    issue: Mapped[DataQualityIssue] = mapped_column(String(40), nullable=False)
    severity: Mapped[Severity] = mapped_column(String(16), default=Severity.WARNING, nullable=False)
    window_start: Mapped[datetime] = mapped_column(TimestampType, nullable=False)
    window_end: Mapped[datetime] = mapped_column(TimestampType, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(TimestampType, nullable=False)

    affected_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expected: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)

    resolved_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)


class DatasetQuality(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Rolled-up quality score per (instrument, provider, timeframe).

    `is_training_eligible` is the gate the spec demands: data without
    trustworthy provenance or score must not enter production training sets.
    """

    __tablename__ = "dataset_quality"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id", "provider_id", "timeframe", name="uq_dataset_quality_target"
        ),
    )

    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("instruments.id", ondelete="CASCADE")
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("providers.id", ondelete="CASCADE")
    )
    timeframe: Mapped[Timeframe] = mapped_column(String(8), nullable=False)

    score: Mapped[float] = mapped_column(Numeric(4, 3), default=1.0, nullable=False)
    coverage_start: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    coverage_end: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    expected_bars: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    actual_bars: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    open_findings: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_training_eligible: Mapped[bool] = mapped_column(default=False, nullable=False)
    evaluated_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
