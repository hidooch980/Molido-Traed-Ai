"""Cognitive-layer endpoints (phases 13-20).

Every route here is read-only and none authorises anything. The brain's output
is an opinion with its reasoning attached; turning an opinion into an order
requires the risk brain and the execution engine, neither of which exists.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.brain import calibration, cognitive, strategy
from app.core.enums import Timeframe
from app.db.session import get_db
from app.services import episodes as episode_service
from app.services import regime as regime_service
from app.services import world_state

router = APIRouter(prefix="/brain", tags=["brain"])


def _cutoff(as_of: datetime | None) -> datetime:
    return (as_of or datetime.now(UTC)).astimezone(UTC)


@router.get("/regime/{instrument_id}")
def read_regime(
    instrument_id: uuid.UUID,
    timeframe: Timeframe = Query(default=Timeframe.H1),
    as_of: datetime | None = None,
    session: Session = Depends(get_db),
) -> dict:
    return regime_service.classify(
        session, instrument_id, timeframe, _cutoff(as_of)
    ).as_dict()


@router.get("/think/{instrument_id}")
def read_proposal(
    instrument_id: uuid.UUID,
    timeframe: Timeframe = Query(default=Timeframe.H1),
    as_of: datetime | None = None,
    session: Session = Depends(get_db),
) -> dict:
    """The full reasoning chain behind one proposal (spec 46 decision replay)."""
    return cognitive.think(session, instrument_id, timeframe, _cutoff(as_of)).as_dict()


@router.get("/strategies/{instrument_id}")
def read_strategies(
    instrument_id: uuid.UUID,
    timeframe: Timeframe = Query(default=Timeframe.H1),
    as_of: datetime | None = None,
    session: Session = Depends(get_db),
) -> dict:
    cutoff = _cutoff(as_of)
    state = world_state.build(session, instrument_id, timeframe, cutoff).as_dict()
    state["regime"] = regime_service.classify(
        session, instrument_id, timeframe, cutoff
    ).as_dict()

    setups = strategy.evaluate(state)
    return {
        "instrument_id": str(instrument_id),
        "timeframe": timeframe.value,
        "as_of": cutoff.isoformat(),
        "regime": state["regime"]["regime"],
        "fired": [s.as_dict() for s in setups if s.fired],
        "evaluated": [s.as_dict() for s in setups],
    }


@router.get("/calibration/{instrument_id}")
def read_calibration(
    instrument_id: uuid.UUID,
    timeframe: Timeframe = Query(default=Timeframe.H1),
    as_of: datetime | None = None,
    session: Session = Depends(get_db),
) -> dict:
    """Whether any stored score has earned the word probability.

    Expected to report `calibrated: false` for a long time. That is the
    correct answer until enough matured outcomes exist, and reporting it
    plainly is the point of the endpoint.
    """
    cutoff = _cutoff(as_of)
    matured = episode_service.query(
        session, instrument_id, timeframe, cutoff, limit=5000
    )
    forecasts = calibration.build_forecasts_from_episodes(matured)
    report = calibration.evaluate(forecasts, source="episode_conviction")
    return {
        "instrument_id": str(instrument_id),
        "timeframe": timeframe.value,
        "as_of": cutoff.isoformat(),
        "matured_episodes": len(matured),
        **report.as_dict(),
    }
