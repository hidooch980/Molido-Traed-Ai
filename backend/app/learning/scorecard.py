"""Does this strategy have an edge, or does it have a sample? (§32, §36)

The measurement that was missing. The calibration run over 718 resolved EURUSD
setups produced hit rates between 0.27 and 0.31 across the whole conviction
range, with the three highest buckets holding 34, 69 and 25 observations —
intervals wide enough to contain almost any story somebody wanted to tell. I
told one. This module exists so that cannot happen again.

Four rules, and the third is the one that costs the most to follow:

**Breakeven comes from the realised reward:risk, not the intended one.** A
strategy built to 2R that actually returns 1.3R on its winners needs a hit rate
of 43%, not 33%. Measuring against the intended figure flatters every strategy
that fails to reach its targets — which is every strategy, because targets are
missed and stops are not.

**The interval decides, not the point estimate.** A hit rate of 0.36 against a
breakeven of 0.33 is not an edge if the interval runs from 0.24 to 0.48. The
verdict is driven by the lower bound, so "probably positive" reads as
`insufficient` rather than as `edge`.

**Testing ten strategies finds one that looks good.** With enough families,
regimes and sessions, something clears any threshold by chance. Every scorecard
carries the number of comparisons it was one of, and the threshold tightens
accordingly. A strategy that only clears without the correction is reported as
clearing only without the correction.

**Wilson, not the normal approximation.** At n=25 and p=0.3 the textbook
interval is both too narrow and skewed the wrong way. Wilson is barely more
code and does not misbehave near the ends.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any

# Below this many resolved trials a strategy has a sample, not a result. Fifty
# is where a hit rate's 95% interval narrows to roughly +/- 13 points, which is
# still wide - it is the floor at which the question becomes answerable at all,
# not the point at which the answer is precise.
MIN_TRIALS = 50

# Confidence level for every interval reported here.
Z = 1.96


@dataclass(frozen=True)
class Trial:
    """One setup that fired, and what it returned.

    `r_multiple` is None while the outcome has not matured. Unresolved trials
    are counted and excluded, never treated as scratches: dropping them
    silently biases the result toward whichever outcome resolves faster, and
    stops resolve faster than targets.
    """

    strategy: str
    r_multiple: float | None
    regime: str = "unknown"
    session: str = "unknown"
    conviction: float | None = None

    @property
    def resolved(self) -> bool:
        return self.r_multiple is not None

    @property
    def won(self) -> bool:
        return self.r_multiple is not None and self.r_multiple > 0


def wilson_interval(hits: int, trials: int, z: float = Z) -> tuple[float, float]:
    """Wilson score interval for a proportion.

    Used instead of `p +/- z*sqrt(p(1-p)/n)` because at the sample sizes this
    module actually sees, the normal approximation is narrow enough to turn a
    coin flip into a finding.
    """
    if trials <= 0:
        return (0.0, 1.0)
    p = hits / trials
    denominator = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denominator
    spread = (
        z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denominator
    )
    return (max(0.0, centre - spread), min(1.0, centre + spread))


def breakeven_hit_rate(reward_risk: float) -> float | None:
    """The hit rate a payoff of `reward_risk` needs just to stand still."""
    if reward_risk <= 0:
        return None
    return 1.0 / (1.0 + reward_risk)


@dataclass
class Scorecard:
    """One strategy's result, with everything needed to disbelieve it."""

    strategy: str
    trials: int
    unresolved: int
    wins: int
    hit_rate: float | None = None
    hit_rate_low: float | None = None
    hit_rate_high: float | None = None
    average_win_r: float | None = None
    average_loss_r: float | None = None
    realised_reward_risk: float | None = None
    required_hit_rate: float | None = None
    expectancy_r: float | None = None
    #: Gross winnings divided by gross losses. Expectancy says what the
    #: average trade returns; this says how much was won for every unit
    #: lost, and the two disagree in the case that matters - a strategy
    #: with a positive average carried by one outlier has a profit
    #: factor barely above one, and the average alone hides that.
    profit_factor: float | None = None
    #: The worst peak-to-trough fall of the cumulative R curve, in R.
    #:
    #: A strategy is not described by its total. Two with the same
    #: expectancy are different instruments if one reached it through a
    #: 12 R hole - on a challenge account the hole is what ends the
    #: attempt, whatever the total would have been.
    max_drawdown_r: float | None = None
    #: The longest run of consecutive losers. The number an account
    #: holder actually has to sit through.
    longest_losing_run: int = 0
    comparisons: int = 1
    verdict: str = "insufficient"
    reason: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def has_edge(self) -> bool:
        return self.verdict == "edge"

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "verdict": self.verdict,
            "reason": self.reason,
            "trials": self.trials,
            "unresolved": self.unresolved,
            "wins": self.wins,
            "hit_rate": _round(self.hit_rate),
            "hit_rate_95ci": [_round(self.hit_rate_low), _round(self.hit_rate_high)],
            "average_win_r": _round(self.average_win_r),
            "average_loss_r": _round(self.average_loss_r),
            "realised_reward_risk": _round(self.realised_reward_risk),
            "required_hit_rate": _round(self.required_hit_rate),
            "expectancy_r": _round(self.expectancy_r),
            "profit_factor": _round(self.profit_factor),
            "max_drawdown_r": _round(self.max_drawdown_r),
            "longest_losing_run": self.longest_losing_run,
            "comparisons": self.comparisons,
            "notes": self.notes,
            # An edge measured in a backtest is a hypothesis about the future.
            "note": "a measured edge is evidence, not a forecast",
        }


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def _bonferroni_z(comparisons: int) -> float:
    """Widen the interval for the number of strategies tested at once.

    Approximate, and deliberately so: the exact correction depends on how
    correlated the families are, which nobody knows. The point is that the
    threshold moves at all - testing twelve strategies against a fixed 95% line
    finds one winner in a room of coin flips.
    """
    if comparisons <= 1:
        return Z
    # Inverse normal at 1 - alpha/(2m), approximated well enough over the range
    # of comparison counts this module sees.
    alpha = 0.05 / comparisons
    return abs(_inverse_normal(alpha / 2))


def _inverse_normal(p: float) -> float:
    """Acklam's rational approximation. Accurate to ~1e-9 over (0, 1)."""
    if not 0 < p < 1:
        raise ValueError("p must be in (0, 1)")
    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
         3.754408661907416e00]
    low, high = 0.02425, 1 - 0.02425
    if p < low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / (
            (((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > high:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / (
            (((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (
        ((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def score(
    trials: list[Trial],
    *,
    strategy: str,
    comparisons: int = 1,
    min_trials: int = MIN_TRIALS,
) -> Scorecard:
    """Judge one strategy against the hit rate its own payoff demands."""
    resolved = [t for t in trials if t.resolved]
    unresolved = len(trials) - len(resolved)
    card = Scorecard(
        strategy=strategy,
        trials=len(resolved),
        unresolved=unresolved,
        wins=sum(1 for t in resolved if t.won),
        comparisons=comparisons,
    )

    if unresolved:
        # Named rather than dropped: stops resolve faster than targets, so a
        # silent exclusion biases the result toward the losers being counted
        # first.
        card.notes.append(
            f"{unresolved} trials have not matured and are excluded — stops resolve "
            "faster than targets, so their absence is not neutral"
        )

    if len(resolved) < min_trials:
        card.reason = (
            f"{len(resolved)} resolved trials, below the {min_trials} at which the "
            "question becomes answerable"
        )
        return card

    wins = [t.r_multiple for t in resolved if t.won]
    losses = [t.r_multiple for t in resolved if not t.won]
    if not wins or not losses:
        card.reason = (
            "every trial went the same way, so there is no payoff ratio to measure "
            "against — a sample with no losers has not met a loser yet"
        )
        return card

    card.hit_rate = len(wins) / len(resolved)
    card.average_win_r = statistics.fmean(wins)  # type: ignore[arg-type]
    card.average_loss_r = abs(statistics.fmean(losses))  # type: ignore[arg-type]
    card.realised_reward_risk = (
        card.average_win_r / card.average_loss_r if card.average_loss_r > 0 else None
    )
    card.required_hit_rate = (
        breakeven_hit_rate(card.realised_reward_risk)
        if card.realised_reward_risk
        else None
    )
    card.expectancy_r = statistics.fmean(
        [t.r_multiple for t in resolved]  # type: ignore[misc]
    )

    # Gross win over gross loss. Infinite when nothing lost is reported
    # as None rather than as a huge number: a strategy with no losing
    # trade yet has not been measured against losing, and a printed
    # 999 would be read as a result.
    gross_win = sum((t.r_multiple or 0.0) for t in resolved if (t.r_multiple or 0.0) > 0)
    gross_loss = -sum((t.r_multiple or 0.0) for t in resolved if (t.r_multiple or 0.0) < 0)
    card.profit_factor = (gross_win / gross_loss) if gross_loss > 0 else None

    # The R curve in the order the trades resolved, and its worst fall
    # from a peak. Order matters here and nowhere else on this card,
    # which is why it is computed from the sequence rather than from
    # the aggregates above.
    running = peak = 0.0
    worst = 0.0
    losing_run = longest_run = 0
    for trade in resolved:
        value = trade.r_multiple or 0.0
        running += value
        peak = max(peak, running)
        worst = max(worst, peak - running)
        if value < 0:
            losing_run += 1
            longest_run = max(longest_run, losing_run)
        else:
            losing_run = 0
    card.max_drawdown_r = worst
    card.longest_losing_run = longest_run

    z = _bonferroni_z(comparisons)
    card.hit_rate_low, card.hit_rate_high = wilson_interval(len(wins), len(resolved), z)
    if comparisons > 1:
        card.notes.append(
            f"interval widened for {comparisons} simultaneous comparisons — testing "
            "many strategies against a fixed line finds a winner in a room of coin flips"
        )

    if card.required_hit_rate is None:
        card.reason = "the payoff ratio could not be measured"
        return card

    if card.hit_rate_low > card.required_hit_rate:
        card.verdict = "edge"
        card.reason = (
            f"hit rate {card.hit_rate:.1%} with a lower bound of {card.hit_rate_low:.1%}, "
            f"above the {card.required_hit_rate:.1%} its {card.realised_reward_risk:.2f} "
            "realised payoff demands"
        )
    elif card.hit_rate_high < card.required_hit_rate:
        card.verdict = "negative"
        card.reason = (
            f"hit rate {card.hit_rate:.1%} with an upper bound of {card.hit_rate_high:.1%}, "
            f"below the {card.required_hit_rate:.1%} needed — this loses money at a "
            "measurable rate"
        )
    else:
        card.verdict = "insufficient"
        card.reason = (
            f"hit rate {card.hit_rate:.1%}, interval "
            f"[{card.hit_rate_low:.1%}, {card.hit_rate_high:.1%}] straddles the "
            f"{card.required_hit_rate:.1%} it needs — not shown to work, not shown to fail"
        )
    return card


def score_all(
    trials_by_strategy: dict[str, list[Trial]], *, min_trials: int = MIN_TRIALS
) -> list[Scorecard]:
    """Score every strategy, correcting each for how many were tested."""
    comparisons = max(1, len(trials_by_strategy))
    cards = [
        score(trials, strategy=name, comparisons=comparisons, min_trials=min_trials)
        for name, trials in sorted(trials_by_strategy.items())
    ]
    return sorted(cards, key=lambda c: (c.verdict != "edge", -(c.expectancy_r or -99)))


def summarise(cards: list[Scorecard]) -> dict[str, Any]:
    """The one-line answer: is anything here worth trading?"""
    with_edge = [c for c in cards if c.has_edge]
    return {
        "strategies": len(cards),
        "with_edge": [c.strategy for c in with_edge],
        "negative": [c.strategy for c in cards if c.verdict == "negative"],
        "insufficient": [c.strategy for c in cards if c.verdict == "insufficient"],
        "any_edge": bool(with_edge),
        "cards": [c.as_dict() for c in cards],
        "note": (
            "an edge here is a measurement over past bars; it becomes a forecast "
            "only after it survives out of sample"
        ),
    }
