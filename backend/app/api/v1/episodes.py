"""Historical episode endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.enums import Timeframe
from app.db.session import get_db
from app.schemas.market import EpisodeOut, EpisodesResponse
from app.services import episodes as episode_service
from app.services.instruments import get_instrument

router = APIRouter(prefix="/episodes", tags=["episodes"])


@router.get("/{instrument_id}", response_model=EpisodesResponse)
def read_episodes(
    instrument_id: uuid.UUID,
    timeframe: Timeframe = Query(default=Timeframe.H1),
    as_of: datetime | None = Query(
        default=None,
        description="Knowledge cutoff. Episodes whose outcome window is still "
        "open at this instant are excluded — their outcome had not happened.",
    ),
    horizon_bars: int | None = None,
    session_label: str | None = Query(
        default=None, description="Filter to episodes that occurred in this session."
    ),
    limit: int = Query(default=100, ge=1, le=1000),
    session: Session = Depends(get_db),
) -> EpisodesResponse:
    instrument = get_instrument(session, instrument_id)
    cutoff = (as_of or datetime.now(UTC)).astimezone(UTC)

    rows = episode_service.query(
        session,
        instrument_id,
        timeframe,
        cutoff,
        horizon_bars=horizon_bars,
        limit=limit,
        session_label=session_label,
    )
    stats = episode_service.coverage(session, instrument_id, timeframe)

    return EpisodesResponse(
        instrument_id=instrument.id,
        symbol=instrument.symbol,
        timeframe=timeframe,
        as_of=cutoff,
        count=len(rows),
        stored=int(stats["episodes"]),
        matured=int(stats["matured"]),
        distribution=episode_service.outcome_distribution(rows),
        episodes=[
            EpisodeOut(
                event_time=row.event_time,
                outcome_ready_at=row.outcome_ready_at,
                horizon_bars=row.horizon_bars,
                entry_price=float(row.entry_price),
                session_labels=row.session_labels or [],
                features=row.features or {},
                max_up_pct=float(row.max_up_pct) if row.max_up_pct is not None else None,
                max_down_pct=(
                    float(row.max_down_pct) if row.max_down_pct is not None else None
                ),
                forward_return_pct=(
                    float(row.forward_return_pct)
                    if row.forward_return_pct is not None
                    else None
                ),
                bars_to_max_up=row.bars_to_max_up,
                bars_to_max_down=row.bars_to_max_down,
                regime=row.regime,
                strategy=row.strategy,
                decision=row.decision,
            )
            for row in rows
        ],
    )
