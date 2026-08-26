"""Expected value (spec phase 21, §20).

EV is the number that decides whether a trade is worth taking, and it is the
easiest number in the whole system to fake. The formula is trivial:

    EV = p · reward − (1 − p) · risk − costs

Everything hard is in `p` and in `costs`.

**`p` must be a calibrated probability, or there is no EV.** Every layer below
produces a confidence-shaped number — a council conviction, a regime margin, a
similarity share — and none of them is a probability until phase 20's
calibration says so. Substituting conviction for probability is how a system
convinces itself that a coin flip is a 70% edge. `compute()` therefore refuses
to return a number when the score has not been calibrated: `available = false`
with the reason, not an optimistic guess.

**Costs must be measured, and the unmeasured ones must be named.** Spread is
observable in the bars. Commission and swap are broker facts, present only when
the operator has configured the broker symbol. Slippage and latency need real
fills, which will not exist until phase 25. An EV that silently omits them is
optimistic by exactly the amount it omitted — so every result carries
`unmeasured_costs`, and a consumer that ignores that list is choosing to.

The spec's rule closes the loop: **insufficient EV means WAIT.** Not "small
position", not "trade it carefully". WAIT.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.brain.calibration import CalibrationReport, to_probability

# An edge smaller than this, expressed in R (multiples of the amount risked),
# is inside the noise of the cost estimate itself and is treated as no edge.
MIN_EV_R = 0.05

# Reward-to-risk below this is refused regardless of probability. A 0.2 R:R
# trade needs an implausibly high hit rate to break even, and the hit rate is
# exactly the number least likely to be trustworthy.
MIN_REWARD_RISK = 0.5


@dataclass
class CostModel:
    """What a round trip actually costs, in price units.

    Every field is optional and defaults to unknown rather than zero. A missing
    commission is not a free trade; it is an unmeasured one, and the difference
    matters when the edge is thin.
    """

    spread: float | None = None
    commission: float | None = None
    #: Signed, unlike everything else here. See `total`.
    swap: float | None = None
    slippage: float | None = None

    def total(self) -> tuple[float, list[str]]:
        """(known cost, names of the costs that are not known).

        **Swap keeps its sign; everything else is taken as a magnitude.**
        Spread, commission and slippage are money leaving under every
        circumstance, so the direction they are supplied in says nothing and
        `abs` protects the sum from a sign convention somebody got backwards.

        Carry is not like that. Holding a currency that pays more than the one
        it is quoted against is *paid* for, every night, and taking the
        absolute value of that turns a position which earns interest into one
        that is charged it - an error of twice the carry, pointing the wrong
        way, and it lands hardest on exactly the trades where the carry is
        large enough to matter.
        """
        known = 0.0
        missing: list[str] = []
        for name in ("spread", "commission", "slippage"):
            value = getattr(self, name)
            if value is None:
                missing.append(name)
            else:
                known += abs(value)

        if self.swap is None:
            missing.append("swap")
        else:
            known += self.swap

        return known, missing


@dataclass
class EVResult:
    available: bool
    reason: str | None = None

    probability: float | None = None
    reward: float | None = None
    risk: float | None = None
    reward_risk: float | None = None
    costs: float | None = None
    unmeasured_costs: list[str] = field(default_factory=list)

    expected_value: float | None = None
    expected_value_r: float | None = None
    breakeven_probability: float | None = None
    verdict: str = "wait"
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        if not self.available:
            return {"available": False, "reason": self.reason, "verdict": "wait"}
        return {
            "available": True,
            "probability": self.probability,
            "reward": self.reward,
            "risk": self.risk,
            "reward_risk": self.reward_risk,
            "costs": self.costs,
            "unmeasured_costs": self.unmeasured_costs,
            "expected_value": self.expected_value,
            "expected_value_r": self.expected_value_r,
            "breakeven_probability": self.breakeven_probability,
            "verdict": self.verdict,
            "notes": self.notes,
        }


def _unavailable(reason: str) -> EVResult:
    return EVResult(available=False, reason=reason, verdict="wait")


def breakeven_probability(reward: float, risk: float, costs: float) -> float | None:
    """The hit rate this trade needs just to break even.

    Reported alongside EV because it is the more honest of the two: it says
    nothing about the model and everything about the trade's shape. A setup
    needing 68% to break even is a bad setup no matter how confident anything
    upstream feels.
    """
    denominator = reward + risk
    if denominator <= 0:
        return None
    return (risk + costs) / denominator


def compute(
    *,
    entry: float,
    stop: float,
    target: float,
    score: float,
    calibration: CalibrationReport,
    costs: CostModel | None = None,
    direction: str = "buy",
) -> EVResult:
    """Expected value for one trade candidate.

    `score` is a raw confidence from an upstream layer; it becomes a
    probability only if `calibration` says that source has earned it.
    """
    if direction not in ("buy", "sell"):
        return _unavailable(f"unknown direction {direction!r}")
    if entry <= 0:
        return _unavailable("entry price must be positive")

    # Distances are taken from the actual levels rather than assumed, so an
    # inverted stop or target is caught here instead of silently producing a
    # negative "risk" that flips the maths.
    if direction == "buy":
        risk = entry - stop
        reward = target - entry
    else:
        risk = stop - entry
        reward = entry - target

    if risk <= 0:
        return _unavailable(
            "stop is not on the losing side of entry — risk would be zero or negative"
        )
    if reward <= 0:
        return _unavailable("target is not on the winning side of entry")

    probability = to_probability(score, calibration)
    if probability is None:
        return _unavailable(
            "no calibrated probability for this score source: "
            f"{calibration.reason or 'not calibrated'}"
        )

    cost_model = costs or CostModel()
    known_costs, unmeasured = cost_model.total()

    reward_risk = reward / risk
    expected = probability * reward - (1.0 - probability) * risk - known_costs
    expected_r = expected / risk
    breakeven = breakeven_probability(reward, risk, known_costs)

    notes: list[str] = []
    if unmeasured:
        notes.append(
            "EV is optimistic by the unmeasured costs: " + ", ".join(unmeasured)
        )

    verdict = "trade"
    if reward_risk < MIN_REWARD_RISK:
        verdict = "wait"
        notes.append(
            f"reward:risk {reward_risk:.2f} is below the {MIN_REWARD_RISK} floor"
        )
    elif expected_r < MIN_EV_R:
        verdict = "wait"
        notes.append(
            f"expected value {expected_r:.3f} R is inside the noise of the cost estimate"
        )

    return EVResult(
        available=True,
        probability=round(probability, 6),
        reward=round(reward, 10),
        risk=round(risk, 10),
        reward_risk=round(reward_risk, 4),
        costs=round(known_costs, 10),
        unmeasured_costs=unmeasured,
        expected_value=round(expected, 10),
        expected_value_r=round(expected_r, 6),
        breakeven_probability=round(breakeven, 6) if breakeven is not None else None,
        verdict=verdict,
        notes=notes,
    )


def costs_from_context(
    *,
    spread: float | None = None,
    broker_symbol: Any | None = None,
    round_trips: int = 2,
    carry: float | None = None,
) -> CostModel:
    """Assemble a cost model from what the system actually knows.

    Spread is crossed on entry and again on exit, hence `round_trips`.
    Commission and swap come from the broker symbol when an operator has
    configured one; slippage stays unknown until real fills exist (phase 25),
    and is left as None rather than assumed to be zero.

    `carry` is the interest cost derived from the two countries' policy rates
    (see `brain.carry`), and it is a **fallback**, not an override. What a
    broker actually charges is the interbank differential plus their markup,
    which on a retail account can be several times the differential itself, so
    a configured `swap_per_night` is always the better number and always wins.
    The estimate exists because the alternative on a deployment with no broker
    symbol is not a smaller number - it is `None`, and every decision made with
    swap sitting in `unmeasured_costs` was made without knowing whether it was
    paying to hold the position or being paid for it.
    """
    commission = None
    swap = None
    if broker_symbol is not None:
        rules = getattr(broker_symbol, "margin_rules", None) or {}
        raw_commission = rules.get("commission_per_lot")
        raw_swap = rules.get("swap_per_night")
        commission = float(raw_commission) if raw_commission is not None else None
        swap = float(raw_swap) if raw_swap is not None else None

    if swap is None and carry is not None:
        swap = carry

    return CostModel(
        spread=abs(spread) * round_trips if spread is not None else None,
        commission=commission,
        swap=swap,
        slippage=None,
    )
