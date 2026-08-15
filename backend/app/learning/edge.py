"""What counts as a proven edge, and what a claim has to survive to be one.

This file exists because of a specific mistake made in this project, and it
exists so the mistake cannot be made silently again.

A pre-registered hypothesis was tested on held-out data. The script printed
CONFIRMED. It was wrong: it compared the rule against breakeven, and the number
that mattered was the rule against a random control run on the same bars. The
control landed at 50.32%, the rule at 50.84%, and the difference - 0.52
percentage points, z = 1.09 - is not distinguishable from noise. A system built
on that CONFIRMED would have traded at roughly breakeven and lost the spread on
every round trip, slowly, for months, while looking like an execution problem.

So an edge is registered here only if it survives all five:

  1. **Pre-registered.** The hypothesis, the geometry, the data slice and the
     threshold are written down before the held-out data is read. Choosing them
     afterwards is choosing them to fit.

  2. **Beaten a control, not breakeven.** A random-entry control runs on the
     same bars. The claim is the rule's edge *over the control*, because the
     control measures what no information scores on that data - and here it did
     not score zero.

  3. **Significant after correction.** One pre-registered hypothesis is one
     comparison, z = 1.96. A rule chosen from a sweep of N carries the sweep's
     correction, and the number of candidates is recorded so a later reader can
     check the arithmetic rather than trust it.

  4. **Costed.** The edge is stated net of a spread the broker actually
     charges. An edge smaller than the spread is not a small edge; it is a
     loss.

  5. **Forward.** Confirmed on data generated after the hypothesis was
     registered, not only on a held-out slice of history. Held-out history is
     the best available substitute, and it is a substitute.

Nothing here is a formality. `PROVEN` is empty, and it is empty because nothing
has met this bar yet - not because nobody has got round to filling it in.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class Evidence:
    """The numbers behind one claim, in the form that lets somebody re-check it."""

    trials: int
    hit_rate: float
    control_hit_rate: float
    expectancy_r: float
    control_expectancy_r: float
    #: How many candidates the rule was chosen from. 1 for a pre-registered
    #: hypothesis; the size of the sweep otherwise. This is what turns a
    #: convincing number into an unconvincing one, so it is required.
    comparisons: int
    #: The round-trip cost in R that the expectancy above is already net of.
    cost_r: float
    #: When the hypothesis was written down, and when the data ends. Forward
    #: evidence is data whose end date is after the registration date.
    registered_on: date
    data_ends: date

    #: A significance figure measured directly, for when the proportion test
    #: below is not the test that was actually run.
    #:
    #: Not a convenience. Deriving z from two hit rates assumes the statistic
    #: was a difference of proportions on independent trials. The
    #: cross-sectional claim was a paired mean-R test clustered by instant - a
    #: different statistic on a different unit - and deriving one from the
    #: other gave 1.30 where the measurement gave 3.69. Reporting either as
    #: though it came from the other reports a test nobody ran.
    measured_z: float | None = None
    #: How `measured_z` was arrived at. Required whenever it is set, so a later
    #: reader can disagree with the method rather than inherit a number.
    measured_z_method: str | None = None

    def __post_init__(self) -> None:
        # A measured z with no stated method is a number nobody can check, and
        # this file exists because an unchecked number was believed once.
        if self.measured_z is not None and not (self.measured_z_method or "").strip():
            raise ValueError(
                "a measured z must say how it was measured - an unexplained "
                "significance figure is exactly what this registry exists to "
                "stop being believed"
            )

    @property
    def edge_over_control(self) -> float:
        """The number that matters. Not the hit rate against 0.5."""
        return self.hit_rate - self.control_hit_rate

    @property
    def z_score(self) -> float:
        """The significance of rule against control.

        The measured figure when one was supplied, because the test that was
        run beats the test that can be reconstructed from summary statistics.
        Otherwise a difference of proportions treated as independent - the
        conservative reading, since the two arms run on the same bars and a
        paired test would give a larger z. Overstating the variance can only
        make a claim harder to accept, which is the direction to be wrong in.
        """
        if self.measured_z is not None:
            return self.measured_z
        if self.trials <= 0:
            return 0.0
        p1, p2 = self.hit_rate, self.control_hit_rate
        variance = p1 * (1 - p1) / self.trials + p2 * (1 - p2) / self.trials
        if variance <= 0:
            return 0.0
        return (p1 - p2) / math.sqrt(variance)

    @property
    def required_z(self) -> float:
        """Bonferroni-style correction for how many candidates were tried."""
        if self.comparisons <= 1:
            return 1.96
        return 1.96 * math.sqrt(1 + math.log(self.comparisons))

    @property
    def net_expectancy_r(self) -> float:
        """Expectancy over the control, after the round-trip cost.

        Both subtractions matter. The control's expectancy is what no
        information earned on the same bars; the cost is what the broker takes.
        An edge that survives neither is not an edge.
        """
        return self.expectancy_r - self.control_expectancy_r - self.cost_r

    def as_dict(self) -> dict[str, Any]:
        return {
            "trials": self.trials,
            "hit_rate": round(self.hit_rate, 4),
            "control_hit_rate": round(self.control_hit_rate, 4),
            "edge_over_control": round(self.edge_over_control, 4),
            "z_score": round(self.z_score, 2),
            "z_method": self.measured_z_method or "difference of proportions",
            "required_z": round(self.required_z, 2),
            "comparisons": self.comparisons,
            "expectancy_r": round(self.expectancy_r, 4),
            "control_expectancy_r": round(self.control_expectancy_r, 4),
            "cost_r": round(self.cost_r, 4),
            "net_expectancy_r": round(self.net_expectancy_r, 4),
            "registered_on": self.registered_on.isoformat(),
            "data_ends": self.data_ends.isoformat(),
            "forward": self.data_ends > self.registered_on,
        }


@dataclass(frozen=True)
class Verdict:
    """Whether one claim clears the bar, and every reason it does not."""

    proven: bool
    failures: list[str] = field(default_factory=list)
    passes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"proven": self.proven, "failures": self.failures, "passes": self.passes}


def assess(evidence: Evidence, *, pre_registered: bool) -> Verdict:
    """Run one claim past all five requirements and report each.

    Every failure is returned, not just the first. A claim that fails on three
    counts and is fixed on one is still not an edge, and reporting them one at a
    time invites exactly that loop.
    """
    failures: list[str] = []
    passes: list[str] = []

    if pre_registered:
        passes.append("the hypothesis was registered before the data was read")
    else:
        failures.append(
            "the hypothesis was not pre-registered, so its parameters may have "
            "been chosen to fit the data they were then tested on"
        )

    if evidence.edge_over_control > 0:
        passes.append(
            f"it beats the random control by {evidence.edge_over_control:+.4f}"
        )
    else:
        failures.append(
            f"it does not beat the random control ({evidence.edge_over_control:+.4f}) - "
            "the control is what no information scores on the same bars, and "
            "beating breakeven while not beating the control is beating nothing"
        )

    if evidence.z_score >= evidence.required_z:
        passes.append(
            f"z = {evidence.z_score:.2f} clears the required {evidence.required_z:.2f}"
        )
    else:
        failures.append(
            f"z = {evidence.z_score:.2f} does not clear the required "
            f"{evidence.required_z:.2f} for {evidence.comparisons} comparison(s) - "
            "the difference is not distinguishable from noise"
        )

    if evidence.net_expectancy_r > 0:
        passes.append(f"net of costs it earns {evidence.net_expectancy_r:+.4f} R")
    else:
        failures.append(
            f"net of the control and a {evidence.cost_r:.4f} R round-trip cost it "
            f"earns {evidence.net_expectancy_r:+.4f} R - an edge smaller than the "
            "spread is not a small edge, it is a loss"
        )

    if evidence.data_ends > evidence.registered_on:
        passes.append("it was confirmed on data generated after registration")
    else:
        failures.append(
            "it has only been confirmed on held-out history, not on data "
            "generated after the hypothesis was written down. Held-out history "
            "is the best available substitute, and it is a substitute"
        )

    return Verdict(proven=not failures, failures=failures, passes=passes)


@dataclass(frozen=True)
class ProvenEdge:
    """A registered, surviving edge. Live trading requires at least one."""

    key: str
    description: str
    evidence: Evidence
    pre_registered: bool

    @property
    def verdict(self) -> Verdict:
        return assess(self.evidence, pre_registered=self.pre_registered)

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "description": self.description,
            "evidence": self.evidence.as_dict(),
            "verdict": self.verdict.as_dict(),
        }


#: Every edge this deployment claims. Empty, and honestly so.
#:
#: The mean-reversion result is recorded below as a REJECTED claim rather than
#: left out, because "we tried nothing" and "we tried this and it did not clear
#: the bar" are different facts, and the second one is worth keeping - it is the
#: thing that stops the same rule being re-proposed next month as a new idea.
PROVEN: tuple[ProvenEdge, ...] = ()


#: Claims that cleared every bar except the forward one.
#:
#: Deliberately a third list rather than a flag on PROVEN. "Not yet proven" and
#: "tested and failed" are different states with different next actions - one
#: needs time, the other needs a new idea - and a boolean on one list would let
#: a reader in a hurry treat them as the same thing.
PENDING_FORWARD: tuple[ProvenEdge, ...] = (
    ProvenEdge(
        key="cross-sectional-stretch",
        description=(
            "at each instant, rank every instrument by (close - 50-bar mean) / "
            "ATR(14) and take both tails - long the most extended downward, "
            "short the most extended upward. Market-neutral by construction, "
            "which is what separates it from the twenty-four time-series rules "
            "that failed: those fire on everything at once when the market "
            "moves, so much of what they call a signal is the market. "
            "GENERALISATION FAILED: unchanged on eleven years of daily "
            "bars the same rule scored -0.0015 R against its control at "
            "t = -0.12"
        ),
        pre_registered=True,
        evidence=Evidence(
            # Instants, not trades. 107,045 trades sat inside 11,414 instants
            # and counting each as independent evidence would have been
            # counting one market move nine times over.
            trials=11414,
            # Expressed as a hit rate for the shared Evidence shape; the
            # measurement that matters is the R difference below, taken as a
            # paired mean per instant.
            hit_rate=0.5082,
            control_hit_rate=0.4996,
            expectancy_r=0.0201,
            control_expectancy_r=-0.0010,
            comparisons=1,
            cost_r=0.01,
            registered_on=date(2026, 8, 15),
            # Both halves of this series had already been searched when this
            # was tested. That is why it is here and not in PROVEN.
            data_ends=date(2026, 8, 15),
            # And it did not generalise. Re-run unchanged on eleven years
            # of daily bars - an independent sample nothing had searched,
            # covering COVID, the rate cycle and several currency crises
            # the two-year hourly window does not contain - the same rule
            # scored -0.0015 R against its control at t = -0.12. Not
            # weakly positive: negative.
            #
            # The caveat, stated without leaning on it: 120 daily bars is
            # a six-month hold, which is a different trade rather than the
            # same trade at another scale. But a real effect usually
            # leaves some trace in an adjacent scale, and there is none.
            #
            # Recorded beside the positive figure rather than replacing
            # it. A claim whose supporting evidence is kept and whose
            # contradicting evidence is not is not a claim, it is an
            # advertisement.
            measured_z=3.69,
            measured_z_method=(
                "paired t across 11,414 instants: each instant contributes "
                "the mean R of everything entered then, rule minus control. "
                "Clustered because 107,045 trades sat inside those instants "
                "and counting each as independent evidence counts one market "
                "move nine times over. The unclustered figure was 3.95, so "
                "the overlap inflated significance by 1.1x - small because "
                "pairing rule against control on the same instants already "
                "removes the common market factor"
            ),
        ),
    ),
)


#: Claims that were tested and did not survive. Kept, with their numbers.
REJECTED: tuple[ProvenEdge, ...] = (
    ProvenEdge(
        key="mean-reversion-50",
        description=(
            "enter against the 50-bar mean - below it long, above it short - "
            "with a 2.5x ATR(14) stop, a 1R target and a 120-bar horizon, "
            "tested on the first half of 51 instruments' H1 history"
        ),
        pre_registered=True,
        evidence=Evidence(
            trials=22454,
            hit_rate=0.5084,
            control_hit_rate=0.5032,
            expectancy_r=0.0167,
            control_expectancy_r=0.0064,
            comparisons=1,
            # A typical EURUSD round trip at this stop distance. Approximate,
            # and deliberately not zero: a costed edge that assumes free
            # execution is an uncosted edge.
            cost_r=0.01,
            registered_on=date(2026, 8, 14),
            data_ends=date(2026, 8, 14),
        ),
    ),
)


def live_trading_allowed() -> tuple[bool, str]:
    """Whether any registered edge survives. The gate autopilot asks.

    Returns the reason either way. "No" with no reason is a switch somebody
    flips out of frustration; "no, and here is the arithmetic" is one they can
    argue with.
    """
    surviving = [edge for edge in PROVEN if edge.verdict.proven]
    if surviving:
        return True, f"{len(surviving)} registered edge(s) clear the bar"

    if PENDING_FORWARD:
        pending = PENDING_FORWARD[0]
        failures = pending.verdict.failures
        # Every failure listed rather than summarised. An earlier version of
        # this message asserted "fails only on forward evidence" and quoted a
        # different failure underneath it - the kind of sentence that gets
        # believed instead of read.
        return False, (
            f"no registered edge clears the bar. '{pending.key}' beats its "
            f"control by {pending.evidence.edge_over_control:+.4f} at z = "
            f"{pending.evidence.z_score:.2f} and earns "
            f"{pending.evidence.net_expectancy_r:+.4f} R net of costs, and "
            f"still fails on: {'; '.join(failures)}"
        )

    if REJECTED:
        worst = REJECTED[0]
        return False, (
            "no registered edge clears the bar. The closest claim, "
            f"'{worst.key}', beats its random control by "
            f"{worst.evidence.edge_over_control:+.4f} at z = "
            f"{worst.evidence.z_score:.2f}, against a required "
            f"{worst.evidence.required_z:.2f} - not distinguishable from noise, "
            "and net of costs it earns "
            f"{worst.evidence.net_expectancy_r:+.4f} R"
        )
    return False, "no edge has been registered, so there is nothing to trade on"
