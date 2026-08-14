"""Decision, readiness and safety-posture endpoints (spec phases 38-40, §43-45).

Three read-only views the dashboard needs and did not have.

`/decisions/{instrument_id}` runs the full chain and returns the trace. It is a
GET because it changes nothing: the chain reads bars, decides, and hands back
where it stopped. Reaching an order intent is not placing one, and the payload
says so on every response.

`/decisions/posture` is the screen an operator looks at when something feels
wrong. It answers the only question that matters at that moment — *can this
thing trade right now, and if not, what is stopping it* — and it answers from
the running configuration rather than from a document.

`/decisions/readiness` grades the deployment. It is deliberately not a health
check: health says the process is answering, readiness says the process is safe
to trade with, and a system can be entirely healthy and entirely unready.

Every route here is a GET behind the READ permission. There is nothing in this
module that mutates, which is why the execution gate leaves it alone — and the
gate is what makes that statement checkable rather than a promise.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.api.guard import find_ungated_routes, mutating_routes
from app.brain import calibration as cal
from app.brain import risk as risk_brain
from app.brain import stress as stress_brain
from app.core.config import get_settings
from app.core.enums import Permission, Timeframe
from app.db.session import get_db
from app.execution.safety import ExecutionPolicy, KillSwitch
from app.ops import health_score
from app.ops import incidents as incident_memory
from app.ops import readiness as rd
from app.pipeline import decide as pipeline
from app.services import retention
from app.services.instruments import get_instrument

router = APIRouter(prefix="/decisions", tags=["decisions"])

READ = Depends(require(Permission.READ))


@router.get("/posture")
def read_posture(
    _: Principal = READ,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Can this deployment trade right now, and what is stopping it?

    Read from the live settings and the live router table, never from a stored
    summary. A posture view that reports what was true at boot is the view that
    reassures somebody during the incident it should have flagged.
    """
    from app.main import app as fastapi_app

    settings = get_settings()
    policy = ExecutionPolicy(
        enabled=settings.enable_execution,
        dry_run=settings.execution_dry_run,
        require_auth=settings.require_auth,
        max_risk_r_per_order=settings.max_risk_r_per_order,
    )
    blockers: list[str] = []
    if not policy.enabled:
        blockers.append("execution is disabled for this deployment")
    if policy.dry_run:
        blockers.append("dry run is on — orders would be simulated, not sent")
    if not policy.require_auth:
        blockers.append("authentication is off, so no order could be attributed")
    if KillSwitch().engaged:
        blockers.append("the kill switch defaults to engaged")

    return {
        "can_trade": not blockers,
        "blockers": blockers,
        "policy": {
            "execution_enabled": policy.enabled,
            "dry_run": policy.dry_run,
            "require_auth": policy.require_auth,
            "max_risk_r_per_order": policy.max_risk_r_per_order,
        },
        "routes": {
            "mutating": [f"{'/'.join(m)} {p}" for p, m in mutating_routes(fastapi_app)],
            "ungated": [
                str(o) for o in find_ungated_routes(fastapi_app, require_auth=policy.require_auth)
            ],
        },
        "operational_rows": retention.operational_row_counts(session),
        "note": "this reports posture; it changes nothing",
    }


@router.get("/readiness")
def read_readiness(
    _: Principal = READ,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Grade the deployment. Health says it answers; this says it is safe."""
    from app.main import app as fastapi_app

    settings = get_settings()
    deployment = rd.Deployment(
        require_auth=settings.require_auth,
        execution_enabled=settings.enable_execution,
        execution_dry_run=settings.execution_dry_run,
        kill_switch_default_engaged=KillSwitch().engaged,
        ungated_mutating_routes=[
            str(o)
            for o in find_ungated_routes(fastapi_app, require_auth=settings.require_auth)
        ],
        retention_configured=bool(retention.POLICIES),
        broker_is_simulated=True,
        # Left as None on purpose: this process cannot see the host's disk, the
        # docker log driver or the restore history, and guessing them would be
        # the one thing `readiness` refuses. They fail as undeterminable, which
        # is the honest grade until an operator supplies them.
    )
    report = rd.assess(deployment, now=datetime.now(UTC))
    payload = report.as_dict()
    # Computed from the checks that just ran rather than by a second pass, so
    # the score and the list underneath it can never disagree about what was
    # true at the same moment.
    payload["health"] = health_score.compute(report, session).as_dict()
    return payload


@router.get("/incidents")
def read_incidents(
    _: Principal = READ,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """What is broken now, what keeps coming back, and what fixed it before.

    The three lists answer different questions and are kept apart. What is open
    is about the present; what recurs is about the pattern, which is usually a
    warning nobody escalated rather than the loudest failure; and a remedy is
    listed only once the same problem was seen again after it and then cleared.
    """
    return {
        "open": [
            {
                "fingerprint": incident.fingerprint,
                "source": incident.source,
                "summary": incident.summary,
                "severity": incident.severity,
                "occurrences": incident.occurrences,
                "first_seen_at": incident.first_seen_at.isoformat(),
                "last_seen_at": incident.last_seen_at.isoformat(),
            }
            for incident in incident_memory.open_incidents(session)
        ],
        "recurring": incident_memory.recurring(session, minimum=3),
        "confirmed_remedies": incident_memory.known_remedies(session),
        "note": (
            "a remedy appears here only after the same problem was seen again "
            "and then cleared. Recording one on request would store a belief, "
            "and 'the alert stopped' would store a coincidence - the alert also "
            "stops when the checker dies"
        ),
    }


@router.get("/{instrument_id}")
def read_decision(
    instrument_id: uuid.UUID,
    timeframe: Timeframe = Query(default=Timeframe.H1),
    as_of: datetime | None = Query(
        default=None, description="Knowledge cutoff. Defaults to now."
    ),
    equity: float = Query(default=100_000.0, gt=0),
    _: Principal = READ,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Run the chain and return where the decision stopped.

    The account state is supplied by query rather than read from anywhere,
    because this endpoint answers "what would the system decide for an account
    that looked like this" — and there is no live account wired to it. An
    endpoint that invented one would be answering a different question in a
    convincing voice.
    """
    instrument = get_instrument(session, instrument_id)
    cutoff = (as_of or datetime.now(UTC)).astimezone(UTC)

    account = risk_brain.AccountState(
        equity=equity,
        balance=equity,
        peak_equity=equity,
        daily_pnl_r=0.0,
        open_positions=0,
        used_margin=0.0,
        free_margin=equity,
    )
    # Pessimistic, and stated: nothing here has been calibrated against
    # resolved outcomes yet, so the chain will refuse at the expected-value
    # gate. That refusal is the correct answer, not a gap in the endpoint.
    health = risk_brain.DataHealth(
        data_age_bars=0.0, training_eligible=True, calibrated=False, safe_mode=False
    )
    uncalibrated = cal.CalibrationReport(
        calibrated=False,
        source="council",
        count=0,
        reason="no resolved forecasts have been scored for this deployment yet",
    )

    trace = pipeline.decide(
        session,
        instrument.id,
        timeframe,
        account=account,
        health=health,
        calibration=uncalibrated,
        history=_measured_history(),
        account_id="preview",
        base_currency=instrument.base_currency,
        quote_currency=instrument.quote_currency,
        r_value_pct=0.002,
        as_of=cutoff,
    )
    return trace.as_dict()


def _measured_history() -> stress_brain.TradeHistory | None:
    """No trade history exists yet, and none is invented.

    Returning a plausible-looking history would let the stress stage produce a
    survival projection about an account that has never traded.
    """
    return None
