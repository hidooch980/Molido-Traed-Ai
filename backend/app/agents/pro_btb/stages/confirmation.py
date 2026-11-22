"""Stage 5: confirmation. Reject keeps waiting; accept hands off to entry. Reason is logged."""

from __future__ import annotations

from dataclasses import dataclass

from app.agents.pro_btb.stages.bo_candle import BoCandleResult
from app.agents.pro_btb.stages.retest import RetestResult
from app.agents.pro_btb.stages.strong_leg import StrongLegResult
from app.agents.pro_btb.types import PipelineDecision, StageSnapshot


@dataclass(frozen=True)
class ConfirmationResult:
    accepted: bool
    reason: str
    checks: dict[str, bool]

    def snapshot(self) -> StageSnapshot:
        return StageSnapshot(
            stage="confirmation",
            valid=self.accepted,
            decision=PipelineDecision.CONTINUE if self.accepted else PipelineDecision.WAIT,
            reasons=(self.reason,),
            details={"checks": self.checks, "checklist_status": "RESEARCH"},
        )


def confirm_setup(
    leg: StrongLegResult,
    bo: BoCandleResult,
    retest: RetestResult,
) -> ConfirmationResult:
    """Default checklist is RESEARCH; the accept/reject-and-log process is specified."""
    checks = {
        "strong_leg_valid": leg.valid and not leg.stopped,
        "bo_found": bo.found and bo.valid,
        "btb_zone_stored": retest.zone is not None,
        "price_returned_to_btb": retest.returned,
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        reason = "rejected: " + ", ".join(failed) + "; no entry, continue waiting"
        return ConfirmationResult(False, reason, checks)
    reason = "accepted: strong leg, BO candle and BTB retest all present"
    if leg.high_risk:
        reason += "; strong leg was marked high-risk"
    if bo.risk_flags:
        reason += "; BO risk flags: " + ",".join(bo.risk_flags)
    return ConfirmationResult(True, reason, checks)
