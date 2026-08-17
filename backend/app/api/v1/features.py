"""Feature store endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.core.enums import Permission, Timeframe
from app.db.session import get_db
from app.features import all_specs
from app.schemas.market import FeatureRowOut, FeatureSpecOut, FeaturesResponse
from app.services import feature_store
from app.services.instruments import get_instrument

router = APIRouter(prefix="/features", tags=["features"])

READ = Depends(require(Permission.READ))


@router.get("/catalog", response_model=list[FeatureSpecOut])
def read_catalog(_: Principal = READ) -> list[FeatureSpecOut]:
    """Every registered feature, with the version and lookback it declares."""
    return [
        FeatureSpecOut(
            name=spec.name,
            version=spec.version,
            lookback=spec.lookback,
            description=spec.description,
            tags=list(spec.tags),
        )
        for spec in all_specs()
    ]


@router.get("/{instrument_id}", response_model=FeaturesResponse)
def read_features(
    instrument_id: uuid.UUID,
    timeframe: Timeframe = Query(default=Timeframe.H1),
    as_of: datetime = Query(
        description="Knowledge cutoff (UTC). Only features computed and knowable "
        "at this instant are returned."
    ),
    lookback: int = Query(default=100, ge=1, le=2000),
    session: Session = Depends(get_db),
    _: Principal = READ,
) -> FeaturesResponse:
    instrument = get_instrument(session, instrument_id)
    rows = feature_store.read_materialized(
        session, instrument_id, timeframe, as_of, lookback=lookback
    )
    stats = feature_store.coverage(session, instrument_id, timeframe)

    return FeaturesResponse(
        instrument_id=instrument.id,
        symbol=instrument.symbol,
        timeframe=timeframe,
        as_of=as_of,
        count=len(rows),
        materialized_values=stats.values,
        materialized_features=stats.features,
        rows=[
            FeatureRowOut(
                event_time=row.event_time,
                source_revision=row.source_revision,
                values=row.values,
            )
            for row in rows
        ],
    )
