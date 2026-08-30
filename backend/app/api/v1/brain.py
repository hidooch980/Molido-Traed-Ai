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

from app.api.deps import Principal, require
from app.brain import calibration, cognitive, context, strategy
from app.core.enums import Permission, Timeframe
from app.db.session import get_db
from app.services import episodes as episode_service
from app.services import regime as regime_service
from app.services import world_state

router = APIRouter(prefix="/brain", tags=["brain"])

READ = Depends(require(Permission.READ))


def _cutoff(as_of: datetime | None) -> datetime:
    return (as_of or datetime.now(UTC)).astimezone(UTC)


@router.get("/regime/{instrument_id}")
def read_regime(
    instrument_id: uuid.UUID,
    timeframe: Timeframe = Query(default=Timeframe.H1),
    as_of: datetime | None = None,
    session: Session = Depends(get_db),
    _: Principal = READ,
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
    _: Principal = READ,
) -> dict:
    """The full reasoning chain behind one proposal (spec 46 decision replay)."""
    return cognitive.think(session, instrument_id, timeframe, _cutoff(as_of)).as_dict()


@router.get("/context/{instrument_id}")
def read_context(
    instrument_id: uuid.UUID,
    timeframe: Timeframe = Query(default=Timeframe.H1),
    as_of: datetime | None = None,
    session: Session = Depends(get_db),
    _: Principal = READ,
) -> dict:
    """The third brain: slow context, and the right to say "not now".

    Runs the fast proposal first, then reads the slow signals - crowd
    positioning, policy-rate carry, the closing bell - and returns the brake
    it would apply to whatever the other layers permit. Advisory here;
    binding only at the order gate, so the forward measurement stays a clean
    series of the first brain alone.

    Each slow signal degrades to an abstention rather than an error. This
    endpoint reaching out to the CFTC and the BIS is exactly why it is its
    own route instead of a block inside `think`: a decision endpoint that
    waits on two external agencies is a decision endpoint that is sometimes
    thirty seconds slow, and the brake is worth having even when both are
    unreachable.
    """
    from app.models.instruments import Instrument
    from app.services import policy_rates, positioning, sessions

    cutoff = _cutoff(as_of)
    proposal = cognitive.think(session, instrument_id, timeframe, cutoff)

    instrument = session.get(Instrument, instrument_id)
    base = (instrument.base_currency or "").upper() if instrument else ""
    quote = (instrument.quote_currency or "").upper() if instrument else ""

    crowd_tilt: float | None = None
    rate_differential: float | None = None
    seconds_to_close: float | None = None
    gap_seconds: float | None = None
    signal_errors: dict[str, str] = {}

    if base and quote:
        try:
            crowd_tilt = positioning.pair_tilt(base, quote, cutoff)["tilt"]
        except Exception as exc:  # noqa: BLE001 - abstention, with the reason kept
            signal_errors["positioning"] = f"{type(exc).__name__}: {exc}"
        try:
            rate_differential = policy_rates.differential(base, quote)
        except Exception as exc:  # noqa: BLE001
            signal_errors["policy_rates"] = f"{type(exc).__name__}: {exc}"
    else:
        signal_errors["positioning"] = "instrument has no currency pair"
        signal_errors["policy_rates"] = "instrument has no currency pair"

    if instrument is not None:
        try:
            calendar = sessions.build_calendar(session, instrument)
            close = calendar.next_close(cutoff)
            if close is not None:
                seconds_to_close = (close - cutoff).total_seconds()
                reopen = calendar.next_open(close)
                if reopen is not None:
                    gap_seconds = (reopen - close).total_seconds()
        except Exception as exc:  # noqa: BLE001
            signal_errors["calendar"] = f"{type(exc).__name__}: {exc}"

    verdict = context.read(
        proposal.decision,
        crowd_tilt=crowd_tilt,
        rate_differential=rate_differential,
        seconds_to_close=seconds_to_close,
        gap_seconds=gap_seconds,
    )

    return {
        "symbol": proposal.symbol,
        "timeframe": timeframe.value,
        "as_of": cutoff.isoformat(),
        "proposal": {
            "decision": proposal.decision.value,
            "conviction": proposal.conviction,
        },
        "verdict": verdict.as_dict(),
        "signals": {
            "crowd_tilt": crowd_tilt,
            "rate_differential": rate_differential,
            "seconds_to_close": seconds_to_close,
            "gap_seconds": gap_seconds,
        },
        # Why an abstention happened, kept apart from the verdict so the
        # brain's own output stays a pure function of its inputs.
        "signal_errors": signal_errors,
        "binding_at": "order gate only - the forward measurement stays a "
        "clean series of the first brain alone",
    }


@router.get("/strategies/{instrument_id}")
def read_strategies(
    instrument_id: uuid.UUID,
    timeframe: Timeframe = Query(default=Timeframe.H1),
    as_of: datetime | None = None,
    session: Session = Depends(get_db),
    _: Principal = READ,
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
    _: Principal = READ,
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
