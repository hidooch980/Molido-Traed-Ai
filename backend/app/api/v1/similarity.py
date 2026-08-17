"""Historical similarity endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.core.enums import Permission, Timeframe
from app.db.session import get_db
from app.services import similarity
from app.services.instruments import get_instrument

router = APIRouter(prefix="/similarity", tags=["similarity"])

READ = Depends(require(Permission.READ))


@router.get("/{instrument_id}")
def read_similar(
    instrument_id: uuid.UUID,
    timeframe: Timeframe = Query(default=Timeframe.H1),
    as_of: datetime | None = Query(
        default=None,
        description="Knowledge cutoff. Only episodes matured by this instant "
        "are searchable, and the feature scaling is learned from those alone.",
    ),
    k: int = Query(default=50, ge=5, le=500),
    session: Session = Depends(get_db),
    _: Principal = READ,
) -> dict:
    instrument = get_instrument(session, instrument_id)
    cutoff = (as_of or datetime.now(UTC)).astimezone(UTC)

    result = similarity.find_similar(
        session, instrument_id, timeframe, cutoff, k=k
    )
    return {
        "instrument_id": str(instrument.id),
        "symbol": instrument.symbol,
        "timeframe": timeframe.value,
        **result.as_payload(),
    }
