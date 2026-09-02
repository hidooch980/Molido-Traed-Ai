"""The deployment as it is right now: readiness, the three states, one decision.

One function gathers every live fact - the host's evidence notes, the disk,
the bar table, the audit chain, the forward journal, the SLO window, the
kill switch file, the edge registry, the settings - and hands them to
`readiness.assess` and `authorization.decide`. The API route and the
trading cycle both call it, so the dashboard and the thing that sends
orders can never disagree about what was true at the same moment.

Nothing here is cached. Every call reads the world again, which is the
whole of automatic recovery: a blocker that has cleared is not there the
next time anybody looks, and nothing has to be reset for it to clear.

Every reader is wrapped so that one unreachable source becomes one
undeterminable fact (a failed check) rather than an exception on the path
that decides whether to trade. A posture that raises halts the caller,
and the caller was about to refuse anyway - this way it refuses with the
reason attached.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.execution import killswitch_store, modes
from app.learning import edge as edge_registry
from app.ops import authorization, calibration, disk, evidence, freshness, readiness as rd, slo


@dataclass
class Posture:
    checked_at: datetime
    report: rd.ReadinessReport
    decision: authorization.Decision
    details: dict[str, Any] = field(default_factory=dict)
    #: Readers that failed, by name, with the exception's type. A posture
    #: with a failed reader is still a posture; it just has a failed check.
    reader_failures: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload = self.report.as_dict()
        payload["authorization"] = self.decision.as_dict()
        payload["details"] = self.details
        payload["reader_failures"] = self.reader_failures
        return payload


def _try(name: str, reader: Callable[[], Any], failures: dict[str, str], default: Any = None) -> Any:
    try:
        return reader()
    except Exception as problem:  # noqa: BLE001 - one bad reader is one failed check
        failures[name] = type(problem).__name__
        return default


def gather(
    session: Session,
    *,
    now: datetime | None = None,
    ungated_mutating_routes: list[str] | None = None,
    account: dict[str, Any] | None = None,
    account_reason: str = "",
    risk_approved: bool | None = None,
    risk_reason: str = "",
    data_age_bars: float | None = None,
    broker_adapter: Any = None,
) -> Posture:
    """Read everything and decide.

    `account`, `risk_approved` and `data_age_bars` are the facts only the
    trading cycle has (it holds the terminal's publication and the risk
    brain's verdict); the API route leaves them None, and the decision it
    reports then shows those gates as unobserved rather than guessing them.
    `ungated_mutating_routes` is the API's own fact and the cycle leaves it
    to the empty list the route check has always reported.
    """
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    settings = get_settings()
    failures: dict[str, str] = {}
    details: dict[str, Any] = {}

    switch = _try("kill_switch", killswitch_store.load, failures)
    disk_state = _try("disk", disk.measure, failures)
    fresh = _try("freshness", lambda: freshness.measure(session, now=moment), failures)
    calibrated = _try("calibration", lambda: calibration.measure(session, now=moment), failures)
    window = _try("slo", lambda: slo.window(session, now=moment), failures)

    def _chain():
        from app.services import audit

        return audit.verify(session, tail=500)

    chain = _try("audit_chain", _chain, failures)

    log_rotation = _try("log_rotation", lambda: evidence.log_rotation_configured(now=moment), failures)
    restore = _try("restore_drill", lambda: evidence.last_successful_restore(now=moment), failures)
    secrets = _try("secrets", lambda: evidence.secrets_in_repository(now=moment), failures)

    # The adapter that would actually be handed an order. Live paper mode
    # swaps in a paper broker; everything else is the terminal.
    if broker_adapter is None:
        def _adapter():
            from app.execution import autopilot
            from app.execution.metatrader_broker import MetaTraderBroker

            mode, _why, _live = autopilot.mode_now()
            if mode == autopilot.PAPER:
                from app.execution.paper_broker import LivePaperBroker

                return LivePaperBroker()
            return MetaTraderBroker()

        broker_adapter = _try("broker_adapter", _adapter, failures)
    mode_report = (
        modes.classify(broker_adapter, dry_run=bool(settings.execution_dry_run))
        if broker_adapter is not None
        else None
    )

    if fresh is not None:
        details["freshness"] = fresh.as_dict()
        if data_age_bars is None:
            data_age_bars = fresh.best_decision_age_bars
    if calibrated is not None:
        details["calibration"] = calibrated.as_dict()
    if window is not None:
        details["slo"] = window.as_dict()
    if chain is not None:
        details["audit_chain"] = chain.as_dict()
    if disk_state is not None:
        details["disk"] = disk_state.as_dict()
    if mode_report is not None:
        details["execution_mode"] = mode_report.as_dict()
    details["evidence"] = {
        "log_rotation_configured": log_rotation,
        "last_successful_restore": restore.isoformat() if restore else None,
        "secrets_in_repository": secrets,
        "directory": str(evidence.DEFAULT_DIR),
    }

    deployment = rd.Deployment(
        require_auth=settings.require_auth,
        execution_enabled=settings.enable_execution,
        execution_dry_run=settings.execution_dry_run,
        # The class default, which is what this check has always graded: a
        # switch that starts open protects nothing. The *file's* state is a
        # different fact and is in the decision below.
        kill_switch_default_engaged=True,
        ungated_mutating_routes=ungated_mutating_routes if ungated_mutating_routes is not None else [],
        log_rotation_configured=log_rotation,
        retention_configured=_try("retention", _retention_configured, failures),
        last_successful_restore=restore,
        disk_free_ratio=(1.0 - disk_state.used_ratio) if disk_state is not None else None,
        data_age_bars=data_age_bars,
        calibrated_sources=len(calibrated.calibrated) if calibrated is not None else None,
        slo_observations=window.observations if window is not None else None,
        audit_chain_intact=chain.intact if chain is not None else None,
        secrets_in_repository=secrets,
        broker_is_simulated=mode_report.simulated if mode_report is not None else None,
    )
    report = rd.assess(deployment, now=moment)

    allowed, why = _try("edge_registry", edge_registry.live_trading_allowed, failures, default=(None, "the edge registry could not be read"))

    facts = authorization.Facts(
        engine_running=bool(settings.enable_execution),
        kill_switch_engaged=None if switch is None else bool(switch.engaged),
        kill_switch_reason=getattr(switch, "reason", "") or "",
        readiness_blocking_failures=[c.name for c in report.blocking_failures],
        readiness_important_failures=[c.name for c in report.important_failures],
        data_age_bars=data_age_bars,
        max_data_age_bars=freshness.MAX_AGE_BARS,
        account_available=(bool(account.get("available")) if isinstance(account, dict) else None),
        account_reason=account_reason,
        proven_edge=allowed,
        proven_edge_reason=why,
        trade_without_proven_edge=bool(getattr(settings, "trade_without_proven_edge", False)),
        risk_approved=risk_approved,
        risk_reason=risk_reason,
        execution_mode=mode_report.mode.value if mode_report is not None else None,
        execution_mode_consistent=mode_report.consistent if mode_report is not None else None,
    )
    decision = authorization.decide(facts, now=moment)
    return Posture(
        checked_at=moment,
        report=report,
        decision=decision,
        details=details,
        reader_failures=failures,
    )


def _retention_configured() -> bool:
    from app.services import retention

    return bool(retention.POLICIES)


__all__ = ["Posture", "gather"]
