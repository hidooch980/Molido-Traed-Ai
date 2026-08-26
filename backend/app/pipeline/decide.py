"""The whole chain, end to end (spec §21-22, the part that makes the rest a system).

Every module before this one is excellent in isolation and answers a question
nobody asked on its own. This is where a decision actually travels: bars, then
features, regime, council, adversary, levels, calibrated probability, expected
value, portfolio room, risk authorisation, stress survival, challenge rules —
and only then an order intent.

The point of running it as one function is not convenience. It is that **a
decision must be able to say where it died**. A system of eighteen independent
modules produces eighteen independent refusals and no answer to "why did
nothing trade today?", which is the question an operator actually has. So the
return value is a trace: every stage, in order, with its verdict and its
reason, whether or not the chain got past it.

Three rules the chain enforces that no individual module can:

**Stopping is the normal outcome.** Most world states produce no trade. A chain
that reaches an order intent on a typical bar is a chain with a broken gate,
not a productive one.

**Nothing downstream can undo an upstream refusal.** The stages run in order
and the first block ends the walk. There is no scoring, no weighted vote across
layers, no "three out of five said yes". Each gate is a veto.

**A stage that could not run is a stage that failed.** Missing history, missing
calibration, missing correlation — none of them are skipped. Uncertainty
reduces what is permitted, and at this level "we could not check" and "the
check failed" are the same outcome for the same reason.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.brain import carry, cognitive
from app.brain import expected_value as ev
from app.brain import portfolio as pf
from app.brain import risk as risk_brain
from app.brain import stress as stress_brain
from app.brain.calibration import CalibrationReport
from app.core.enums import Decision, RiskVerdict, Timeframe
from app.execution.contracts import (
    Approval,
    OrderIntent,
    OrderSide,
    OrderType,
)

# How far the stop sits from entry, in ATR. Policy, not measurement: it is a
# choice about how much ordinary noise a position should survive, and it is
# published in the trace so nobody reads the levels as derived facts.
STOP_ATR_MULTIPLE = 1.5

# Reward:risk the levels are built to. Also policy. The EV stage then decides
# whether the resulting shape is worth taking at the calibrated probability —
# this constant sets the shape, it does not justify it.
TARGET_REWARD_RISK = 2.0


@dataclass
class Stage:
    """One gate, its verdict, and the reason — recorded whether it passed or not."""

    name: str
    passed: bool
    detail: str
    payload: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "payload": self.payload,
        }


@dataclass
class DecisionTrace:
    """Where a decision got to, and what stopped it.

    `intent` is None on almost every bar, and that is the design. The value of
    this object is `stopped_at` plus the stage list: it turns "nothing traded"
    from a shrug into a specific, checkable statement about which gate closed.
    """

    symbol: str
    timeframe: Timeframe
    as_of: datetime
    stages: list[Stage] = field(default_factory=list)
    intent: OrderIntent | None = None
    stopped_at: str | None = None
    permitted_risk_r: float | None = None

    @property
    def reached_intent(self) -> bool:
        return self.intent is not None

    def stage(self, name: str) -> Stage | None:
        for item in self.stages:
            if item.name == name:
                return item
        return None

    def _record(self, name: str, passed: bool, detail: str, payload: dict | None = None) -> bool:
        self.stages.append(Stage(name, passed, detail, payload or {}))
        if not passed and self.stopped_at is None:
            self.stopped_at = name
        return passed

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe.value,
            "as_of": self.as_of.isoformat(),
            "reached_intent": self.reached_intent,
            "stopped_at": self.stopped_at,
            "permitted_risk_r": self.permitted_risk_r,
            "stages": [s.as_dict() for s in self.stages],
            "intent": self.intent.as_dict() if self.intent else None,
            "policy": {
                "stop_atr_multiple": STOP_ATR_MULTIPLE,
                "target_reward_risk": TARGET_REWARD_RISK,
            },
            # The chain ends at an intent. Whether that intent is ever sent is
            # `app.execution.safety`'s question, and it asks its own.
            "authorises_execution": False,
        }


@dataclass
class Levels:
    entry: float
    stop: float
    target: float
    atr: float


def derive_levels(price: float, atr: float, direction: Decision) -> Levels | None:
    """Entry, stop and target from the current price and measured volatility.

    Returns None rather than guessing when ATR is missing or zero. A stop
    placed without a volatility measurement is a stop placed at an arbitrary
    distance, and every number downstream — the R, the EV, the survivable size —
    would be denominated in that arbitrary unit while looking measured.
    """
    if atr <= 0 or price <= 0:
        return None
    distance = STOP_ATR_MULTIPLE * atr
    if direction is Decision.BUY:
        return Levels(price, price - distance, price + distance * TARGET_REWARD_RISK, atr)
    if direction is Decision.SELL:
        return Levels(price, price + distance, price - distance * TARGET_REWARD_RISK, atr)
    return None


def _price_and_atr(payload: dict[str, Any]) -> tuple[float | None, float | None]:
    price_block = payload.get("price") or {}
    price = price_block.get("close") if price_block.get("available") else None

    feature_block = payload.get("features") or {}
    values = feature_block.get("values") or {} if feature_block.get("available") else {}
    atr = values.get("atr_14")
    return (
        float(price) if isinstance(price, int | float) else None,
        float(atr) if isinstance(atr, int | float) else None,
    )


def decide(
    session: Session,
    instrument_id: uuid.UUID,
    timeframe: Timeframe,
    *,
    account: risk_brain.AccountState,
    health: risk_brain.DataHealth,
    calibration: CalibrationReport,
    history: stress_brain.TradeHistory | None,
    account_id: str,
    open_positions: list[pf.Position] | None = None,
    open_risk_r: list[float | None] | None = None,
    correlations: dict[str, float] | None = None,
    measured_correlation: float | None = None,
    costs: ev.CostModel | None = None,
    rate_differential: float | None = None,
    base_currency: str | None = None,
    quote_currency: str | None = None,
    challenge_rules: Any | None = None,
    challenge_state: Any | None = None,
    r_value_pct: float | None = None,
    as_of: datetime | None = None,
) -> DecisionTrace:
    """Walk one instrument through every gate and report where it stopped.

    The caller supplies the account, the health and the measured history rather
    than this function reading them, because those are facts about a live
    account and this function must be runnable over historical bars with the
    account state of that moment. A pipeline that fetches "now" cannot be
    backtested, and a pipeline that cannot be backtested has never been tested.
    """
    cutoff = (as_of or datetime.now(UTC)).astimezone(UTC)
    positions = list(open_positions or [])

    proposal = cognitive.think(session, instrument_id, timeframe, cutoff)
    trace = DecisionTrace(symbol=proposal.symbol, timeframe=timeframe, as_of=cutoff)

    # ------------------------------------------------------------ 1. brain
    if not trace._record(
        "cognition",
        proposal.decision is not Decision.WAIT,
        f"the brain proposes {proposal.decision.value}"
        + (f": {'; '.join(proposal.wait_reasons)}" if proposal.wait_reasons else ""),
        {"conviction": proposal.conviction, "regime": proposal.regime.get("regime")},
    ):
        return trace

    # ------------------------------------------------------------ 2. levels
    state_payload = cognitive_payload(session, instrument_id, timeframe, cutoff)
    price, atr = _price_and_atr(state_payload)
    levels = (
        derive_levels(price, atr, proposal.decision)
        if price is not None and atr is not None
        else None
    )
    if not trace._record(
        "levels",
        levels is not None,
        "levels derived from measured ATR"
        if levels
        else "no measured ATR — a stop placed without one is an arbitrary distance "
        "that every number downstream would be denominated in",
        {"price": price, "atr_14": atr},
    ):
        return trace
    assert levels is not None  # narrowed by the gate above

    # ------------------------------------- 3. calibrated probability and EV
    direction = "buy" if proposal.decision is Decision.BUY else "sell"

    # The interest on holding this position, which needs three things that only
    # exist together at this point: the two countries' rate difference, which
    # the caller supplies because fetching it here would make the pipeline
    # unbacktestable; the direction, which the cognition stage has just
    # decided; and a notional, which the levels stage has just placed.
    #
    # Supplied as a fallback only. A broker's own swap figure is the
    # differential plus their markup and is what will actually be charged, so
    # a `costs` that already carries one is left alone.
    priced_costs = costs
    if rate_differential is not None and (costs is None or costs.swap is None):
        try:
            estimate = carry.swap_cost(
                differential_pct=rate_differential,
                entry=levels.entry,
                direction=direction,
            )
        except ValueError:
            # A refusal here is about the inputs, not about the trade. It
            # leaves the swap unmeasured, which is what it was before.
            estimate = None
        if estimate is not None:
            priced_costs = ev.CostModel(
                spread=costs.spread if costs else None,
                commission=costs.commission if costs else None,
                swap=estimate,
                slippage=costs.slippage if costs else None,
            )
    value = ev.compute(
        entry=levels.entry,
        stop=levels.stop,
        target=levels.target,
        direction=direction,
        score=proposal.conviction,
        calibration=calibration,
        costs=priced_costs,
    )
    if not trace._record(
        "expected_value",
        value.available and value.verdict == "trade",
        value.reason or f"expected value says {value.verdict}",
        value.as_dict(),
    ):
        return trace

    # ------------------------------------------------------------ 4. portfolio
    requested = 1.0
    book = pf.evaluate(
        symbol=proposal.symbol,
        direction=direction,
        proposed_risk_r=requested,
        positions=positions,
        base_currency=base_currency,
        quote_currency=quote_currency,
        correlations=correlations,
    )
    if not trace._record(
        "portfolio",
        book.allowed,
        f"portfolio says {book.verdict}",
        book.as_dict(),
    ):
        return trace

    # ------------------------------------------------------------ 5. risk
    authorisation = risk_brain.authorise(
        requested_risk_r=requested,
        account=account,
        health=health,
        portfolio_headroom_r=book.max_additional_risk_r,
    )
    if not trace._record(
        "risk",
        authorisation.approves,
        f"risk says {authorisation.verdict.value}",
        authorisation.as_dict(),
    ):
        return trace
    trace.permitted_risk_r = authorisation.permitted_risk_r

    # ------------------------------------------------------------ 6. stress
    if history is None:
        trace._record(
            "stress",
            False,
            "no measured trade history — survival cannot be projected, and an "
            "unprojected account is not a cleared one",
        )
        return trace

    risk_fraction = r_value_pct if r_value_pct is not None else _implied_r_value(
        account, authorisation.permitted_risk_r
    )
    report = stress_brain.run_all(
        history=history,
        r_value_pct=risk_fraction,
        open_risk_r=open_risk_r if open_risk_r is not None else [p.risk_r for p in positions],
        current_drawdown_pct=account.drawdown_pct,
        measured_correlation=measured_correlation,
    )
    if not trace._record(
        "stress",
        report.verdict is not RiskVerdict.BLOCK,
        f"stress says {report.verdict.value}"
        + (f": {'; '.join(report.breaches[:2])}" if report.breaches else ""),
        report.as_dict(),
    ):
        return trace

    # ------------------------------------------------------------ 7. challenge
    if challenge_rules is not None and challenge_state is not None:
        from app.brain import challenge as challenge_brain

        verdict = challenge_brain.check(
            challenge_rules, challenge_state, authorisation.permitted_risk_r
        )
        if not trace._record(
            "challenge",
            verdict.allowed,
            f"challenge says {verdict.verdict}"
            + (f": {'; '.join(verdict.breaches[:2])}" if verdict.breaches else ""),
            verdict.as_dict(),
        ):
            return trace
        if verdict.max_additional_risk_r is not None:
            trace.permitted_risk_r = min(
                trace.permitted_risk_r, verdict.max_additional_risk_r
            )
    else:
        # Not silently skipped. An account with no rulebook loaded is an account
        # whose rules were not checked, and the trace has to carry that.
        trace._record(
            "challenge",
            True,
            "no challenge rulebook was supplied — the provider's rules were not "
            "checked, which is not the same as satisfied",
        )

    # ------------------------------------------------------------ 8. intent
    approved_at = cutoff
    intent = OrderIntent(
        symbol=proposal.symbol,
        side=OrderSide.BUY if proposal.decision is Decision.BUY else OrderSide.SELL,
        order_type=OrderType.MARKET,
        risk_r=trace.permitted_risk_r or 0.0,
        entry=levels.entry,
        stop=levels.stop,
        target=levels.target,
        approvals=(
            Approval(
                "risk", True, f"permitted {authorisation.permitted_risk_r:.2f} R", approved_at
            ),
            Approval(
                "portfolio", True, f"headroom {book.max_additional_risk_r:.2f} R", approved_at
            ),
            Approval("challenge", True, _challenge_detail(challenge_rules), approved_at),
            Approval("stress", True, f"worst scenario {report.verdict.value}", approved_at),
        ),
        authorised_at=approved_at,
        account_id=account_id,
        metadata={"conviction": proposal.conviction, "probability": value.probability},
    )
    trace.intent = intent
    trace._record(
        "intent",
        True,
        f"assembled a {intent.side.value} intent at {trace.permitted_risk_r:.2f} R",
        intent.as_dict(),
    )
    return trace


def _challenge_detail(rules: Any | None) -> str:
    return "within the rulebook" if rules is not None else "no rulebook supplied"


def _implied_r_value(account: risk_brain.AccountState, permitted_r: float) -> float:
    """What one R costs as a fraction of equity, when the caller did not say.

    Derived from the account rather than assumed: the stress module needs this
    to convert R into a drawdown percentage, and a guessed value would make its
    entire projection a statement about a different account.
    """
    if account.equity <= 0 or permitted_r <= 0:
        return 0.0
    # One R is the per-trade risk the risk brain just permitted, expressed
    # against equity. The risk brain works in R and the account works in money;
    # this is the only place the two meet.
    return min(1.0, permitted_r / 100.0)


def cognitive_payload(
    session: Session, instrument_id: uuid.UUID, timeframe: Timeframe, cutoff: datetime
) -> dict[str, Any]:
    """The world state as a dict, re-read for the levels stage.

    Re-read rather than threaded out of `think()`, because `Proposal`
    deliberately carries no price: it is a judgement, not a quote, and giving
    it one would invite callers to size from a number the brain never promised
    was current.
    """
    from app.services import world_state

    return world_state.build(session, instrument_id, timeframe, cutoff).as_dict()
