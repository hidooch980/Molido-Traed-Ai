"""Meta-brain (spec phase 16, §15) and adversarial check (phase 17, §16).

The meta-brain weighs the council rather than counting it, measures how much
the analysts disagree, and decides whether the reading is trustworthy enough to
pass on. The adversary then tries to knock it down.

**Weights are declared constants, not learned.** The spec calls for weights
validated per regime and versioned. Learning them needs outcome data this
system has not accumulated, so the table below is an explicit, reviewable
starting point with a version number — not a trained artefact wearing one. When
the learning lab produces real weights, the version changes and the audit trail
shows it.

**Disagreement suppresses.** The spec is direct: strong disagreement should
normally reduce risk or produce WAIT. Averaging opposing analysts into a
confident middle is the failure this guards against, and it is the most common
way an ensemble becomes worse than its parts.

**The adversary is not a formality.** It is given the same evidence and asked
to argue the other side. When it finds enough, the proposal is downgraded — a
mechanism that only earns its place if it is allowed to win.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from app.brain.council import NEUTRAL_BAND, Opinion
from app.core.enums import Decision, Regime

WEIGHTS_VERSION = 1

# How much each analyst counts. Directionless analysts (volatility, session,
# data quality) hold zero weight in the direction vote by design — they act
# through confidence and through the adversary instead.
BASE_WEIGHTS: dict[str, float] = {
    "trend": 1.0,
    "structure": 0.6,
    "momentum": 0.6,
    "regime": 1.0,
    "history": 1.2,
    "volatility": 0.0,
    "session": 0.0,
    "data_quality": 0.0,
}

# Per-regime adjustments. In a range, trend-following analysts are the ones
# most likely to be wrong; in a trend, mean-reversion signals are.
REGIME_ADJUSTMENTS: dict[str, dict[str, float]] = {
    Regime.RANGE.value: {"trend": 0.5, "momentum": 1.2, "structure": 1.2},
    Regime.TREND_UP.value: {"trend": 1.3, "momentum": 0.8},
    Regime.TREND_DOWN.value: {"trend": 1.3, "momentum": 0.8},
    Regime.HIGH_VOLATILITY.value: {"history": 0.7, "structure": 0.7},
    Regime.BREAKOUT.value: {"structure": 1.3, "trend": 1.2},
    Regime.REVERSAL.value: {"trend": 0.6, "history": 1.3},
}

# Above this, the council is split enough that the reading is suppressed.
MAX_DISAGREEMENT = 0.55
# A direction needs at least this weighted score to be proposed at all.
MIN_CONVICTION = 0.20


@dataclass
class MetaVerdict:
    decision: Decision
    conviction: float
    disagreement: float
    weights_version: int = WEIGHTS_VERSION
    suppressed: bool = False
    suppression_reason: str | None = None
    contributing: dict[str, float] = field(default_factory=dict)
    abstained: list[str] = field(default_factory=list)
    supporting: list[str] = field(default_factory=list)
    contradicting: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "conviction": round(self.conviction, 4),
            "disagreement": round(self.disagreement, 4),
            "weights_version": self.weights_version,
            "suppressed": self.suppressed,
            "suppression_reason": self.suppression_reason,
            "contributing": {k: round(v, 4) for k, v in self.contributing.items()},
            "abstained": self.abstained,
            "supporting_evidence": self.supporting,
            "contradicting_evidence": self.contradicting,
        }


def weights_for(regime: str | None) -> dict[str, float]:
    weights = dict(BASE_WEIGHTS)
    for analyst, factor in REGIME_ADJUSTMENTS.get(regime or "", {}).items():
        weights[analyst] = weights.get(analyst, 0.0) * factor
    return weights


def deliberate(opinions: list[Opinion], regime: str | None = None) -> MetaVerdict:
    """Weigh the council and decide whether its reading survives."""
    weights = weights_for(regime)
    abstained = [o.analyst for o in opinions if o.abstained]
    voting = [o for o in opinions if not o.abstained and weights.get(o.analyst, 0.0) > 0]

    if not voting:
        return MetaVerdict(
            Decision.WAIT,
            0.0,
            0.0,
            suppressed=True,
            suppression_reason="no analyst with weight produced a reading",
            abstained=abstained,
        )

    contributions: dict[str, float] = {}
    total_weight = 0.0
    weighted_sum = 0.0
    for o in voting:
        w = weights[o.analyst] * max(o.confidence, 0.0)
        contributions[o.analyst] = w * o.score
        weighted_sum += w * o.score
        total_weight += w

    conviction = weighted_sum / total_weight if total_weight > 0 else 0.0

    # Disagreement is the spread of directional opinions, not of the weighted
    # sum: two analysts at +1 and -1 average to zero, and only the spread
    # reveals that the zero is a fight rather than a consensus.
    directional = [o.score for o in voting if abs(o.score) >= NEUTRAL_BAND]
    disagreement = statistics.pstdev(directional) if len(directional) > 1 else 0.0

    supporting = [e for o in voting if o.score * conviction > 0 for e in o.evidence]
    contradicting = [e for o in voting if o.score * conviction < 0 for e in o.evidence]

    verdict = MetaVerdict(
        decision=Decision.WAIT,
        conviction=conviction,
        disagreement=disagreement,
        contributing=contributions,
        abstained=abstained,
        supporting=supporting[:6],
        contradicting=contradicting[:6],
    )

    if disagreement > MAX_DISAGREEMENT:
        verdict.suppressed = True
        verdict.suppression_reason = (
            f"analysts disagree ({disagreement:.2f} spread, limit {MAX_DISAGREEMENT})"
        )
        return verdict

    if abs(conviction) < MIN_CONVICTION:
        verdict.suppressed = True
        verdict.suppression_reason = (
            f"conviction {abs(conviction):.2f} below the {MIN_CONVICTION} floor"
        )
        return verdict

    verdict.decision = Decision.BUY if conviction > 0 else Decision.SELL
    return verdict


# ------------------------------------------------------------- adversary
@dataclass
class Challenge:
    code: str
    severity: str  # "note" | "concern" | "blocking"
    detail: str


@dataclass
class AdversarialResult:
    challenges: list[Challenge] = field(default_factory=list)
    verdict: str = "clear"  # clear | reduce | block

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "challenges": [
                {"code": c.code, "severity": c.severity, "detail": c.detail}
                for c in self.challenges
            ],
        }


def challenge(
    verdict: MetaVerdict, opinions: list[Opinion], state: dict
) -> AdversarialResult:
    """Argue against the proposal (spec §16).

    Deliberately adversarial: it looks only for reasons the trade is wrong.
    A balanced reviewer here would duplicate the meta-brain; the value is in
    having something whose only job is to find the hole.
    """
    result = AdversarialResult()
    by_name = {o.analyst: o for o in opinions}

    quality = by_name.get("data_quality")
    if quality and "stale_data" in quality.reason_codes:
        result.challenges.append(
            Challenge("stale_data", "blocking", "the newest bar is stale")
        )
    if quality and "data_not_training_eligible" in quality.reason_codes:
        result.challenges.append(
            Challenge(
                "poor_data_quality",
                "concern",
                "this dataset does not pass the quality gate",
            )
        )

    session = by_name.get("session")
    if session and "market_closed" in session.reason_codes:
        result.challenges.append(
            Challenge("market_closed", "blocking", "the market is not trading")
        )
    if session and "thin_liquidity" in session.reason_codes:
        result.challenges.append(
            Challenge("thin_liquidity", "concern", "no major session is active")
        )

    volatility = by_name.get("volatility")
    if volatility and "volatility_expanded" in volatility.reason_codes:
        result.challenges.append(
            Challenge(
                "volatility_expanded",
                "concern",
                "volatility is above this instrument's own p75, so stops are wider "
                "than usual for the same conviction",
            )
        )

    if verdict.disagreement > MAX_DISAGREEMENT * 0.7:
        result.challenges.append(
            Challenge(
                "council_split",
                "concern",
                f"the council is close to its disagreement limit ({verdict.disagreement:.2f})",
            )
        )

    history = by_name.get("history")
    if history and history.abstained:
        result.challenges.append(
            Challenge(
                "no_historical_support",
                "concern",
                "no comparable history: this reading rests on indicators alone",
            )
        )
    elif history and not history.abstained:
        if history.score * verdict.conviction < 0:
            result.challenges.append(
                Challenge(
                    "history_contradicts",
                    "blocking",
                    "similar past states moved the other way",
                )
            )

    momentum = by_name.get("momentum")
    if momentum and verdict.decision == Decision.BUY:
        if "overbought" in momentum.reason_codes:
            result.challenges.append(
                Challenge("buying_overbought", "concern", "RSI is already extended")
            )
    if momentum and verdict.decision == Decision.SELL:
        if "oversold" in momentum.reason_codes:
            result.challenges.append(
                Challenge("selling_oversold", "concern", "RSI is already depressed")
            )

    if len(verdict.abstained) >= 3:
        result.challenges.append(
            Challenge(
                "thin_evidence",
                "concern",
                f"{len(verdict.abstained)} analysts had nothing to say",
            )
        )

    blocking = [c for c in result.challenges if c.severity == "blocking"]
    concerns = [c for c in result.challenges if c.severity == "concern"]

    if blocking:
        result.verdict = "block"
    elif len(concerns) >= 2:
        result.verdict = "reduce"

    return result
