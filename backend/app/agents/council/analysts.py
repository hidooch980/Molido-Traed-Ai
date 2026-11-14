"""Six council members the existing council lacks. Abstain first.

Each reads one block of a `world` dict and returns an `Opinion`. A missing or
malformed block is an abstention, never a neutral 0.0: "I could not see" and
"I looked and it is balanced" are different claims. Scores run -1 (sell) to
+1 (buy). `confidence` describes data coverage only - the meta-brain does not
use it to weight anyone.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

NEUTRAL_BAND = 0.15


@dataclass(frozen=True)
class Opinion:
    member: str
    abstained: bool
    score: float = 0.0
    confidence: float = 0.0
    evidence: tuple[str, ...] = field(default_factory=tuple)
    objection: bool = False  # adversary only: "the case is weak"

    @property
    def direction(self) -> str:
        if self.abstained or abs(self.score) < NEUTRAL_BAND:
            return "WAIT"
        return "BUY" if self.score > 0 else "SELL"

    def as_dict(self) -> dict[str, Any]:
        return {"member": self.member, "abstained": self.abstained,
                "score": round(self.score, 4), "confidence": round(self.confidence, 4),
                "direction": self.direction, "evidence": list(self.evidence),
                "objection": self.objection}


def abstain(member: str, why: str) -> Opinion:
    return Opinion(member, True, evidence=(why,))


def _num(block: Any, key: str) -> float | None:
    if not isinstance(block, dict):
        return None
    value = block.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _clip(x: float) -> float:
    return max(-1.0, min(1.0, x))


def macro(world: dict) -> Opinion:
    """Policy-rate differential base minus quote, in percentage points."""
    diff = _num(world.get("macro"), "rate_differential")
    if diff is None:
        return abstain("macro", "no policy-rate differential")
    return Opinion("macro", False, _clip(diff / 4.0), 0.5,
                   (f"rate differential {diff:+.2f}pp",))


def news(world: dict) -> Opinion:
    """Directionless: a near high-impact event says stand aside."""
    minutes = _num(world.get("news"), "minutes_to_high_impact")
    if minutes is None:
        return abstain("news", "no economic calendar data")
    near = abs(minutes) <= 30
    return Opinion("news", False, 0.0, 0.8 if near else 0.4,
                   (f"high-impact event in {minutes:+.0f} min" + (" - stand aside" if near
                                                                    else ""),),
                   objection=near)


def sentiment(world: dict) -> Opinion:
    """Contrarian on crowding: COT speculative net-long share, 0..1."""
    share = _num(world.get("sentiment"), "speculative_net_long_share")
    if share is None or not 0.0 <= share <= 1.0:
        return abstain("sentiment", "no public positioning data")
    crowd = (share - 0.5) * 2
    if abs(crowd) < 0.5:
        return Opinion("sentiment", False, 0.0, 0.3, (f"positioning {share:.0%} not crowded",))
    return Opinion("sentiment", False, _clip(-crowd * 0.6), 0.4,
                   (f"speculators {share:.0%} long - crowded, contrarian",))


def quant(world: dict) -> Opinion:
    """Mean reversion on a price z-score against its own rolling mean."""
    z = _num(world.get("quant"), "zscore")
    if z is None:
        return abstain("quant", "no z-score")
    if abs(z) < 1.0:
        return Opinion("quant", False, 0.0, 0.3, (f"z {z:+.2f} inside band",))
    return Opinion("quant", False, _clip(-z / 3.0), 0.5, (f"z {z:+.2f} stretched",))


def execution(world: dict) -> Opinion:
    """Directionless cost check: spread as a share of ATR."""
    ratio = _num(world.get("execution"), "spread_to_atr")
    if ratio is None or ratio < 0:
        return abstain("execution", "no spread/ATR")
    costly = ratio > 0.15
    return Opinion("execution", False, 0.0, 0.6,
                   (f"spread is {ratio:.0%} of ATR" + (" - too costly" if costly else ""),),
                   objection=costly)


MEMBERS: dict[str, Callable[[dict], Opinion]] = {
    "macro": macro, "news": news, "sentiment": sentiment, "quant": quant,
    "execution": execution,
}


def adversary(opinions: list[Opinion]) -> Opinion:
    """Argue against the majority with the minority's own evidence."""
    votes = [o for o in opinions if o.direction in ("BUY", "SELL")]
    if not votes:
        return abstain("adversarial", "no directional case to attack")
    buys = sum(1 for o in votes if o.direction == "BUY")
    majority = "BUY" if buys * 2 >= len(votes) else "SELL"
    against = [o for o in votes if o.direction != majority]
    objections = [o for o in opinions if o.objection]
    weak = len(against) * 3 >= len(votes) or bool(objections)
    reasons = tuple(f"{o.member} says {o.direction}" for o in against) + tuple(
        f"{o.member} objects" for o in objections)
    sign = -1.0 if majority == "BUY" else 1.0
    return Opinion("adversarial", False, sign * (0.5 if weak else 0.1), 0.5,
                   reasons or ("no counter-evidence found",), objection=weak)


def convene(world: dict) -> list[Opinion]:
    opinions = [fn(world) for fn in MEMBERS.values()]
    return [*opinions, adversary(opinions)]
