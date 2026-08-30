"""When the forward measurement will be able to answer the question.

The question is "when can a real account be connected", and the honest form of
it is not a countdown to yes. It is: **when will there be enough evidence to
answer at all** - because the answer may well be no, and a page counting down
to a date implies otherwise.

Three things decide the date, and only one of them is a choice.

**The unit of evidence is the instant, not the decision.** The rule takes both
tails of one cross-section at one moment: eight decisions taken together on a
market-neutral book are one piece of evidence about one market move, not eight.
The historical measurement learned this the expensive way - 107,045 trades sat
inside 11,414 instants, and counting them as independent would have counted one
move nine times over. Everything here counts instants. The decision count is
published beside it because it is the number that looks bigger, and somebody
will find it eventually; better it appears here, labelled, than gets discovered
later and believed.

**The sample size comes from the spread, not from the edge.** An edge of
+0.0212 R per instant sounds decisive until you see that the per-instant spread
around it is 0.61 R - twenty-nine times larger. That ratio, not the edge, is
what sets how long this takes.

**The arrival rate is observed, never assumed.** Before any instants resolve
there is no rate, so there is no date. A projection built from an assumed rate
would be a forecast of the assumption.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from app.workers.resolve import HORIZON

#: The significance bar. The same 1.96 the edge registry demands.
CONFIDENCE_Z = 1.96

#: Power. 0.84 is 80% - the conventional floor, and the reason the sample is
#: roughly twice what 1.96 alone would suggest.
#:
#: Sizing on 1.96 alone answers "how many instants until an edge of this size
#: would be significant if the estimate landed exactly on the truth", which it
#: will not. Half the time the estimate lands low and the measurement reports
#: nothing on an edge that is really there. Planning to that figure is planning
#: to a coin flip on whether the exercise concludes at all.
POWER_Z = 0.84

#: What the historical measurement found, per instant. Carried here so the
#: projection states its own assumption rather than burying it: this is the
#: sample needed *if the forward edge is the same size as the historical one*,
#: which is precisely the thing under test.
HISTORICAL_EDGE_R = 0.0212
HISTORICAL_T = 3.69
HISTORICAL_INSTANTS = 11414

#: Hours the FX book trades in a week, and so hourly instants per week at full
#: availability. Used to explain the observed rate, never to replace it.
INSTANTS_PER_WEEK_AT_FULL_RATE = 120


def spread_from_t(edge: float, t: float, instants: int) -> float:
    """Recover the per-instant standard deviation from a published t.

    t = mean / (sd / sqrt(n)), so sd = mean * sqrt(n) / t. Derived rather than
    hardcoded because the three inputs are figures the registry actually
    publishes, and a hardcoded spread would quietly stop matching them the
    first time any one of them was revised.
    """
    if t <= 0 or instants <= 0:
        raise ValueError("a spread cannot be recovered from a non-positive t or n")
    return abs(edge) * math.sqrt(instants) / t


def instants_needed(
    edge: float,
    spread: float,
    *,
    confidence_z: float = CONFIDENCE_Z,
    power_z: float = POWER_Z,
) -> int | None:
    """How many instants are needed to detect an edge of this size.

    None for a zero or negative edge: no sample size establishes something that
    is not there, and returning a very large number would read as "keep going"
    rather than as "this is the wrong question".
    """
    if edge <= 0 or spread <= 0:
        return None
    return math.ceil(((confidence_z + power_z) * spread / edge) ** 2)


@dataclass(frozen=True)
class Readiness:
    """How far the forward measurement is from being able to answer."""

    instants_resolved: int
    instants_needed: int | None
    #: The flattering count. Published beside the real one, and labelled.
    decisions_resolved: int
    #: Observed. None until enough time has passed to observe anything.
    instants_per_week: float | None
    answerable_on: date | None
    open_requirements: tuple[str, ...] = ()
    met_requirements: tuple[str, ...] = ()
    #: Bars each decision is scored over. Instants one bar apart share all but
    #: one bar of that window, so consecutive instants are not independent
    #: draws and the instant count is itself an optimistic number.
    horizon_bars: int = HORIZON
    #: The per-instant spread the sample size was actually computed from, and
    #: whether it was measured forward or taken from the historical claim.
    #:
    #: Carried rather than recomputed for display. `as_dict` used to derive the
    #: historical spread on the spot while `assess` accepted one as an
    #: argument, so a measured spread would have changed the date and left the
    #: sentence explaining it still quoting the assumption.
    spread: float = 0.0
    spread_is_measured: bool = False

    @property
    def independent_blocks(self) -> int:
        """Resolved instants that share no part of an outcome window.

        A floor, not an estimate. Two instants one bar apart are scored over
        windows overlapping in 119 of 120 bars, so they largely re-measure one
        market move - the same error as counting eight simultaneous decisions
        as eight, taken along time instead of across the book. The true
        effective sample sits between this and `instants_resolved`; where
        exactly needs the serial correlation measured, which needs more
        resolved instants than exist. Published as a floor so the optimistic
        number is never the only one on the page.
        """
        if self.horizon_bars <= 0:
            return self.instants_resolved
        return self.instants_resolved // self.horizon_bars

    @property
    def fraction(self) -> float | None:
        if not self.instants_needed:
            return None
        return min(1.0, self.instants_resolved / self.instants_needed)

    def as_dict(self) -> dict[str, Any]:
        spread = self.spread or spread_from_t(
            HISTORICAL_EDGE_R, HISTORICAL_T, HISTORICAL_INSTANTS
        )
        return {
            "spread_r": round(spread, 4),
            "spread_is_measured": self.spread_is_measured,
            "instants_resolved": self.instants_resolved,
            "instants_needed": self.instants_needed,
            "fraction": round(self.fraction, 4) if self.fraction is not None else None,
            "decisions_resolved": self.decisions_resolved,
            "independent_blocks": self.independent_blocks,
            "horizon_bars": self.horizon_bars,
            "instants_per_week": (
                round(self.instants_per_week, 1)
                if self.instants_per_week is not None
                else None
            ),
            "answerable_on": (
                self.answerable_on.isoformat() if self.answerable_on else None
            ),
            "open_requirements": list(self.open_requirements),
            "met_requirements": list(self.met_requirements),
            "what_the_date_means": (
                "the date the question can be answered, not the date it is "
                "answered yes. The rule may fail, and on the evidence so far "
                "that is the more likely outcome: re-run unchanged on eleven "
                "years of daily bars it scored -0.0015 R against its control "
                "at t = -0.12"
            ),
            "why_instants": (
                "one cross-section taken at one moment produces both tails at "
                "once, so eight decisions there are one piece of evidence "
                "about one market move rather than eight. The historical "
                "measurement had 107,045 trades inside 11,414 instants, and "
                "counting those as independent counts one move nine times"
            ),
            "why_blocks": (
                f"each decision is scored over {self.horizon_bars} bars, and "
                "instants land one bar apart, so consecutive instants share "
                f"{self.horizon_bars - 1} of those {self.horizon_bars} bars. "
                "They are not independent draws. `independent_blocks` counts "
                "only instants sharing no part of a window - a floor, not an "
                "estimate. The honest reading of `fraction` is that it is an "
                "upper bound on progress"
            ),
            "the_assumption": (
                f"sized for an edge of {HISTORICAL_EDGE_R} R per instant "
                f"against a per-instant spread of {spread:.3f} R, "
                + (
                    "measured from the forward pairs themselves"
                    if self.spread_is_measured
                    else "recovered from the historical claim - which is to "
                    "say the number under test"
                )
                + ". The edge is the historical one either way, so this is "
                "the wait if the forward edge turns out the same size. A "
                "smaller one needs a larger sample and the relationship is "
                "quadratic: half the edge is four times the wait"
            ),
        }


def assess(
    *,
    instants_resolved: int,
    decisions_resolved: int,
    instants_per_week: float | None,
    today: date,
    edge: float = HISTORICAL_EDGE_R,
    spread: float | None = None,
    open_requirements: tuple[str, ...] = (),
    met_requirements: tuple[str, ...] = (),
) -> Readiness:
    """Put the pieces together into a date, or say why there is not one."""
    measured = spread is not None and spread > 0
    if not measured:
        spread = spread_from_t(HISTORICAL_EDGE_R, HISTORICAL_T, HISTORICAL_INSTANTS)
    assert spread is not None

    needed = instants_needed(edge, spread)

    answerable: date | None = None
    if needed is not None and instants_per_week and instants_per_week > 0:
        remaining = max(0, needed - instants_resolved)
        answerable = today + timedelta(weeks=remaining / instants_per_week)

    return Readiness(
        instants_resolved=instants_resolved,
        instants_needed=needed,
        decisions_resolved=decisions_resolved,
        instants_per_week=instants_per_week,
        answerable_on=answerable,
        open_requirements=open_requirements,
        met_requirements=met_requirements,
        spread=spread,
        spread_is_measured=measured,
    )
