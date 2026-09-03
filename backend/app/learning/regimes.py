"""When the cross-section is a cross-section, and when it is just the market.

The 21-year daily measurement says the rule earns +0.108 R over its control
at t = 5.63, and that the number is made almost entirely by 2017, 2018 and
2024 while 2006, 2014 and 2025 are significantly negative. A spread that wide
is not a rule with an edge; it is a rule whose edge is conditional on
something, and the question is what.

This module proposes one answer and tests it in the only way that means
anything.

**The hypothesis, stated before the split is read.** `cross-sectional-stretch`
ranks every instrument by how far its close sits from its own mean in ATRs and
takes both tails. It claims to be market-neutral by construction: long the most
extended downward, short the most extended upward, so a move that lifts
everything cancels. That claim has a precondition nobody had tested - the
instruments have to actually differ. When every stretch is the same sign and
size, the tails are not two ends of a cross-section, they are two arbitrary
picks from one common move, and the rule is trading the market while believing
it is hedged.

So: **the edge should be larger when the dispersion of the stretch across the
universe is high, and smaller or absent when it is low.** That is an economic
statement about what the rule is, not a parameter looking for a value.

**Nothing here is fitted to the answer.** The feature is built from the rule's
own inputs - the same closes and the same ATR, cut at the same instant - so it
adds no data and cannot look ahead. The threshold is the median of the feature
*over the training period only*, which is one pre-specified choice rather than
a sweep, and it is then applied unchanged to a test period the choice never
saw. The test result is reported whatever it says.

**What would falsify it.** If the high-dispersion half of the test period does
not beat the low-dispersion half, the hypothesis is wrong and the filter is
not built. That is the outcome this module is designed to be able to return.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.brain import crosssection
from app.learning.measure import Bar
from app.learning.robustness import Row, paired

#: The training share. The threshold is chosen on the first 60% of instants
#: and never revised; the last 40% is the test. Chosen before any of this was
#: run, and stated here rather than passed, because a split fraction that can
#: be tuned is a second parameter.
TRAIN_FRACTION = 0.6

#: Below this many instants a half is not worth a verdict.
MIN_HALF = 200


@dataclass(frozen=True)
class Feature:
    """One instant's regime reading, from what the rule itself saw."""

    at: datetime
    #: Spread of the stretch across the ranked universe: the standard
    #: deviation of (close - 50-bar mean) / ATR over the instruments priced
    #: at this instant. High means the instruments genuinely differ.
    dispersion: float
    #: How many instruments the reading is built from. A dispersion over four
    #: names is not a cross-section.
    breadth: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "at": self.at.isoformat(),
            "dispersion": round(self.dispersion, 4),
            "breadth": self.breadth,
        }


def _stretches_at(
    series: dict[str, list[Bar]],
    index_of: dict[str, dict[datetime, int]],
    at: datetime,
    universe: frozenset[str],
) -> list[float]:
    """Every instrument's stretch at this instant, cut point-in-time.

    The cut is the same one `measure` makes: bars up to and including `at`,
    nothing after. Recomputed here rather than carried out of the measurement
    because the measurement does not keep it - and recomputing from the same
    functions the rule uses is what makes this a reading of the rule's own
    input rather than a second opinion about the market.
    """
    out: list[float] = []
    for symbol in sorted(universe):
        position = index_of.get(symbol, {}).get(at)
        if position is None:
            continue
        bars = series[symbol][: position + 1]
        if len(bars) < crosssection.MEAN_WINDOW + 2:
            continue
        closes = [bar.close for bar in bars]
        atr = crosssection.average_true_range(
            [(bar.high, bar.low, bar.close) for bar in bars]
        )
        if not atr or atr <= 0:
            continue
        stretch = crosssection.stretch_of(closes, atr)
        if stretch is not None:
            out.append(stretch)
    return out


def features(
    series: dict[str, list[Bar]],
    instants: Sequence[datetime],
    *,
    universe: frozenset[str],
    min_breadth: int = crosssection.MIN_CROSS_SECTION,
) -> dict[datetime, Feature]:
    """The regime reading at each instant the measurement scored.

    Instants whose cross-section is thinner than `min_breadth` are left out
    rather than given a dispersion computed from a handful of names: the
    hypothesis is about the shape of a cross-section, and four instruments do
    not have one. `regime_segments` counts what is left out as `unknown`,
    which is where they belong.
    """
    index_of = {
        symbol: {bar.at: i for i, bar in enumerate(bars)}
        for symbol, bars in series.items()
    }
    out: dict[datetime, Feature] = {}
    for at in instants:
        stretches = _stretches_at(series, index_of, at, universe)
        if len(stretches) < min_breadth:
            continue
        mean = sum(stretches) / len(stretches)
        variance = sum((s - mean) ** 2 for s in stretches) / (len(stretches) - 1)
        out[at] = Feature(at=at, dispersion=math.sqrt(variance), breadth=len(stretches))
    return out


@dataclass(frozen=True)
class Half:
    """One side of the threshold, scored on its own instants."""

    name: str
    instants: int
    edge_r: float
    t: float
    #: Standard deviation of this half's paired differences. Kept because the
    #: question the whole module asks is whether the two halves *differ*, and
    #: that needs each half's spread, not just its mean.
    spread_r: float = 0.0

    @property
    def standard_error(self) -> float:
        if self.instants < 2 or self.spread_r <= 0:
            return 0.0
        return self.spread_r / math.sqrt(self.instants)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "instants": self.instants,
            "edge_r": round(self.edge_r, 4),
            "t": round(self.t, 2),
        }


def separation_t(high: Half, low: Half) -> float:
    """Welch's t for the difference between the two halves.

    The statistic that matters, and the one an earlier version of this module
    did not compute. Requiring only that the high half's own edge clear 1.96
    lets any genuinely positive unconditional edge "confirm" a regime that
    carries nothing: the high half inherits the edge, the separation lands
    positive by coin flip, and a random feature is reported as a filter. A
    test that a real edge passes regardless of the regime is not a test of
    the regime.

    Welch rather than pooled because the two halves have no reason to share a
    variance - that is close to the hypothesis being tested.
    """
    error = math.sqrt(high.standard_error**2 + low.standard_error**2)
    if error <= 0:
        return 0.0
    return (high.edge_r - low.edge_r) / error


@dataclass
class RegimeTest:
    """The whole protocol, and what it concluded.

    Both periods are reported. A filter that looks good in training and does
    nothing in test is the thing this exists to catch, and hiding the training
    number would make that failure look like a weak result rather than an
    overfit one.
    """

    threshold: float
    train_high: Half
    train_low: Half
    test_high: Half
    test_low: Half
    train_window: tuple[datetime, datetime] | None = None
    test_window: tuple[datetime, datetime] | None = None
    unknown_instants: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def train_separation(self) -> float:
        return self.train_high.edge_r - self.train_low.edge_r

    @property
    def test_separation(self) -> float:
        return self.test_high.edge_r - self.test_low.edge_r

    @property
    def testable(self) -> bool:
        return min(self.test_high.instants, self.test_low.instants) >= MIN_HALF

    @property
    def test_separation_t(self) -> float:
        return separation_t(self.test_high, self.test_low)

    @property
    def train_separation_t(self) -> float:
        return separation_t(self.train_high, self.train_low)

    @property
    def confirmed(self) -> bool:
        """Whether the held-out period supports the hypothesis.

        Four conditions, all required:

        - the test period is thick enough to judge;
        - the **separation** between the halves is itself distinguishable from
          zero, which is the hypothesis. Without this, any genuinely positive
          unconditional edge confirms any random feature about half the time:
          the high half inherits the edge and the separation lands positive by
          coin flip;
        - the high half beats the low half rather than the other way round;
        - and the high half's own edge is positive and significant, because a
          separation made of the low half being badly negative while the high
          half is no better than nothing is not a filter to trade - it is a
          reason not to trade at all.
        """
        return (
            self.testable
            and abs(self.test_separation_t) >= 1.96
            and self.test_separation > 0
            and self.test_high.edge_r > 0
            and abs(self.test_high.t) >= 1.96
        )

    @property
    def verdict(self) -> str:
        if not self.testable:
            return "UNTESTABLE"
        if not self.confirmed:
            return "NOT_CONFIRMED_OUT_OF_SAMPLE"
        return "CONFIRMED_OUT_OF_SAMPLE"

    def as_dict(self) -> dict[str, Any]:
        return {
            "hypothesis": (
                "the rule is market-neutral only when the instruments differ; "
                "its edge should be larger when the dispersion of the stretch "
                "across the universe is high"
            ),
            "threshold": round(self.threshold, 4),
            "threshold_chosen_on": "the median dispersion of the training period only",
            "train": {
                "window": [w.isoformat() for w in self.train_window] if self.train_window else None,
                "high": self.train_high.as_dict(),
                "low": self.train_low.as_dict(),
                "separation_r": round(self.train_separation, 4),
                "separation_t": round(self.train_separation_t, 2),
            },
            "test": {
                "window": [w.isoformat() for w in self.test_window] if self.test_window else None,
                "high": self.test_high.as_dict(),
                "low": self.test_low.as_dict(),
                "separation_r": round(self.test_separation, 4),
                "separation_t": round(self.test_separation_t, 2),
            },
            "unknown_instants": self.unknown_instants,
            "verdict": self.verdict,
            "notes": self.notes,
            "note": (
                "the threshold was chosen on the training period and applied "
                "unchanged to the test period. The training numbers are printed "
                "beside the test ones because a filter that works only in "
                "training is an overfit, and hiding the comparison would make "
                "that look like a weak result instead"
            ),
        }


def _score(rows: Sequence[Row], name: str) -> Half:
    edge, t, n = paired(rows)
    spread = 0.0
    if n > 1:
        differences = [rule - control for _at, rule, control in rows]
        mean = sum(differences) / n
        spread = math.sqrt(sum((d - mean) ** 2 for d in differences) / (n - 1))
    return Half(name=name, instants=n, edge_r=edge, t=t, spread_r=spread)


def test_dispersion_regime(
    rows: Sequence[Row],
    readings: dict[datetime, Feature],
    *,
    train_fraction: float = TRAIN_FRACTION,
) -> RegimeTest:
    """Choose the threshold on the training period, judge it on the test one.

    `rows` are the measurement's paired instants; `readings` the regime
    feature at each. Instants with no reading take no part in either half and
    are counted, because a filter evaluated only on the instants it could
    classify is a filter evaluated on a sample it selected.
    """
    ordered = sorted((r for r in rows if r[0] in readings), key=lambda r: r[0])
    unknown = len(rows) - len(ordered)
    if len(ordered) < 2 * MIN_HALF:
        empty = Half(name="", instants=0, edge_r=0.0, t=0.0)
        return RegimeTest(
            threshold=0.0,
            train_high=empty,
            train_low=empty,
            test_high=empty,
            test_low=empty,
            unknown_instants=unknown,
            notes=[
                f"only {len(ordered)} instants carry a regime reading, which is "
                f"fewer than the {2 * MIN_HALF} a split needs"
            ],
        )

    cut = int(len(ordered) * train_fraction)
    train, test = ordered[:cut], ordered[cut:]

    # The threshold: the median of the training period, and nothing else. One
    # pre-specified choice. A sweep over thresholds here would be choosing the
    # filter to fit the training data and then reporting a test number that
    # had already been spent.
    train_values = sorted(readings[row[0]].dispersion for row in train)
    threshold = train_values[len(train_values) // 2]

    def split(rows_in: Sequence[Row]) -> tuple[list[Row], list[Row]]:
        high = [r for r in rows_in if readings[r[0]].dispersion >= threshold]
        low = [r for r in rows_in if readings[r[0]].dispersion < threshold]
        return high, low

    train_high, train_low = split(train)
    test_high, test_low = split(test)

    return RegimeTest(
        threshold=threshold,
        train_high=_score(train_high, "train high dispersion"),
        train_low=_score(train_low, "train low dispersion"),
        test_high=_score(test_high, "test high dispersion"),
        test_low=_score(test_low, "test low dispersion"),
        train_window=(train[0][0], train[-1][0]),
        test_window=(test[0][0], test[-1][0]),
        unknown_instants=unknown,
    )


__all__ = [
    "MIN_HALF",
    "separation_t",
    "TRAIN_FRACTION",
    "Feature",
    "Half",
    "RegimeTest",
    "features",
    "test_dispersion_regime",
]
