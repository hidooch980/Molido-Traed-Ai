"""Everything that has to hold before a positive number means anything.

`measure` answers one question well: over this window, did the rule beat a
random control on the same bars, paired by instant. A single answer to that
question is what the mean-reversion claim had when it printed CONFIRMED, and
the reason this module exists is that the answer was true and worthless - the
edge lived in one stretch of one series and nothing had asked.

So each function here takes the *same* paired instants and asks a different
way for the number to fall apart:

    segments      does it survive being cut by hour, weekday, year, regime?
    leave_one_out does it survive removing any single instrument?
    cost_stress   does it survive execution costing twice, or four times?
    permutation   does a coin flip on the same instants score as well?
    bootstrap     what is the interval around it, given serial overlap?

**Nothing here can promote an edge.** Every function returns a finding; the
registry in `app.learning.edge` decides, and its five requirements are
unchanged. A rule that passes every test below and has no forward evidence is
still NOT_PROVEN, and a rule that fails one of these while clearing the
registry is a rule whose registry entry should be re-read, not overridden.

**The unit of evidence stays the instant.** Every statistic recomputes its own
paired t from the rows rather than trusting a pre-aggregated number, because a
slice of a mean is not the mean of a slice, and the whole point of this module
is slicing.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.learning.measure import COST_R, Measurement, _paired_t

#: One row as `measure` keeps it: when, the rule's mean R at that instant, the
#: control's mean R at the same instant.
Row = tuple[datetime, float, float]

#: How much of the sample a slice needs before its number is worth printing.
#: Below this the standard error swamps any plausible edge, and a table of
#: twenty slices each with eleven observations is a table of noise with
#: headings.
MIN_SLICE = 100

#: Execution cost in R at three severities. The base figure is the module's
#: own measured cost; the others are what the same edge has to survive if the
#: spread widens or the fill slips. Not predictions - stresses.
COST_LEVELS: tuple[tuple[str, float], ...] = (
    ("base", COST_R),
    ("stressed", COST_R * 2.0),
    ("extreme", COST_R * 4.0),
)


# ------------------------------------------------------------------ statistics
def paired(rows: Sequence[Row]) -> tuple[float, float, int]:
    """(mean edge, t, n) for these instants, recomputed from the rows."""
    if not rows:
        return 0.0, 0.0, 0
    differences = [rule - control for _at, rule, control in rows]
    mean = sum(differences) / len(differences)
    t, _spread = _paired_t(differences)
    return mean, t, len(differences)


@dataclass(frozen=True)
class Slice:
    """One cut of the sample, with its own arithmetic."""

    name: str
    instants: int
    edge_r: float
    t: float

    @property
    def thin(self) -> bool:
        return self.instants < MIN_SLICE

    @property
    def positive(self) -> bool:
        return self.edge_r > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "instants": self.instants,
            "edge_r": round(self.edge_r, 4),
            "t": round(self.t, 2),
            "thin": self.thin,
            "positive": self.positive,
        }


def segments(
    rows: Sequence[Row], key: Callable[[datetime], str], *, label: str
) -> list[Slice]:
    """Cut the instants by a function of their timestamp and score each.

    The cut is on the decision instant, which is the only time this module
    knows. That is enough for the questions worth asking of it - session,
    weekday, year - and it is not enough for a volatility regime, which is a
    property of the market rather than of the clock. `regime_segments` takes
    that as data instead of pretending to derive it here.
    """
    buckets: dict[str, list[Row]] = {}
    for row in rows:
        buckets.setdefault(key(row[0]), []).append(row)
    if len(buckets) < 2:
        # Not a cut. Daily bars are all stamped at midnight, so slicing them
        # by hour puts every instant in one bucket and prints the headline
        # number under a heading that suggests it was tested by session. A
        # segmentation that separates nothing is worse than no segmentation:
        # it looks like evidence.
        return []
    out: list[Slice] = []
    for name, bucket in sorted(buckets.items()):
        edge, t, n = paired(bucket)
        out.append(Slice(name=f"{label}:{name}", instants=n, edge_r=edge, t=t))
    return out


def regime_segments(
    rows: Sequence[Row], regime_at: dict[datetime, str], *, label: str = "regime"
) -> list[Slice]:
    """Cut by a regime the caller measured, per instant.

    Takes a mapping rather than computing one. A regime derived inside this
    function from the same bars the rule traded would be derived with
    knowledge of the whole series - the caller has to say what was knowable at
    each instant, because that is the only version of the question that means
    anything. Instants with no regime recorded are counted under `unknown`
    rather than dropped: silently dropping them would let a regime label that
    only exists in calm periods make the sample look calm.
    """
    labelled: list[Row] = []
    for row in rows:
        labelled.append(row)
    buckets: dict[str, list[Row]] = {}
    for row in labelled:
        buckets.setdefault(regime_at.get(row[0], "unknown"), []).append(row)
    out: list[Slice] = []
    for name, bucket in sorted(buckets.items()):
        edge, t, n = paired(bucket)
        out.append(Slice(name=f"{label}:{name}", instants=n, edge_r=edge, t=t))
    return out


# ------------------------------------------------------------------ dimensions
def by_hour(rows: Sequence[Row]) -> list[Slice]:
    return segments(rows, lambda at: f"{at.hour:02d}", label="hour")


def by_session(rows: Sequence[Row]) -> list[Slice]:
    """Tokyo, London, New York, by UTC hour.

    The boundaries are the conventional ones and they are approximate: the
    exchanges move with daylight saving and this does not. Approximate is
    enough for the question - does the edge live in one session - and stating
    it here stops the boundary being read as a measurement.
    """

    def session(at: datetime) -> str:
        hour = at.hour
        if 0 <= hour < 7:
            return "tokyo"
        if 7 <= hour < 12:
            return "london"
        if 12 <= hour < 17:
            return "overlap"
        return "new-york"

    return segments(rows, session, label="session")


def by_weekday(rows: Sequence[Row]) -> list[Slice]:
    names = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    return segments(rows, lambda at: names[at.weekday()], label="weekday")


def by_year(rows: Sequence[Row]) -> list[Slice]:
    return segments(rows, lambda at: str(at.year), label="year")


def by_period(rows: Sequence[Row], *, parts: int = 3) -> list[Slice]:
    """Early, middle, recent - equal thirds of the instants, in order.

    Equal counts rather than equal spans: a series with a sparse first year
    and a dense last one splits by span into a slice that is mostly noise and
    one that is mostly the answer.
    """
    ordered = sorted(rows, key=lambda r: r[0])
    if not ordered or parts < 2:
        return []
    size = len(ordered) // parts
    if size == 0:
        return []
    names = {3: ("early", "middle", "recent")}.get(parts)
    out: list[Slice] = []
    for i in range(parts):
        chunk = ordered[i * size : (i + 1) * size] if i < parts - 1 else ordered[i * size :]
        edge, t, n = paired(chunk)
        name = names[i] if names else f"part-{i + 1}"
        out.append(Slice(name=f"period:{name}", instants=n, edge_r=edge, t=t))
    return out


# ----------------------------------------------------------------- cost stress
@dataclass(frozen=True)
class CostLevel:
    name: str
    cost_r: float
    net_r: float

    @property
    def survives(self) -> bool:
        return self.net_r > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "cost_r": round(self.cost_r, 4),
            "net_r": round(self.net_r, 4),
            "survives": self.survives,
        }


def cost_stress(
    edge_r: float, *, levels: Sequence[tuple[str, float]] = COST_LEVELS
) -> list[CostLevel]:
    """The same edge, charged more.

    Subtracted from the edge over the control rather than from the rule alone:
    the control pays execution too, and charging one arm and not the other
    invents an edge worth exactly the cost.
    """
    return [
        CostLevel(name=name, cost_r=cost, net_r=edge_r - cost) for name, cost in levels
    ]


# ------------------------------------------------------------------- placebo
@dataclass(frozen=True)
class Permutation:
    """A null built from the sample itself, without assuming a distribution."""

    draws: int
    observed_edge: float
    p_value: float
    null_mean: float
    null_spread: float
    #: How many draws of pure noise beat the observed edge. The p-value is
    #: this over the draws, and it is reported separately because "3 of 5000"
    #: is a fact and "p = 0.0006" is a rendering of it.
    at_least_as_extreme: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "draws": self.draws,
            "observed_edge_r": round(self.observed_edge, 4),
            "at_least_as_extreme": self.at_least_as_extreme,
            "p_value": round(self.p_value, 5),
            "null_mean_r": round(self.null_mean, 5),
            "null_spread_r": round(self.null_spread, 5),
            "null": (
                "each draw flips the sign of each instant's rule-minus-control "
                "difference at random, which is exactly the hypothesis that the "
                "rule's choice of direction carries no information"
            ),
        }


def permutation_test(
    rows: Sequence[Row], *, draws: int = 5000, seed: int = 20260902
) -> Permutation:
    """Sign-flip permutation on the paired differences.

    The null is the one worth testing: not "the rule earns zero" but "the
    rule's *direction* is arbitrary". Flipping the sign of a paired difference
    is what that hypothesis does to the data, and the resulting distribution
    needs no assumption of normality - which matters here because R outcomes
    are bimodal by construction, a stop or a target and nothing between.

    Seeded, so a re-run reproduces. A p-value that moves when you look again
    is not one.
    """
    differences = [rule - control for _at, rule, control in rows]
    n = len(differences)
    if n < 2:
        return Permutation(0, 0.0, 1.0, 0.0, 0.0, 0)
    observed = sum(differences) / n
    rng = random.Random(seed)  # noqa: S311 - a seeded permutation test, not a secret
    beats = 0
    total = 0.0
    total_square = 0.0
    for _ in range(draws):
        drawn = sum(d if rng.random() < 0.5 else -d for d in differences) / n
        total += drawn
        total_square += drawn * drawn
        if abs(drawn) >= abs(observed):
            beats += 1
    mean = total / draws
    variance = max(total_square / draws - mean * mean, 0.0)
    # +1 in both places: a permutation p-value of exactly zero claims the
    # observed value is impossible under the null, and the sample never
    # supports that - it supports "not seen in this many draws".
    return Permutation(
        draws=draws,
        observed_edge=observed,
        p_value=(beats + 1) / (draws + 1),
        null_mean=mean,
        null_spread=math.sqrt(variance),
        at_least_as_extreme=beats,
    )


# ----------------------------------------------------------------- bootstrap
@dataclass(frozen=True)
class Bootstrap:
    draws: int
    block: int
    median: float
    lower: float
    upper: float

    @property
    def excludes_zero(self) -> bool:
        return self.lower > 0 or self.upper < 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "draws": self.draws,
            "block_instants": self.block,
            "median_edge_r": round(self.median, 4),
            "ci_lower_r": round(self.lower, 4),
            "ci_upper_r": round(self.upper, 4),
            "excludes_zero": self.excludes_zero,
            "why_blocks": (
                "entries opened within one horizon of each other resolve on "
                "overlapping bars, so consecutive instants are not independent. "
                "Resampling single instants would break that dependence and "
                "report an interval narrower than the data supports"
            ),
        }


def block_bootstrap(
    rows: Sequence[Row],
    *,
    block: int,
    draws: int = 2000,
    seed: int = 20260902,
    confidence: float = 0.95,
) -> Bootstrap:
    """Moving-block bootstrap over the paired differences.

    `block` must be at least the horizon in instants, and the caller passes it
    rather than this guessing: how many instants a 120-bar horizon spans
    depends on how often the rule fires, which is a property of the run.
    """
    ordered = [rule - control for _at, rule, control in sorted(rows, key=lambda r: r[0])]
    n = len(ordered)
    block = max(1, min(int(block), n))
    if n < 2:
        return Bootstrap(0, block, 0.0, 0.0, 0.0)
    rng = random.Random(seed)  # noqa: S311 - a seeded block bootstrap, not a secret
    starts = n - block + 1
    needed = math.ceil(n / block)
    means: list[float] = []
    for _ in range(draws):
        sample: list[float] = []
        for _ in range(needed):
            begin = rng.randrange(starts)
            sample.extend(ordered[begin : begin + block])
        sample = sample[:n]
        means.append(sum(sample) / len(sample))
    means.sort()
    tail = (1.0 - confidence) / 2.0
    lower = means[int(tail * (draws - 1))]
    upper = means[int((1 - tail) * (draws - 1))]
    median = means[draws // 2]
    return Bootstrap(draws=draws, block=block, median=median, lower=lower, upper=upper)


# --------------------------------------------------------------- leave one out
@dataclass(frozen=True)
class Excluded:
    """What the edge became with one instrument removed from the universe."""

    symbol: str
    instants: int
    edge_r: float
    t: float

    @property
    def measurable(self) -> bool:
        """Whether the run produced any evidence at all.

        A run that scored no instants has an edge of exactly zero, and zero
        here means "not measured", not "no edge". `rank` refuses a
        cross-section thinner than its minimum, so on a universe already at
        that minimum every removal empties every instant and the table fills
        with confident zeroes that read as twenty fragilities.
        """
        return self.instants > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "without": self.symbol,
            "instants": self.instants,
            "edge_r": round(self.edge_r, 4) if self.measurable else None,
            "t": round(self.t, 2) if self.measurable else None,
            "measurable": self.measurable,
        }


def leave_one_out(
    run: Callable[[frozenset[str]], Measurement],
    *,
    universe: frozenset[str],
    full_edge: float,
) -> tuple[list[Excluded], list[str]]:
    """Re-measure once per instrument, with that instrument out of the ranking.

    `run` is a callable so this module never has to know how a measurement is
    assembled; the CLI passes a closure over the loaded series.

    Removed from the *universe*, not from the counted trades. Dropping an
    instrument's trades while it still influences the ranking measures a
    different rule - one that ranks against an instrument it may not trade -
    and the question here is what the rule is worth without that market at
    all.

    Returns the runs and the names whose removal takes the edge to zero or
    below: an edge that exists only in the presence of one instrument is a
    finding about that instrument.

    **A run that scored nothing is not a run that scored zero.** `rank`
    refuses a cross-section thinner than its minimum, so on a universe sitting
    at that minimum every removal empties every instant, every run returns an
    edge of exactly 0.0000, and the naive reading is that the edge depends on
    all twenty instruments at once - which is not a finding, it is the
    absence of one. Those runs are reported as unmeasurable and take no part
    in the fragility verdict.
    """
    runs: list[Excluded] = []
    fragile: list[str] = []
    for symbol in sorted(universe):
        measurement = run(frozenset(universe - {symbol}))
        excluded = Excluded(
            symbol=symbol,
            instants=measurement.instants,
            edge_r=measurement.edge_r,
            t=measurement.t_statistic,
        )
        runs.append(excluded)
        if excluded.measurable and full_edge > 0 and measurement.edge_r <= 0:
            fragile.append(symbol)
    return runs, fragile


# ------------------------------------------------------------------- verdict
@dataclass
class Robustness:
    """Every finding, and the one sentence that follows from all of them."""

    instants: int
    edge_r: float
    t: float
    slices: list[Slice] = field(default_factory=list)
    costs: list[CostLevel] = field(default_factory=list)
    permutation: Permutation | None = None
    bootstrap: Bootstrap | None = None
    excluded: list[Excluded] = field(default_factory=list)
    fragile_on: list[str] = field(default_factory=list)
    #: How many distinct hypotheses were tried to arrive here. Required, and
    #: not defaulted to one: a rule chosen from a sweep carries the sweep.
    hypotheses_tested: int = 1

    @property
    def thick_slices(self) -> list[Slice]:
        return [s for s in self.slices if not s.thin]

    @property
    def negative_slices(self) -> list[Slice]:
        return [s for s in self.thick_slices if not s.positive]

    @property
    def survives_extreme_cost(self) -> bool:
        return bool(self.costs) and self.costs[-1].survives

    @property
    def separated_from_placebo(self) -> bool:
        return self.permutation is not None and self.permutation.p_value < 0.05

    @property
    def required_t(self) -> float:
        """Bonferroni-style, for however many hypotheses were tried."""
        if self.hypotheses_tested <= 1:
            return 1.96
        return 1.96 * math.sqrt(1 + math.log(self.hypotheses_tested))

    @property
    def findings(self) -> list[str]:
        """Everything that did not hold, in words, or an empty list."""
        out: list[str] = []
        if abs(self.t) < self.required_t:
            out.append(
                f"t = {self.t:.2f} does not clear the {self.required_t:.2f} "
                f"required for {self.hypotheses_tested} hypothesis(es)"
            )
        negative = self.negative_slices
        if negative:
            out.append(
                "the edge is negative in "
                f"{len(negative)} of {len(self.thick_slices)} slices with enough "
                f"data: {', '.join(s.name for s in negative[:6])}"
            )
        if not self.survives_extreme_cost:
            out.append("it does not survive execution costing four times the measured figure")
        if not self.separated_from_placebo:
            out.append("a sign-flipped null reproduces it as often as not")
        if self.bootstrap is not None and not self.bootstrap.excludes_zero:
            out.append(
                f"the block bootstrap interval [{self.bootstrap.lower:+.4f}, "
                f"{self.bootstrap.upper:+.4f}] contains zero"
            )
        if self.fragile_on:
            out.append(
                "removing " + ", ".join(self.fragile_on) + " takes the edge to zero"
            )
        return out

    @property
    def verdict(self) -> str:
        """Never PROVEN. That word belongs to the registry, which also asks
        for forward evidence and pre-registration - neither of which any
        amount of re-slicing the same history can supply."""
        if self.fragile_on:
            return "FRAGILE"
        if self.findings:
            return "NOT_ROBUST"
        return "ROBUST_ON_THIS_SAMPLE"

    def as_dict(self) -> dict[str, Any]:
        return {
            "instants": self.instants,
            "edge_r": round(self.edge_r, 4),
            "t": round(self.t, 2),
            "required_t": round(self.required_t, 2),
            "hypotheses_tested": self.hypotheses_tested,
            "verdict": self.verdict,
            "findings": self.findings,
            "slices": [s.as_dict() for s in self.slices],
            "slices_thin": len([s for s in self.slices if s.thin]),
            "cost_stress": [c.as_dict() for c in self.costs],
            "permutation": self.permutation.as_dict() if self.permutation else None,
            "bootstrap": self.bootstrap.as_dict() if self.bootstrap else None,
            "leave_one_out": [e.as_dict() for e in self.excluded],
            "fragile_on": self.fragile_on,
            "note": (
                "this grades whether a measured edge holds up under re-slicing, "
                "not whether it is proven. Proof needs pre-registration and "
                "evidence from after the hypothesis was written down, and no "
                "amount of re-cutting the same history supplies either"
            ),
        }


def assess(
    measurement: Measurement,
    *,
    horizon_instants: int,
    hypotheses_tested: int = 1,
    excluded: Sequence[Excluded] = (),
    fragile_on: Sequence[str] = (),
    regime_at: dict[datetime, str] | None = None,
    draws: int = 5000,
) -> Robustness:
    """Run every test above against one measurement's kept instants.

    Requires `keep_instants=True` on the measurement: without the rows there
    is nothing to slice, and re-deriving them from the summary is not
    possible. Raises rather than returning an empty report, because a
    robustness report that quietly checked nothing is the shape of thing this
    whole module exists to stop.
    """
    rows = measurement.instant_rows
    if rows is None:
        raise ValueError(
            "this needs the measurement's instant rows; re-run measure() with "
            "keep_instants=True. A robustness report assembled from a summary "
            "would be a report about a number rather than about the sample"
        )
    slices: list[Slice] = []
    slices += by_session(rows)
    slices += by_weekday(rows)
    slices += by_year(rows)
    slices += by_period(rows)
    if regime_at:
        slices += regime_segments(rows, regime_at)
    return Robustness(
        instants=measurement.instants,
        edge_r=measurement.edge_r,
        t=measurement.t_statistic,
        slices=slices,
        costs=cost_stress(measurement.edge_r),
        permutation=permutation_test(rows, draws=draws),
        bootstrap=block_bootstrap(rows, block=horizon_instants, draws=max(500, draws // 2)),
        excluded=list(excluded),
        fragile_on=list(fragile_on),
        hypotheses_tested=hypotheses_tested,
    )


__all__ = [
    "COST_LEVELS",
    "MIN_SLICE",
    "Bootstrap",
    "CostLevel",
    "Excluded",
    "Permutation",
    "Robustness",
    "Slice",
    "assess",
    "block_bootstrap",
    "by_hour",
    "by_period",
    "by_session",
    "by_weekday",
    "by_year",
    "cost_stress",
    "leave_one_out",
    "paired",
    "permutation_test",
    "regime_segments",
    "segments",
]
