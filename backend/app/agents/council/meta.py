"""Meta-brain v2: weigh by measured credibility, detect conflict, prefer WAIT.

- Weight = declared weight (versioned) x credibility factor (out-of-sample).
  Self-reported confidence is ignored for weighting.
- Not enough participating members -> WAIT (insufficient data).
- Strong directional members on both sides -> conflict; high conflict -> WAIT.
- An adversary or member objection downgrades a BUY/SELL to WAIT unless the
  weighted case is strong.
The verdict is a recommendation into a shadow log. It cannot authorise a
trade; the risk brain remains the only authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.council.analysts import NEUTRAL_BAND, Opinion
from app.agents.council.credibility import CredibilityBook
from app.agents.council.weights import WeightVersion

MIN_QUORUM = 2
CONFLICT_WAIT = 0.34
STRONG = 0.5


@dataclass(frozen=True)
class Verdict:
    direction: str
    score: float
    participating: int
    conflict: float
    conflicts: tuple[tuple[str, str], ...]
    objections: tuple[str, ...]
    reasons: tuple[str, ...]
    weights_version: int
    weights_used: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction, "score": round(self.score, 4),
            "participating": self.participating, "conflict": round(self.conflict, 4),
            "conflicts": [list(c) for c in self.conflicts],
            "objections": list(self.objections), "reasons": list(self.reasons),
            "weights_version": self.weights_version,
            "weights_used": {k: round(v, 4) for k, v in self.weights_used.items()},
            "authority": "advisory only - the risk brain decides",
        }


def aggregate(opinions: list[Opinion], weights: WeightVersion,
              book: CredibilityBook | None = None) -> Verdict:
    book = book or CredibilityBook()
    voting = [o for o in opinions if not o.abstained and o.member != "adversarial"]
    used = {o.member: weights.weights.get(o.member, 0.0) * book.factor(o.member)
            for o in voting}
    directional = [o for o in voting if used[o.member] > 0 and abs(o.score) >= NEUTRAL_BAND]
    objections = tuple(o.member for o in opinions if o.objection)
    reasons: list[str] = []

    if len(directional) < MIN_QUORUM:
        return Verdict("WAIT", 0.0, len(directional), 0.0, (), objections,
                       ("insufficient participating members",), weights.version, used)

    total = sum(used[o.member] for o in directional)
    score = sum(used[o.member] * o.score for o in directional) / total if total else 0.0

    strong_buy = [o.member for o in directional if o.score >= STRONG]
    strong_sell = [o.member for o in directional if o.score <= -STRONG]
    conflicts = tuple((b, s) for b in strong_buy for s in strong_sell)
    against = sum(used[o.member] for o in directional if (o.score > 0) != (score > 0))
    conflict = against / total if total else 0.0

    direction = "WAIT" if abs(score) < NEUTRAL_BAND else ("BUY" if score > 0 else "SELL")
    if conflict >= CONFLICT_WAIT or conflicts:
        reasons.append(f"conflict {conflict:.0%} between members")
        direction = "WAIT"
    if direction != "WAIT" and objections and abs(score) < STRONG:
        reasons.append("objection on a weak case: " + ", ".join(objections))
        direction = "WAIT"
    if direction != "WAIT":
        reasons.append(f"weighted score {score:+.2f}")
    return Verdict(direction, score, len(directional), conflict, conflicts, objections,
                   tuple(reasons), weights.version, used)
