"""What the same edge looks like when the order, the sample or the fill changes.

Section 16 of the research brief asks for Monte Carlo, and the report already
had two of its members: a block bootstrap over the instants and a sign-flipped
placebo. Those answer "is the mean distinguishable from zero". They do not
answer the three questions an account holder actually has to live with:

  * **Was this drawdown lucky?** The same trades in a different order produce a
    different worst peak-to-trough fall, and the one that happened is a single
    draw from that distribution. A strategy is not described by its total - two
    with the same expectancy are different instruments if one reached it
    through a hole twice as deep.
  * **Does the edge rest on a handful of instants?** Drop a random share of
    them and see how often what is left is still positive. An edge carried by
    six moments out of four hundred is a story about those six moments.
  * **Does it survive being late?** Every result here assumes the bar after the
    decision is available at its open. A fill one bar later is not a cost, it
    is a different trade, and a rule whose edge lives entirely in the first bar
    is a rule about latency rather than about markets.

The first two work on the rows `measure` already keeps. The third cannot: it
needs the series re-walked with the entry moved, so it lives in `measure`
itself and this module only reports it.

**Every draw is seeded.** Section 28 asks for reproducibility, and a robustness
number that changes each time it is run is not evidence, it is weather.
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.learning.robustness import Row

#: Draws for every resampling here. Five thousand is where the fifth
#: percentile of a few hundred instants stops moving between runs at the
#: resolution these numbers are printed to; more is slower without being
#: more informative.
DRAWS = 5000

#: The seed. Fixed rather than random so two runs of the same report agree,
#: and stated rather than hidden so a reader can change it and see for
#: themselves that the answer does not depend on it.
SEED = 20260908

#: How much of the sample the omission test throws away. A fifth: large
#: enough that an edge carried by a few instants will lose them in most
#: draws, small enough that what remains is still the same experiment.
OMIT_FRACTION = 0.2


def edges(rows: Sequence[Row]) -> list[float]:
    """The rule's advantage over its control at each instant, in R."""
    return [rule - control for _at, rule, control in rows]


# ----------------------------------------------------------------- the curve
@dataclass(frozen=True)
class Curve:
    """What the run of instants did, in the order it happened."""

    total_r: float
    max_drawdown_r: float
    longest_losing_run: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_r": round(self.total_r, 4),
            "max_drawdown_r": round(self.max_drawdown_r, 4),
            "longest_losing_run": self.longest_losing_run,
        }


def curve(values: Sequence[float]) -> Curve:
    """Cumulative sum, its worst fall from a peak, and the longest cold run.

    Drawdown is measured from the running peak rather than from the start, so
    a strategy that doubles and then halves is described as having halved.
    """
    total = 0.0
    peak = 0.0
    worst = 0.0
    run = 0
    longest = 0
    for value in values:
        total += value
        peak = max(peak, total)
        worst = max(worst, peak - total)
        if value < 0:
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    return Curve(total_r=total, max_drawdown_r=worst, longest_losing_run=longest)


# ------------------------------------------------------------- the resampling
@dataclass(frozen=True)
class Reshuffle:
    """The observed drawdown against the ones the same trades could have had."""

    observed_r: float
    median_r: float
    p95_r: float
    worst_r: float
    percentile_of_observed: float
    draws: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "observed_drawdown_r": round(self.observed_r, 4),
            "median_drawdown_r": round(self.median_r, 4),
            "p95_drawdown_r": round(self.p95_r, 4),
            "worst_drawdown_r": round(self.worst_r, 4),
            "observed_at_percentile": round(self.percentile_of_observed, 1),
            "draws": self.draws,
            "note": (
                "the order of these trades was one draw from this distribution; "
                "the 95th percentile is the hole to plan for, not the observed one"
            ),
        }


def reshuffled(rows: Sequence[Row], *, draws: int = DRAWS, seed: int = SEED) -> Reshuffle | None:
    """Deal the same instants in a different order, `draws` times.

    The multiset of outcomes is untouched - only their sequence changes - so
    the total is identical in every draw and the only thing that moves is the
    path. That is the point: expectancy is a property of the trades, drawdown
    is a property of their order, and only one of the two was observed.
    """
    values = edges(rows)
    if len(values) < 2:
        return None

    observed = curve(values).max_drawdown_r
    rng = random.Random(seed)  # noqa: S311 - a seeded reshuffle, not a secret
    pool = list(values)
    falls: list[float] = []
    for _ in range(draws):
        rng.shuffle(pool)
        falls.append(curve(pool).max_drawdown_r)
    falls.sort()

    below = sum(1 for fall in falls if fall <= observed)
    return Reshuffle(
        observed_r=observed,
        median_r=falls[len(falls) // 2],
        p95_r=falls[int(len(falls) * 0.95)],
        worst_r=falls[-1],
        percentile_of_observed=100.0 * below / len(falls),
        draws=draws,
    )


@dataclass(frozen=True)
class Omission:
    """How often the edge is still positive with part of the sample gone."""

    fraction: float
    kept: int
    share_positive: float
    p05_r: float
    median_r: float
    draws: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "dropped_fraction": self.fraction,
            "instants_kept": self.kept,
            "share_of_draws_positive": round(self.share_positive, 4),
            "p05_mean_edge_r": round(self.p05_r, 4),
            "median_mean_edge_r": round(self.median_r, 4),
            "draws": self.draws,
        }


def with_random_omission(
    rows: Sequence[Row],
    *,
    fraction: float = OMIT_FRACTION,
    draws: int = DRAWS,
    seed: int = SEED,
) -> Omission | None:
    """Throw away a random share of the instants and re-read the edge.

    An edge that survives losing a fifth of its evidence most of the time is
    spread across the sample. One that does not is carried by a few instants,
    and a few instants are an anecdote however large the t statistic computed
    over all of them.
    """
    values = edges(rows)
    keep = int(len(values) * (1.0 - fraction))
    if keep < 2:
        return None

    rng = random.Random(seed)  # noqa: S311 - a seeded resample, not a secret
    means: list[float] = []
    for _ in range(draws):
        sample = rng.sample(values, keep)
        means.append(sum(sample) / keep)
    means.sort()

    return Omission(
        fraction=fraction,
        kept=keep,
        share_positive=sum(1 for mean in means if mean > 0) / len(means),
        p05_r=means[int(len(means) * 0.05)],
        median_r=means[len(means) // 2],
        draws=draws,
    )


# ----------------------------------------------------------------- the ratios
@dataclass(frozen=True)
class Ratios:
    """Section 21's risk-adjusted readings, per instant and unannualised.

    **Unannualised on purpose.** Annualising needs a number of instants per
    year, and the instants here are not evenly spaced - the rule fires when it
    fires, markets shut at weekends, and a sparse series and a dense one would
    be multiplied by different constants for reasons that have nothing to do
    with either edge. A per-instant Sharpe compares two rules on this sample
    honestly; an annualised one compares them to a convention.
    """

    mean_r: float
    sharpe: float | None
    sortino: float | None
    calmar: float | None
    recovery_factor: float | None
    profit_factor: float | None
    win_rate: float
    instants: int

    def as_dict(self) -> dict[str, Any]:
        def _round(value: float | None) -> float | None:
            return None if value is None else round(value, 4)

        return {
            "mean_edge_r": _round(self.mean_r),
            "sharpe_per_instant": _round(self.sharpe),
            "sortino_per_instant": _round(self.sortino),
            "calmar": _round(self.calmar),
            "recovery_factor": _round(self.recovery_factor),
            "profit_factor": _round(self.profit_factor),
            "win_rate": _round(self.win_rate),
            "instants": self.instants,
            "note": "per instant, not annualised - the instants are not evenly spaced",
        }


def ratios(rows: Sequence[Row]) -> Ratios | None:
    """Sharpe, Sortino, Calmar, recovery and profit factor over the edge series.

    Computed on the *edge* - the rule minus its control at the same instant -
    rather than on the rule's raw return, for the same reason every other
    number in this project is: a raw return includes whatever the market did
    to everything, and two rules measured in different years would be compared
    on that rather than on themselves.

    Sortino divides by the downside deviation only, so a rule whose variance
    is mostly upside is not punished for it. Calmar and recovery both divide
    by the worst fall, which is why they are None when there was none: a
    strategy that never drew down has no ratio, and printing a large number
    there would be inventing one.
    """
    values = edges(rows)
    if len(values) < 2:
        return None

    mean = sum(values) / len(values)
    spread = statistics.pstdev(values)
    downside = [value for value in values if value < 0]
    down_spread = math.sqrt(sum(v * v for v in downside) / len(values)) if downside else 0.0

    shape = curve(values)
    won = sum(value for value in values if value > 0)
    lost = -sum(value for value in values if value < 0)

    return Ratios(
        mean_r=mean,
        sharpe=(mean / spread) if spread else None,
        sortino=(mean / down_spread) if down_spread else None,
        calmar=(mean / shape.max_drawdown_r) if shape.max_drawdown_r else None,
        recovery_factor=((shape.total_r / shape.max_drawdown_r) if shape.max_drawdown_r else None),
        profit_factor=(won / lost) if lost else None,
        win_rate=sum(1 for value in values if value > 0) / len(values),
        instants=len(values),
    )


def report(rows: Sequence[Row], *, draws: int = DRAWS, seed: int = SEED) -> dict[str, Any]:
    """Everything in this module for one measured sample."""
    shape = curve(edges(rows))
    shuffle = reshuffled(rows, draws=draws, seed=seed)
    omit = with_random_omission(rows, draws=draws, seed=seed)
    read = ratios(rows)
    return {
        "seed": seed,
        "curve": shape.as_dict(),
        "reshuffled": shuffle.as_dict() if shuffle else None,
        "omission": omit.as_dict() if omit else None,
        "ratios": read.as_dict() if read else None,
    }


def render(payload: dict[str, Any]) -> list[str]:
    """The report's lines, or an explanation of why there are none."""
    lines = [f"  monte carlo (seed {payload.get('seed')}):"]
    shuffle = payload.get("reshuffled")
    if shuffle:
        lines.append(
            f"    drawdown observed {shuffle['observed_drawdown_r']:.4f} R, "
            f"median {shuffle['median_drawdown_r']:.4f}, "
            f"95th {shuffle['p95_drawdown_r']:.4f}, "
            f"worst {shuffle['worst_drawdown_r']:.4f}"
        )
        lines.append(
            "    the order that happened sits at the "
            f"{shuffle['observed_at_percentile']:.1f}th percentile of orders"
        )
    omit = payload.get("omission")
    if omit:
        lines.append(
            f"    dropping {omit['dropped_fraction'] * 100:.0f}% at random leaves a "
            f"positive edge in {omit['share_of_draws_positive'] * 100:.1f}% of draws"
        )
    read = payload.get("ratios")
    if read:
        lines.append(
            f"    sharpe {read['sharpe_per_instant']}  "
            f"sortino {read['sortino_per_instant']}  "
            f"calmar {read['calmar']}  "
            f"profit factor {read['profit_factor']}  (per instant)"
        )
    if len(lines) == 1:
        lines.append("    too few instants to resample")
    return lines


__all__ = [
    "Curve",
    "DRAWS",
    "OMIT_FRACTION",
    "Omission",
    "Ratios",
    "Reshuffle",
    "SEED",
    "curve",
    "edges",
    "ratios",
    "render",
    "report",
    "reshuffled",
    "with_random_omission",
]
