"""Stage 6: BTB entry. Entry/SL/TP only from SPECIFIED-or-better rules; otherwise WAIT."""

from __future__ import annotations

from dataclasses import dataclass

from app.agents.pro_btb.rules import Rule, placement_rules_ready
from app.agents.pro_btb.stages.confirmation import ConfirmationResult
from app.agents.pro_btb.types import Direction, PipelineDecision, StageSnapshot


@dataclass(frozen=True)
class EntryResult:
    action: str  # WAIT, or BUY/SELL only when placement rules are SPECIFIED+
    direction: Direction
    reason: str
    entry: float | None
    stop_loss: float | None
    take_profit: float | None
    risk_reward: float | None
    invalidation: float | None

    def snapshot(self) -> StageSnapshot:
        return StageSnapshot(
            stage="btb_entry",
            valid=self.action in {"BUY", "SELL"},
            decision=PipelineDecision.WAIT if self.action == "WAIT" else PipelineDecision.CONTINUE,
            reasons=(self.reason,),
            details={
                "action": self.action,
                "direction": self.direction.value,
                "entry": self.entry,
                "stop_loss": self.stop_loss,
                "take_profit": self.take_profit,
                "risk_reward": self.risk_reward,
                "invalidation": self.invalidation,
            },
        )


def _wait(direction: Direction, reason: str) -> EntryResult:
    return EntryResult(
        action="WAIT", direction=direction, reason=reason,
        entry=None, stop_loss=None, take_profit=None,
        risk_reward=None, invalidation=None,
    )


def propose_entry(
    confirmation: ConfirmationResult,
    direction: Direction,
    catalog: dict[str, Rule] | None = None,
    *,
    # Prices are accepted only when placement_rules_ready(catalog) is true.
    # Tests may pass a promoted catalog together with explicit prices.
    entry: float | None = None,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    invalidation: float | None = None,
) -> EntryResult:
    if direction is Direction.NONE:
        return _wait(direction, "no direction; WAIT")
    if not confirmation.accepted:
        return _wait(direction, "confirmation rejected; WAIT — " + confirmation.reason)
    if not placement_rules_ready(catalog):
        return _wait(
            direction,
            "WAIT: exact entry, stop-loss and take-profit rules are not SPECIFIED "
            "(or better); no guessed placement is emitted. RR and invalidation are "
            "logged as null until those rules are sourced.",
        )
    if entry is None or stop_loss is None or take_profit is None:
        return _wait(direction, "WAIT: placement rules are ready but no prices were supplied")
    risk = abs(entry - stop_loss)
    reward = abs(take_profit - entry)
    if risk <= 0:
        return _wait(direction, "WAIT: stop distance is not positive")
    rr = reward / risk
    action = "BUY" if direction is Direction.BULL else "SELL"
    return EntryResult(
        action=action, direction=direction,
        reason="placement rules are SPECIFIED or better; prices recorded",
        entry=entry, stop_loss=stop_loss, take_profit=take_profit,
        risk_reward=rr, invalidation=invalidation,
    )
