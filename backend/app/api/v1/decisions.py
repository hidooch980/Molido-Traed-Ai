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
from app.brain import analyst
from app.brain import calibration as cal
from app.brain import risk as risk_brain
from app.brain import stress as stress_brain
from app.core.config import get_settings
from app.core.enums import AuditEventType, Permission, Timeframe
from app.core.errors import MolidoError
from app.db.session import get_db
from app.execution.safety import ExecutionPolicy, KillSwitch
from app.ops import bottlenecks, disk, health_score, self_healing
from app.ops import incidents as incident_memory
from app.pipeline import decide as pipeline
from app.services import policy_rates, retention, security_log
from app.services.instruments import get_instrument

router = APIRouter(prefix="/decisions", tags=["decisions"])

READ = Depends(require(Permission.READ))
#: The analysis endpoint costs money to answer, so it is not READ.
SIMULATE = Depends(require(Permission.SIMULATE))


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
    # Every fact from the live system, gathered once (`app.ops.posture`):
    # the host's evidence notes for what a container cannot see, the bar
    # table for freshness, the audit chain, the forward journal, the SLO
    # window, the kill switch file. The same gatherer the trading cycle
    # uses, so this page and the thing that sends orders cannot disagree.
    from app.ops import posture as posture_module

    posture = posture_module.gather(
        session,
        now=datetime.now(UTC),
        ungated_mutating_routes=[
            str(o)
            for o in find_ungated_routes(fastapi_app, require_auth=settings.require_auth)
        ],
    )
    report = posture.report
    payload = posture.as_dict()
    # Computed from the checks that just ran rather than by a second pass, so
    # the score and the list underneath it can never disagree about what was
    # true at the same moment.
    payload["health"] = health_score.compute(report, session).as_dict()

    # Checked here rather than assumed unknowable. `readiness` said the host
    # disk could not be seen from inside a container; it can - the container's
    # root is the host's disk, and the reading differs by the overlay, not by
    # the device. The assumption went untested for months while the disk
    # reached 82% with nobody watching.
    state = disk.measure()
    payload["disk"] = state.as_dict()
    if state.severity:
        incident_memory.record(
            session,
            incident_memory.Report(
                source="disk",
                summary=state.summary,
                severity=state.severity,
                details=state.as_dict(),
            ),
        )
    else:
        incident_memory.clear(session, "disk", state.summary)

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


@router.get("/bottlenecks")
def read_bottlenecks(
    _: Principal = READ,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Where effort is going that produces nothing.

    Ranked by estimated cost rather than severity, because the two disagree
    constantly and the expensive thing is usually the quiet one - which is
    exactly why nobody has fixed it. Everything is derived from data already
    stored; nothing new is measured, because a profiler with its own memory
    footprint on a two-core host would be measuring a slowdown it caused.
    """
    return bottlenecks.analyse(session)


@router.get("/healing")
def read_healing(
    _: Principal = READ,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """What repair the system would attempt, and why it would refuse.

    A GET, and there is no POST beside it. `apply` exists in the module and
    takes both an explicit confirmation and the function that does the work, so
    nothing can be repaired by calling a URL. Turning that into a scheduled job
    is a separate decision with its own consequences, and it belongs to whoever
    owns the machine rather than to whoever can reach the API.
    """
    plans = [
        self_healing.plan(session, incident.fingerprint).as_dict()
        for incident in incident_memory.open_incidents(session)
    ]
    return {
        "plans": plans,
        "would_act_on": [p["fingerprint"] for p in plans if p["allowed"]],
        "catalogue": [
            {
                "action": action.name,
                "description": action.description,
                "why_safe": action.why_safe,
                "reversible": action.reversible,
            }
            for action in self_healing.CATALOGUE.values()
        ],
        "budget_per_hour": self_healing.MAX_ATTEMPTS_PER_WINDOW,
        "automatic": False,
        "note": (
            "no route here repairs anything. Every action is reversible, "
            "budgeted three to the hour, recorded before it runs and credited "
            "only when the raising signal clears - a command exiting zero is a "
            "command exiting zero, not a repair"
        ),
    }


@router.get("/{instrument_id}/analysis")
def read_decision_analysis(
    instrument_id: uuid.UUID,
    timeframe: Timeframe = Query(default=Timeframe.H1),
    as_of: datetime | None = Query(default=None),
    equity: float = Query(default=100_000.0, gt=0),
    language: str = Query(default="fa", max_length=8),
    principal: Principal = SIMULATE,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """The same chain, with the second brain's reading of it.

    Two things are returned, and keeping them separate is the point: the trace
    is what the system decided, and the analysis is one opinion about that
    decision. A response that merged them would let a sentence the model wrote
    be read as a step the chain took.

    Behind SIMULATE rather than READ because it costs money to answer. Every
    call is a request to a model; a page that polled this on READ would bill
    the account holder for a refresh they did not know they made.

    The verdict is recorded whether or not it is any good - "was the analyst
    right" has to be a question with an answer, and it cannot be one if only
    the answers somebody liked were kept.
    """
    trace = _trace_for(session, instrument_id, timeframe, as_of=as_of, equity=equity)
    verdict = analyst.analyse(trace, language=language)

    security_log.record(
        session,
        AuditEventType.ANALYST_SPOKE,
        summary=verdict.headline[:200],
        user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        detail={
            "instrument_id": str(instrument_id),
            "timeframe": str(timeframe),
            "available": verdict.available,
            "objection_strength": verdict.objection_strength,
            "would_have_traded": verdict.would_have_traded,
            # The trace's own words for where it ended. Recorded beside the
            # analyst's `would_have_traded` because the pair is the whole
            # scoring question: the chain refused at this gate, the analyst
            # would or would not have.
            "stopped_at": trace.get("stopped_at"),
            "reached_intent": trace.get("reached_intent"),
            "model": verdict.model,
            "unavailable_because": verdict.unavailable_because,
        },
    )
    session.commit()

    return {
        "trace": trace,
        "analysis": verdict.as_dict(),
        "note": (
            "the trace is what the system decided; the analysis is one opinion "
            "about it, produced afterwards and connected to nothing"
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

    # The carry input, fetched here because fetching is the caller's job - the
    # chain must be runnable over historical bars, and a pipeline that reads
    # "now" from inside itself can never be replayed. This endpoint answers for
    # the present, so the present differential is the right one to hand it.
    #
    # None when either leg has no policy rate (gold and the index futures are
    # not currencies), and None when the feed cannot be read. Both leave the
    # swap where it has always been on this deployment - in the unmeasured
    # list. This is not one of the chain's gates, where "could not check" must
    # equal "failed"; it is one term of a sum, and the cost model already
    # reports a missing term by name.
    rate_differential: float | None = None
    if instrument.base_currency and instrument.quote_currency:
        try:
            rate_differential = policy_rates.differential(
                instrument.base_currency, instrument.quote_currency
            )
        except MolidoError:
            rate_differential = None

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
        rate_differential=rate_differential,
        r_value_pct=0.002,
        as_of=cutoff,
    )
    return trace.as_dict()


def _trace_for(
    session: Session,
    instrument_id: uuid.UUID,
    timeframe: Timeframe,
    *,
    as_of: datetime | None,
    equity: float,
) -> dict[str, Any]:
    """The trace, built exactly the way `read_decision` builds it.

    Shared rather than reimplemented so the analysed trace is provably the
    trace the plain endpoint returns. Two constructions that drift would mean
    the analysis explains a decision the operator never saw.
    """
    return read_decision(
        instrument_id,
        timeframe=timeframe,
        as_of=as_of,
        equity=equity,
        session=session,
    )


def _measured_history() -> stress_brain.TradeHistory | None:
    """No trade history exists yet, and none is invented.

    Returning a plausible-looking history would let the stress stage produce a
    survival projection about an account that has never traded.
    """
    return None
