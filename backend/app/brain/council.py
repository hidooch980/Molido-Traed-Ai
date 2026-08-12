"""AI Council (spec phase 15, §14).

Independent analysts, each looking at the same world state through one lens and
returning a structured opinion. The council does not decide anything; it
produces evidence for the layers above.

**These analysts are rule-based, not learned, and every output says so.** The
spec calls them AI agents, and one day some of them will be. Today each is a
small deterministic function over measurements that already exist. Labelling
them `method: "rule_based"` is not modesty — it is the difference between a
system whose limits are visible and one that quietly launders heuristics as
intelligence. A later learned analyst reports a different method, and the audit
trail shows exactly when the change happened.

**An analyst that cannot see its inputs abstains.** It does not return a
neutral 0.5. Abstention and neutrality are different claims: the first says "I
have nothing to add", the second says "I looked and it is balanced", and a
meta-brain that cannot tell them apart will average away its own blind spots.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.core.enums import Decision, Regime

METHOD = "rule_based"

# Scores run -1 (bearish) to +1 (bullish). Below this the reading is not worth
# acting on and is reported as neutral rather than as a weak direction.
NEUTRAL_BAND = 0.15


@dataclass
class Opinion:
    """One analyst's reading of one world state."""

    analyst: str
    abstained: bool
    score: float = 0.0
    confidence: float = 0.0
    reason_codes: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    method: str = METHOD
    version: int = 1

    @property
    def direction(self) -> Decision:
        if self.abstained or abs(self.score) < NEUTRAL_BAND:
            return Decision.WAIT
        return Decision.BUY if self.score > 0 else Decision.SELL

    def as_dict(self) -> dict[str, Any]:
        return {
            "analyst": self.analyst,
            "abstained": self.abstained,
            "score": round(self.score, 4),
            "confidence": round(self.confidence, 4),
            "direction": self.direction.value,
            "reason_codes": self.reason_codes,
            "evidence": self.evidence,
            "method": self.method,
            "version": self.version,
        }


def _abstain(name: str, why: str) -> Opinion:
    return Opinion(analyst=name, abstained=True, reason_codes=["no_input"], evidence=[why])


AnalystFn = Callable[[dict], Opinion]
_REGISTRY: dict[str, AnalystFn] = {}


def analyst(name: str) -> Callable[[AnalystFn], AnalystFn]:
    def wrap(fn: AnalystFn) -> AnalystFn:
        _REGISTRY[name] = fn
        return fn

    return wrap


def names() -> list[str]:
    return sorted(_REGISTRY)


def _features(state: dict) -> dict | None:
    block = state.get("features", {})
    return block.get("values") if block.get("available") else None


def _memory(state: dict) -> dict | None:
    block = state.get("memory", {})
    return block.get("horizons") if block.get("available") else None


# ----------------------------------------------------------------- analysts
@analyst("trend")
def trend_analyst(state: dict) -> Opinion:
    """Reads the short and medium horizons, and penalises disagreement."""
    memory = _memory(state)
    if not memory:
        return _abstain("trend", "market memory unavailable")

    short = memory.get("short", {})
    medium = memory.get("medium", {})
    if not short.get("available"):
        return _abstain("trend", "short horizon has too little history")

    strength = short.get("trend_strength") or 0.0
    score = max(-1.0, min(1.0, strength / 3.0))
    evidence = [f"short-horizon trend {short.get('trend')} (strength {strength:.2f})"]
    codes = [f"trend_{short.get('trend')}"]
    confidence = min(1.0, abs(strength) / 3.0)

    if medium.get("available") and medium.get("trend") in ("up", "down"):
        if medium["trend"] != short.get("trend") and short.get("trend") in ("up", "down"):
            # Conflicting horizons cut confidence rather than flipping the
            # score: the short-term reading is still what it is.
            confidence *= 0.5
            codes.append("horizon_conflict")
            evidence.append(f"medium horizon disagrees ({medium['trend']})")
        else:
            confidence = min(1.0, confidence * 1.2)
            codes.append("horizon_aligned")

    return Opinion("trend", False, score, confidence, codes, evidence)


@analyst("structure")
def structure_analyst(state: dict) -> Opinion:
    """Where price sits in its recent range."""
    features = _features(state)
    if not features or features.get("position_in_range_20") is None:
        return _abstain("structure", "range position unavailable")

    position = features["position_in_range_20"]
    # Distance from the middle, signed. Near the top is bullish structure in a
    # trend and stretched in a range — which one it is, is the regime
    # analyst's job, not this one's.
    score = (position - 0.5) * 2
    return Opinion(
        "structure",
        False,
        max(-1.0, min(1.0, score)),
        min(1.0, abs(score)),
        ["range_high" if position > 0.65 else "range_low" if position < 0.35 else "mid_range"],
        [f"price at {position:.0%} of its 20-bar range"],
    )


@analyst("momentum")
def momentum_analyst(state: dict) -> Opinion:
    features = _features(state)
    if not features or features.get("rsi_14") is None:
        return _abstain("momentum", "RSI unavailable")

    rsi = features["rsi_14"]
    score = (rsi - 50) / 50
    codes = ["overbought" if rsi >= 70 else "oversold" if rsi <= 30 else "momentum_neutral"]
    return Opinion(
        "momentum",
        False,
        max(-1.0, min(1.0, score)),
        min(1.0, abs(score) * 1.5),
        codes,
        [f"RSI(14) at {rsi:.0f}"],
    )


@analyst("volatility")
def volatility_analyst(state: dict) -> Opinion:
    """Directionless by construction.

    Volatility says how large a move is, never which way. This analyst always
    scores zero and carries its reading in confidence and reason codes — a
    volatility analyst that voted a direction would be inventing one.
    """
    features = _features(state)
    dna = state.get("dna", {})
    if not features or features.get("atr_14_pct") is None:
        return _abstain("volatility", "ATR unavailable")

    atr = features["atr_14_pct"]
    codes = ["volatility_measured"]
    evidence = [f"ATR% {atr:.5f}"]

    if dna.get("available"):
        profile = dna.get("profiles", {}).get("volatility", {}).get("data", {})
        percentiles = profile.get("bar_range_pct", {})
        p75, p25 = percentiles.get("p75"), percentiles.get("p25")
        if p75 is not None and atr >= p75:
            codes.append("volatility_expanded")
            evidence.append("above this instrument's own p75")
        elif p25 is not None and atr <= p25:
            codes.append("volatility_compressed")
            evidence.append("below this instrument's own p25")

    return Opinion("volatility", False, 0.0, 0.4, codes, evidence)


@analyst("session")
def session_analyst(state: dict) -> Opinion:
    """Liquidity context. Also directionless — it gates, it does not vote."""
    block = state.get("session", {})
    if not block.get("available"):
        return _abstain("session", "session state unavailable")

    active = [s for s in block.get("active", []) if s != "off"]
    is_open = block.get("is_open", False)
    codes = ["market_open" if is_open else "market_closed"]
    if not active:
        codes.append("thin_liquidity")

    return Opinion(
        "session",
        False,
        0.0,
        0.6 if active else 0.2,
        codes,
        [f"sessions active: {', '.join(active) or 'none'}"],
    )


@analyst("regime")
def regime_analyst(state: dict) -> Opinion:
    regime = state.get("regime", {})
    if not regime or regime.get("regime") in (None, Regime.UNCERTAIN.value):
        return _abstain("regime", regime.get("reason") or "regime is uncertain")

    name = regime["regime"]
    confidence = regime.get("confidence", 0.0)
    score = {
        Regime.TREND_UP.value: 0.6,
        Regime.TREND_DOWN.value: -0.6,
    }.get(name, 0.0)

    return Opinion(
        "regime",
        False,
        score,
        confidence,
        [f"regime_{name}"],
        regime.get("evidence", [])[:3],
    )


@analyst("history")
def history_analyst(state: dict) -> Opinion:
    """What happened after similar states — the only analyst grounded in outcomes."""
    similar = state.get("similarity", {})
    if not similar or not similar.get("sufficient"):
        return _abstain(
            "history", similar.get("reason") or "no comparable history"
        )

    outcome = similar.get("outcome", {})
    if not outcome.get("available"):
        return _abstain("history", "matched episodes carry no outcome")

    share = outcome.get("positive_share")
    if share is None:
        return _abstain("history", "outcome share unavailable")

    score = (share - 0.5) * 2
    uncertainty = similar.get("uncertainty", {})
    spread = uncertainty.get("outcome_stdev")

    confidence = min(1.0, outcome.get("count", 0) / 100)
    evidence = [f"{outcome['count']} similar episodes, {share:.0%} closed higher"]
    codes = ["history_bullish" if score > 0 else "history_bearish"]

    # Wide disagreement among the matches is a reason to trust the central
    # tendency less, not a reason to hide it.
    if spread is not None and abs(score) > 0 and spread > abs(
        outcome.get("median_forward_return") or 0
    ) * 3:
        confidence *= 0.5
        codes.append("history_disagrees")
        evidence.append("matched outcomes disagree widely")

    return Opinion("history", False, max(-1.0, min(1.0, score)), confidence, codes, evidence)


@analyst("data_quality")
def quality_analyst(state: dict) -> Opinion:
    """A veto-shaped analyst: it never votes direction, only trustworthiness."""
    quality = state.get("quality", {})
    freshness = state.get("freshness", {})
    codes: list[str] = []
    evidence: list[str] = []
    confidence = 1.0

    if not quality.get("available"):
        return _abstain("data_quality", "dataset has not been evaluated")

    if not quality.get("any_training_eligible", False):
        codes.append("data_not_training_eligible")
        evidence.append("no dataset for this instrument passes the quality gate")
        confidence = 0.3

    if freshness.get("available") and freshness.get("stale"):
        codes.append("stale_data")
        evidence.append(f"newest bar is {freshness['age_seconds']:.0f}s old")
        confidence = 0.0

    if not codes:
        codes.append("data_ok")
        evidence.append("quality gate passed and data is fresh")

    return Opinion("data_quality", False, 0.0, confidence, codes, evidence)


def convene(state: dict) -> list[Opinion]:
    """Run every analyst over one world state."""
    return [_REGISTRY[name](state) for name in names()]
