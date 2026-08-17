"""Market memory endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.core.enums import Permission, Timeframe
from app.db.session import get_db
from app.schemas.market import MarketMemoryResponse
from app.services import market_memory
from app.services.instruments import get_instrument

router = APIRouter(prefix="/memory", tags=["memory"])

READ = Depends(require(Permission.READ))


@router.get("/{instrument_id}", response_model=MarketMemoryResponse)
def read_memory(
    instrument_id: uuid.UUID,
    timeframe: Timeframe = Query(default=Timeframe.H1),
    as_of: datetime | None = Query(
        default=None, description="Knowledge cutoff. Defaults to now."
    ),
    session: Session = Depends(get_db),
    _: Principal = READ,
) -> MarketMemoryResponse:
    instrument = get_instrument(session, instrument_id)
    cutoff = (as_of or datetime.now(UTC)).astimezone(UTC)

    snapshots = market_memory.recall_all(session, instrument_id, timeframe, cutoff)

    return MarketMemoryResponse(
        instrument_id=instrument.id,
        symbol=instrument.symbol,
        timeframe=timeframe,
        as_of=cutoff,
        # Every horizon is present, including unavailable ones — an absent key
        # would be indistinguishable from one the caller did not request.
        horizons=[snap.as_dict() for snap in snapshots.values()],
        agreement=market_memory.agreement(snapshots),
    )
