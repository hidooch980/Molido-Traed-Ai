"""World state endpoint."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.core.enums import Permission, Timeframe
from app.db.session import get_db
from app.services import world_state

router = APIRouter(prefix="/world-state", tags=["world-state"])

READ = Depends(require(Permission.READ))


@router.get("/{instrument_id}")
def read_world_state(
    instrument_id: uuid.UUID,
    timeframe: Timeframe = Query(default=Timeframe.H1),
    as_of: datetime | None = Query(
        default=None, description="Knowledge cutoff. Defaults to now."
    ),
    session: Session = Depends(get_db),
    _: Principal = READ,
) -> dict:
    cutoff = (as_of or datetime.now(UTC)).astimezone(UTC)
    return world_state.build(session, instrument_id, timeframe, cutoff).as_dict()
