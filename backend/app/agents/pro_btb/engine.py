"""Run the six Pro BTB stages in order. Each stage is still callable on its own."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from app.agents.analyzers.bars import Candle
from app.agents.pro_btb.params import ProBtbParams
from app.agents.pro_btb.rules import RULE_BY_ID
from app.agents.pro_btb.stages.bo_candle import BoCandleResult, validate_bo_candle
from app.agents.pro_btb.stages.break_even import BreakEvenReport, identify_break_even_zones
from app.agents.pro_btb.stages.confirmation import ConfirmationResult, confirm_setup
from app.agents.pro_btb.stages.entry import EntryResult, propose_entry
from app.agents.pro_btb.stages.retest import RetestResult, assess_retest
from app.agents.pro_btb.stages.strong_leg import (
    StrongLegResult,
    assess_strong_leg,
    list_strong_legs,
)
from app.agents.pro_btb.types import (
    DecisionTrace,
    Direction,
    PipelineDecision,
    StageSnapshot,
)


def select_breakout_leg(
    bars: Sequence[Candle], params: ProBtbParams | None = None,
) -> StrongLegResult:
    """Prefer the most recent strong leg that actually broke a prior extreme.

    A later retracement can also pass the RESEARCH strength cutoffs; BTB still
    wants the impulse that produced the breakout. If no such leg exists, the
    most recent qualifying leg is returned (or a STOP result).
    """
    params = params or ProBtbParams()
    strong = list_strong_legs(bars, params)
    if not strong:
        return assess_strong_leg(bars, params)
    for leg in reversed(strong):
        if validate_bo_candle(bars, leg, params).found:
            return StrongLegResult(
                valid=leg.valid, stopped=False, high_risk=leg.high_risk,
                direction=leg.direction, start_index=leg.start_index,
                end_index=leg.end_index, start_price=leg.start_price,
                end_price=leg.end_price, length_atr=leg.length_atr,
                reasons=leg.reasons + ("selected as most recent strong leg with a BO candle",),
                metrics=leg.metrics,
            )
    return strong[-1]


class ProBtbEngine:
    """Pure, deterministic pipeline. No I/O, no orders, no Risk Brain calls."""

    def __init__(self, params: ProBtbParams | None = None) -> None:
        self.params = params or ProBtbParams()

    def assess_strong_leg(self, bars: Sequence[Candle]) -> StrongLegResult:
        return select_breakout_leg(bars, self.params)

    def validate_bo_candle(self, bars: Sequence[Candle], leg: StrongLegResult) -> BoCandleResult:
        return validate_bo_candle(bars, leg, self.params)

    def identify_break_even(self, bars: Sequence[Candle], leg: StrongLegResult) -> BreakEvenReport:
        return identify_break_even_zones(bars, leg, self.params)

    def assess_retest(self, bars: Sequence[Candle], bo: BoCandleResult) -> RetestResult:
        return assess_retest(bars, bo, self.params)

    def confirm(
        self, leg: StrongLegResult, bo: BoCandleResult, retest: RetestResult,
    ) -> ConfirmationResult:
        return confirm_setup(leg, bo, retest)

    def enter(self, confirmation: ConfirmationResult, direction: Direction) -> EntryResult:
        return propose_entry(confirmation, direction)

    def run(
        self,
        bars: Sequence[Candle],
        *,
        as_of: datetime,
        symbol: str = "UNKNOWN",
        timeframe: str = "H1",
    ) -> DecisionTrace:
        stages: list[StageSnapshot] = []
        risk_flags: list[str] = []

        leg = self.assess_strong_leg(bars)
        stages.append(leg.snapshot())
        if leg.high_risk:
            risk_flags.append("HIGH_RISK_LEG")
        if leg.stopped:
            empty_bo = validate_bo_candle(bars, leg, self.params)
            empty_be = identify_break_even_zones(bars, leg, self.params)
            empty_retest = assess_retest(bars, empty_bo, self.params)
            confirmation = confirm_setup(leg, empty_bo, empty_retest)
            entry = propose_entry(confirmation, leg.direction)
            stages.extend([empty_bo.snapshot(), empty_be.snapshot(), empty_retest.snapshot(),
                           confirmation.snapshot(), entry.snapshot()])
            return self._trace(
                symbol, timeframe, as_of, leg.direction, PipelineDecision.STOP, stages,
                empty_retest, empty_be, confirmation, entry, tuple(risk_flags),
            )

        bo = self.validate_bo_candle(bars, leg)
        stages.append(bo.snapshot())
        risk_flags.extend(bo.risk_flags)

        be = self.identify_break_even(bars, leg)
        stages.append(be.snapshot())

        retest = self.assess_retest(bars, bo)
        stages.append(retest.snapshot())

        confirmation = self.confirm(leg, bo, retest)
        stages.append(confirmation.snapshot())

        entry = self.enter(confirmation, leg.direction)
        stages.append(entry.snapshot())

        decision = PipelineDecision.WAIT
        if confirmation.accepted and entry.action in {"BUY", "SELL"}:
            decision = PipelineDecision.CONTINUE
        elif not confirmation.accepted or entry.action == "WAIT":
            decision = PipelineDecision.WAIT
        return self._trace(
            symbol, timeframe, as_of, leg.direction, decision, stages,
            retest, be, confirmation, entry, tuple(risk_flags),
        )

    def _trace(
        self,
        symbol: str,
        timeframe: str,
        as_of: datetime,
        direction: Direction,
        decision: PipelineDecision,
        stages: list[StageSnapshot],
        retest: RetestResult,
        be: BreakEvenReport,
        confirmation: ConfirmationResult,
        entry: EntryResult,
        risk_flags: tuple[str, ...],
    ) -> DecisionTrace:
        return DecisionTrace(
            symbol=symbol,
            timeframe=timeframe,
            as_of=as_of,
            direction=direction,
            decision=decision,
            stages=tuple(stages),
            btb_zone=retest.zone,
            break_even_zones=be.zones,
            zone_comparisons=be.comparisons,
            confirmation_accepted=confirmation.accepted,
            confirmation_reason=confirmation.reason,
            entry_action=entry.action,
            entry_reason=entry.reason,
            risk_reward=entry.risk_reward,
            invalidation=entry.invalidation,
            risk_flags=risk_flags,
            rule_statuses={rid: r.status.value for rid, r in RULE_BY_ID.items()},
        )
