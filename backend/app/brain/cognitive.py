"""Cognitive brain (spec phase 14, §13) with counterfactuals (phase 18, §17).

The layered pipeline the spec describes:

    perception -> context -> memory -> reasoning -> scenarios ->
    prediction -> uncertainty -> risk awareness -> decision

Each stage is a real step here, and the output records what happened at every
one of them, because the spec also requires a decision to be auditable and
replayable.

**The brain proposes; it does not authorize.** Its output is a proposal with a
direction and a rationale. Position size, risk limits and the final yes/no
belong to the risk brain (phase 23), which does not exist yet — so this module
deliberately has no way to express "trade this much". Building that here would
put sizing inside the layer that is supposed to be argued with.

**WAIT is the default, not the failure case.** Every gate below returns WAIT
when it is not satisfied, and the spec's first principle is that insufficient
evidence means WAIT. A brain that has to be talked out of trading is the wrong
shape.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.brain import council, meta
from app.core.enums import Decision, Timeframe
from app.core.logging import get_logger
from app.services import regime as regime_service
from app.services import similarity, world_state

log = get_logger(__name__)

BRAIN_VERSION = 1


@dataclass
class Scenario:
    """One alternative the brain considered (spec §17)."""

    name: str
    description: str
    preferred: bool = False
    rationale: str = ""


@dataclass
class Proposal:
    instrument_id: uuid.UUID
    symbol: str
    timeframe: Timeframe
    as_of: datetime
    decision: Decision
    conviction: float
    brain_version: int = BRAIN_VERSION

    regime: dict[str, Any] = field(default_factory=dict)
    council: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    adversarial: dict[str, Any] = field(default_factory=dict)
    scenarios: list[Scenario] = field(default_factory=list)
    invalidation: str | None = None
    uncertainty: dict[str, Any] = field(default_factory=dict)
    wait_reasons: list[str] = field(default_factory=list)
    stages: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": str(self.instrument_id),
            "symbol": self.symbol,
            "timeframe": self.timeframe.value,
            "as_of": self.as_of.isoformat(),
            "decision": self.decision.value,
            "conviction": round(self.conviction, 4),
            "brain_version": self.brain_version,
            # No position size, no risk allocation: authorising a trade is the
            # risk brain's job and it does not exist yet.
            "authorises_execution": False,
            "regime": self.regime,
            "council": self.council,
            "meta": self.meta,
            "adversarial": self.adversarial,
            "scenarios": [
                {
                    "name": s.name,
                    "description": s.description,
                    "preferred": s.preferred,
                    "rationale": s.rationale,
                }
                for s in self.scenarios
            ],
            "invalidation": self.invalidation,
            "uncertainty": self.uncertainty,
            "wait_reasons": self.wait_reasons,
            "stages": self.stages,
        }


def think(
    session: Session,
    instrument_id: uuid.UUID,
    timeframe: Timeframe,
    as_of: datetime | None = None,
) -> Proposal:
    """Run the full pipeline and return a proposal."""
    cutoff = (as_of or datetime.now(UTC)).astimezone(UTC)
    stages: list[str] = []

    # --- perception + context ---------------------------------------------
    state = world_state.build(session, instrument_id, timeframe, cutoff)
    payload = state.as_dict()
    stages.append("perception")

    proposal = Proposal(
        instrument_id=instrument_id,
        symbol=state.symbol,
        timeframe=timeframe,
        as_of=cutoff,
        decision=Decision.WAIT,
        conviction=0.0,
        stages=stages,
    )

    if not payload.get("price", {}).get("available"):
        proposal.wait_reasons.append("no price is knowable at this instant")
        return proposal

    # --- regime -----------------------------------------------------------
    regime_result = regime_service.classify(session, instrument_id, timeframe, cutoff)
    payload["regime"] = regime_result.as_dict()
    proposal.regime = payload["regime"]
    stages.append("context")

    # --- memory: what happened after states like this ---------------------
    try:
        similar = similarity.find_similar(session, instrument_id, timeframe, cutoff)
        payload["similarity"] = similar.as_payload()
    except Exception as exc:  # noqa: BLE001 - a missing memory is not a crash
        log.warning("cognitive.similarity_failed", error=str(exc))
        payload["similarity"] = {"sufficient": False, "reason": str(exc)}
    stages.append("memory")

    # --- reasoning: the council -------------------------------------------
    opinions = council.convene(payload)
    proposal.council = [o.as_dict() for o in opinions]
    stages.append("reasoning")

    verdict = meta.deliberate(opinions, regime_result.regime.value)
    proposal.meta = verdict.as_dict()

    # --- adversarial ------------------------------------------------------
    adversary = meta.challenge(verdict, opinions, payload)
    proposal.adversarial = adversary.as_dict()
    stages.append("scenarios")

    # --- counterfactuals (spec §17) ---------------------------------------
    proposal.scenarios = _scenarios(verdict, adversary)

    # --- uncertainty ------------------------------------------------------
    proposal.uncertainty = {
        "council_disagreement": round(verdict.disagreement, 4),
        "analysts_abstained": len(verdict.abstained),
        "regime_confidence": regime_result.confidence,
        "historical_support": payload["similarity"].get("sufficient", False),
        # Deliberately no probability: nothing here is calibrated, and phase 20
        # measures calibration rather than asserting it.
        "probability_available": False,
        "probability_reason": "no calibrated model exists yet (phase 20+)",
    }
    stages.append("uncertainty")

    # --- risk awareness and decision --------------------------------------
    stages.append("risk_awareness")

    if verdict.suppressed:
        proposal.wait_reasons.append(verdict.suppression_reason or "suppressed")
    if adversary.verdict == "block":
        blocking = [c.detail for c in adversary.challenges if c.severity == "blocking"]
        proposal.wait_reasons.extend(blocking)

    if not proposal.wait_reasons:
        proposal.decision = verdict.decision
        proposal.conviction = abs(verdict.conviction)
        if adversary.verdict == "reduce":
            # The adversary cannot flip the direction, but it can take the
            # conviction down — which is what the risk layer will read.
            proposal.conviction *= 0.5
            proposal.scenarios.append(
                Scenario(
                    "reduced_conviction",
                    "Proceed at lower conviction",
                    True,
                    "the adversary raised concerns that do not block but do weaken it",
                )
            )
        proposal.invalidation = _invalidation(payload, verdict.decision)

    stages.append("decision")
    proposal.stages = stages
    return proposal


def _scenarios(verdict: meta.MetaVerdict, adversary: meta.AdversarialResult) -> list[Scenario]:
    """Alternatives the brain weighed, including doing nothing.

    The spec asks for the best *risk-adjusted* choice rather than the highest
    prediction, and no-trade is always on the list — a comparison that omits it
    can only ever recommend action.
    """
    acting = not verdict.suppressed and adversary.verdict != "block"
    return [
        Scenario(
            "no_trade",
            "Take no position",
            preferred=not acting,
            rationale=(
                verdict.suppression_reason
                or "; ".join(c.detail for c in adversary.challenges if c.severity == "blocking")
                or "available whenever the evidence does not justify risk"
            ),
        ),
        Scenario(
            "act_now",
            f"Act on the {verdict.decision.value} reading",
            preferred=acting,
            rationale=(
                f"conviction {abs(verdict.conviction):.2f} with "
                f"{verdict.disagreement:.2f} disagreement"
            ),
        ),
        Scenario(
            "wait_for_confirmation",
            "Wait for the next bar to confirm",
            preferred=False,
            rationale="cheaper than being wrong when the council is not unanimous",
        ),
    ]


def _invalidation(payload: dict, decision: Decision) -> str:
    """What would prove this reading wrong.

    Stated in words rather than as a price, because a price level implies a
    stop, and a stop is a risk decision this layer is not allowed to make.
    """
    price = payload.get("price", {})
    close = price.get("close")
    if close is None:
        return "a close that reverses the structure this reading rests on"
    if decision == Decision.BUY:
        return (
            f"a close back below the recent range low would invalidate this "
            f"(reading taken at {close})"
        )
    return (
        f"a close back above the recent range high would invalidate this "
        f"(reading taken at {close})"
    )
