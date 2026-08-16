"""Instrument catalogue."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.core.enums import AssetClass, Permission
from app.db.session import get_db
from app.models.instruments import Instrument
from app.schemas.market import InstrumentOut
from app.services.instruments import get_instrument

router = APIRouter(prefix="/instruments", tags=["instruments"])

READ = Depends(require(Permission.READ))


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


@router.get("/tools/sessions")
def read_sessions(_: Principal = READ) -> dict[str, Any]:
    """Which forex sessions are open now, and whether they overlap."""
    from app.services import calculators

    return calculators.sessions_at()


@router.get("/tools/calculate")
def calculate(
    symbol: str,
    equity: float = Query(default=0.0, ge=0),
    risk_percent: float = Query(default=1.0, gt=0, le=100),
    stop_distance: float = Query(default=0.0, ge=0),
    lots: float = Query(default=1.0, gt=0),
    _: Principal = READ,
) -> dict[str, Any]:
    """Pip value, lot size and volatility for one symbol, from the broker's own
    contract specification.

    Every figure refuses rather than assuming. The broker publishes the tick
    value per symbol and it is not 10 dollars because gold is usually 100
    ounces - a calculator that assumes one is the difference between risking 1%
    and 10%, and it looks correct in both cases.
    """
    from app.providers.metatrader import MetaTraderBridge
    from app.services import calculators

    published = MetaTraderBridge().symbols()
    spec = next(
        (s for s in published.get("symbols", []) if s.get("name") == symbol), None
    )
    if spec is None:
        return {
            "available": False,
            "reason": (
                f"{symbol} is not in the terminal's Market Watch, so the broker "
                "has published no contract specification for it. Nothing here "
                "will compute from an assumed one"
            ),
            "known": [s.get("name") for s in published.get("symbols", [])],
        }

    tick_value = spec.get("tick_value")
    tick_size = spec.get("tick_size")

    return {
        "symbol": symbol,
        "specification": {
            "contract_size": spec.get("contract_size"),
            "tick_value": tick_value,
            "tick_size": tick_size,
            "volume_min": spec.get("volume_min"),
            "volume_step": spec.get("volume_step"),
            # Republished here because every number below depends on it, and a
            # reader checking a surprising result should not have to go
            # looking.
            "sizable": spec.get("sizable"),
        },
        "pip_value": calculators.pip_value(
            symbol=symbol,
            lots=lots,
            contract_size=spec.get("contract_size"),
            tick_value=tick_value,
            tick_size=tick_size,
        ),
        "lot_size": calculators.lot_size(
            symbol=symbol,
            equity=equity,
            risk_percent=risk_percent,
            stop_distance_price=stop_distance,
            tick_value=tick_value,
            tick_size=tick_size,
            volume_min=spec.get("volume_min"),
            volume_step=spec.get("volume_step"),
        )
        if equity and stop_distance
        else {
            "available": False,
            "reason": "supply equity and stop_distance to size a position",
        },
        "volatility": {
            "available": False,
            "reason": "volatility needs a bar series; use /api/v1/features",
        },
        "sessions": calculators.sessions_at(),
    }
