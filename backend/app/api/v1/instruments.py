"""Instrument catalogue."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import AssetClass
from app.db.session import get_db
from app.models.instruments import Instrument
from app.schemas.market import InstrumentOut
from app.services.instruments import get_instrument

router = APIRouter(prefix="/instruments", tags=["instruments"])


@router.get("", response_model=list[InstrumentOut])
def list_instruments(
    session: Session = Depends(get_db),
    asset_class: AssetClass | None = None,
    search: str | None = Query(default=None, max_length=64),
    active_only: bool = True,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[Instrument]:
    query = select(Instrument)
    if asset_class is not None:
        query = query.where(Instrument.asset_class == asset_class)
    if active_only:
        query = query.where(Instrument.is_active.is_(True))
    if search:
        query = query.where(Instrument.symbol.ilike(f"%{search.upper()}%"))
    query = query.order_by(Instrument.symbol).limit(limit).offset(offset)
    return list(session.scalars(query))


@router.get("/{instrument_id}", response_model=InstrumentOut)
def read_instrument(instrument_id: uuid.UUID, session: Session = Depends(get_db)) -> Instrument:
    return get_instrument(session, instrument_id)
