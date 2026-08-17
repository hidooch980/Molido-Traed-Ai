"""Point-in-time market data endpoint.

`as_of` is required. There is no "just give me the latest" shortcut here on
purpose: an implicit now is how lookahead bias gets into a backtest, and a
caller that genuinely wants live data can pass the current timestamp and say
so.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.core.enums import Permission, Timeframe
from app.db.session import get_db
from app.schemas.market import BarOut, BarsResponse
from app.services.instruments import get_instrument
from app.services.point_in_time import get_bars, is_training_eligible

router = APIRouter(prefix="/bars", tags=["market-data"])

READ = Depends(require(Permission.READ))


@router.get("", response_model=BarsResponse)
def read_bars(
    instrument_id: uuid.UUID = Query(description="Canonical instrument id"),
    timeframe: Timeframe = Query(description="Bar timeframe"),
    as_of: datetime = Query(
        description="Knowledge cutoff (UTC, ISO-8601). Only bars closed and known "
        "at this instant are returned."
    ),
    lookback: int = Query(default=500, ge=1, le=5000),
    provider_id: uuid.UUID | None = None,
    session: Session = Depends(get_db),
    _: Principal = READ,
) -> BarsResponse:
    instrument = get_instrument(session, instrument_id)
    bars = get_bars(
        session,
        instrument_id,
        timeframe,
        as_of,
        lookback=lookback,
        provider_id=provider_id,
    )
    return BarsResponse(
        instrument_id=instrument.id,
        symbol=instrument.symbol,
        timeframe=timeframe,
        as_of=as_of,
        count=len(bars),
        training_eligible=is_training_eligible(
            session, instrument_id, timeframe, provider_id=provider_id
        ),
        bars=[
            BarOut(
                event_time=b.event_time,
                open=b.open,
                high=b.high,
                low=b.low,
                close=b.close,
                volume=b.volume,
                tick_volume=b.tick_volume,
                spread=b.spread,
                revision=b.revision,
                quality_score=b.quality_score,
            )
            for b in bars
        ],
    )
