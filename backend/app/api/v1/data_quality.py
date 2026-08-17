"""Data-quality reporting."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.core.enums import DataQualityIssue, Permission, Severity, Timeframe
from app.db.session import get_db
from app.models.ingestion import DataQualityFinding, DatasetQuality
from app.schemas.market import DataQualityResponse, DatasetQualityOut, FindingOut
from app.services.instruments import get_instrument

router = APIRouter(prefix="/data-quality", tags=["data-quality"])

READ = Depends(require(Permission.READ))


@router.get("/{instrument_id}", response_model=DataQualityResponse)
def read_data_quality(
    instrument_id: uuid.UUID,
    timeframe: Timeframe | None = None,
    issue: DataQualityIssue | None = None,
    severity: Severity | None = None,
    include_resolved: bool = False,
    limit: int = Query(default=200, ge=1, le=1000),
    session: Session = Depends(get_db),
    _: Principal = READ,
) -> DataQualityResponse:
    instrument = get_instrument(session, instrument_id)

    datasets_q = select(DatasetQuality).where(DatasetQuality.instrument_id == instrument_id)
    findings_q = select(DataQualityFinding).where(
        DataQualityFinding.instrument_id == instrument_id
    )
    if timeframe is not None:
        datasets_q = datasets_q.where(DatasetQuality.timeframe == timeframe)
        findings_q = findings_q.where(DataQualityFinding.timeframe == timeframe)
    if issue is not None:
        findings_q = findings_q.where(DataQualityFinding.issue == issue)
    if severity is not None:
        findings_q = findings_q.where(DataQualityFinding.severity == severity)
    if not include_resolved:
        findings_q = findings_q.where(DataQualityFinding.resolved_at.is_(None))

    findings_q = findings_q.order_by(DataQualityFinding.window_start).limit(limit)

    return DataQualityResponse(
        instrument_id=instrument.id,
        symbol=instrument.symbol,
        datasets=[
            DatasetQualityOut.model_validate(row) for row in session.scalars(datasets_q)
        ],
        findings=[FindingOut.model_validate(row) for row in session.scalars(findings_q)],
    )
