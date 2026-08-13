"""Drift detection and benchmarking (spec phases 33-34, §35-36).

A model does not usually fail loudly. It fails by continuing to answer while
the thing it was trained on stops existing, and every answer looks exactly like
the ones it gave when it was right.

Two kinds of drift, and conflating them is the usual mistake:

**Feature drift** — the inputs have moved. The distribution of volatility, of
spread, of session mix, is not the one the model was trained on. Detectable
without any outcomes at all, which makes it the early warning.

**Concept drift** — the relationship has moved. The inputs look the same and
the mapping from input to outcome no longer holds. Only detectable once
outcomes mature, which makes it the late and expensive one.

A system that watches only the second finds out after it has paid. A system
that watches only the first raises an alarm every time the market has a quiet
week. Both are here, reported separately, and neither is allowed to speak for
the other.

The benchmark below answers the question that makes all of this worth doing: is
the model beating the trivial alternative? A strategy that cannot beat "always
long" over the same window has not been shown to know anything, however good
its Sharpe looks in isolation.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any

# Population Stability Index thresholds. These are the conventional lines from
# credit scoring, where the measure comes from, and they are policy rather than
# measurement - published in the payload so a reader knows a threshold was
# applied rather than a finding reached.
PSI_SHIFTED = 0.1
PSI_BROKEN = 0.25

# Below this many observations in either window, a distribution comparison is
# comparing noise with noise.
MIN_DRIFT_SAMPLE = 50

# Bins for the reference distribution. Ten is enough resolution to see a shift
# and coarse enough that a bin is not one observation wide.
DRIFT_BINS = 10

# A bin with no reference mass makes the PSI term infinite. This floor is a
# numerical guard, not a measurement, and it is applied to both sides so it
# cannot bias the direction of the answer.
_EPSILON = 1e-6


@dataclass
class DriftResult:
    """How far a distribution has moved, or why that cannot be said."""

    available: bool
    metric: str
    reason: str | None = None
    score: float | None = None
    verdict: str | None = None  # "stable" | "shifted" | "broken"
    reference_sample: int = 0
    recent_sample: int = 0
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        if not self.available:
            return {
                "available": False,
                "metric": self.metric,
                "reason": self.reason,
                "reference_sample": self.reference_sample,
                "recent_sample": self.recent_sample,
            }
        return {
            "available": True,
            "metric": self.metric,
            "score": round(self.score, 6) if self.score is not None else None,
            "verdict": self.verdict,
            "reference_sample": self.reference_sample,
            "recent_sample": self.recent_sample,
            "thresholds": {"shifted": PSI_SHIFTED, "broken": PSI_BROKEN},
            "detail": self.detail,
        }


def _unavailable(metric: str, reason: str, ref: int = 0, recent: int = 0) -> DriftResult:
    return DriftResult(
        available=False,
        metric=metric,
        reason=reason,
        reference_sample=ref,
        recent_sample=recent,
    )


def population_stability(
    reference: list[float], recent: list[float], *, bins: int = DRIFT_BINS
) -> DriftResult:
    """PSI between a training window and a recent one.

    Bin edges come from the *reference* quantiles, not from the pooled data.
    Pooling would let the recent window move the edges it is being measured
    against, which is how a genuinely shifted distribution scores as stable.
    """
    if len(reference) < MIN_DRIFT_SAMPLE or len(recent) < MIN_DRIFT_SAMPLE:
        return _unavailable(
            "psi",
            f"{min(len(reference), len(recent))} observations, below the "
            f"{MIN_DRIFT_SAMPLE} a distribution comparison needs",
            len(reference),
            len(recent),
        )

    clean_ref = [v for v in reference if math.isfinite(v)]
    clean_recent = [v for v in recent if math.isfinite(v)]
    if len(clean_ref) < MIN_DRIFT_SAMPLE or len(clean_recent) < MIN_DRIFT_SAMPLE:
        return _unavailable(
            "psi",
            "too many non-finite values to compare the distributions",
            len(clean_ref),
            len(clean_recent),
        )

    ordered = sorted(clean_ref)
    edges = [
        ordered[min(len(ordered) - 1, int(round(q * len(ordered) / bins)))]
        for q in range(1, bins)
    ]
    # Ties collapse quantiles onto one another. A constant reference feature has
    # no distribution to have moved away from, and saying so beats dividing by
    # a bin that does not exist.
    if len(set(edges)) < bins - 1:
        return _unavailable(
            "psi",
            "the reference distribution is too concentrated to bin — it has no "
            "spread for the recent window to have moved away from",
            len(clean_ref),
            len(clean_recent),
        )

    def shares(values: list[float]) -> list[float]:
        counts = [0] * bins
        for value in values:
            index = 0
            while index < len(edges) and value > edges[index]:
                index += 1
            counts[index] += 1
        return [max(c / len(values), _EPSILON) for c in counts]

    ref_shares = shares(clean_ref)
    recent_shares = shares(clean_recent)
    psi = math.fsum(
        (r - e) * math.log(r / e) for r, e in zip(recent_shares, ref_shares, strict=True)
    )

    verdict = "stable"
    if psi >= PSI_BROKEN:
        verdict = "broken"
    elif psi >= PSI_SHIFTED:
        verdict = "shifted"

    return DriftResult(
        available=True,
        metric="psi",
        score=psi,
        verdict=verdict,
        reference_sample=len(clean_ref),
        recent_sample=len(clean_recent),
        detail={
            "reference_shares": [round(s, 4) for s in ref_shares],
            "recent_shares": [round(s, 4) for s in recent_shares],
        },
    )


def concept_drift(
    reference_outcomes: list[float], recent_outcomes: list[float]
) -> DriftResult:
    """Whether the relationship between inputs and outcomes still holds.

    Measured on realised R rather than on hit rate: a model can keep its hit
    rate while its winners shrink and its losers grow, and that is the failure
    that empties an account. Reported as a standardised difference in mean R,
    so the answer carries the sample's own noise rather than being a raw gap.
    """
    if len(reference_outcomes) < MIN_DRIFT_SAMPLE or len(recent_outcomes) < MIN_DRIFT_SAMPLE:
        return _unavailable(
            "mean_r_shift",
            f"{min(len(reference_outcomes), len(recent_outcomes))} matured outcomes, "
            f"below the {MIN_DRIFT_SAMPLE} needed — concept drift can only be seen "
            "once outcomes resolve, which is why it is the late warning",
            len(reference_outcomes),
            len(recent_outcomes),
        )

    ref_mean = statistics.fmean(reference_outcomes)
    recent_mean = statistics.fmean(recent_outcomes)
    ref_var = statistics.pvariance(reference_outcomes)
    recent_var = statistics.pvariance(recent_outcomes)
    error = math.sqrt(
        ref_var / len(reference_outcomes) + recent_var / len(recent_outcomes)
    )

    if error <= 0:
        return _unavailable(
            "mean_r_shift",
            "both windows are constant, so a shift has no scale to be measured on",
            len(reference_outcomes),
            len(recent_outcomes),
        )

    z = (recent_mean - ref_mean) / error
    verdict = "stable"
    # Only degradation counts. A model that suddenly performs better has also
    # changed, but "it started working" is not a reason to pull it, and folding
    # the two directions together would fire the alarm on a good month.
    if z <= -3.0:
        verdict = "broken"
    elif z <= -2.0:
        verdict = "shifted"

    return DriftResult(
        available=True,
        metric="mean_r_shift",
        score=z,
        verdict=verdict,
        reference_sample=len(reference_outcomes),
        recent_sample=len(recent_outcomes),
        detail={
            "reference_mean_r": round(ref_mean, 4),
            "recent_mean_r": round(recent_mean, 4),
            "standard_error": round(error, 6),
            "note": "only degradation is flagged; improvement is a change, not a fault",
        },
    )


# ------------------------------------------------------------------ benchmark


@dataclass
class BenchmarkResult:
    """The model against the trivial alternative, over the same window."""

    available: bool
    reason: str | None = None
    strategy_total_r: float | None = None
    baselines: dict[str, float] = field(default_factory=dict)
    beaten: list[str] = field(default_factory=list)
    lost_to: list[str] = field(default_factory=list)
    sample: int = 0

    @property
    def beats_every_baseline(self) -> bool:
        return self.available and not self.lost_to

    def as_dict(self) -> dict[str, Any]:
        if not self.available:
            return {"available": False, "reason": self.reason, "sample": self.sample}
        return {
            "available": True,
            "sample": self.sample,
            "strategy_total_r": round(self.strategy_total_r, 4)
            if self.strategy_total_r is not None
            else None,
            "baselines": {k: round(v, 4) for k, v in self.baselines.items()},
            "beaten": self.beaten,
            "lost_to": self.lost_to,
            "beats_every_baseline": self.beats_every_baseline,
        }


def benchmark(
    strategy_r: list[float], baselines: dict[str, list[float]]
) -> BenchmarkResult:
    """Compare realised R against each baseline over the same decisions.

    Every baseline must have the same number of observations as the strategy.
    A baseline measured over a different window is measuring a different market,
    and the comparison would be reporting the window as an edge.
    """
    if not strategy_r:
        return BenchmarkResult(available=False, reason="the strategy produced no outcomes")
    if not baselines:
        return BenchmarkResult(
            available=False,
            reason="no baseline to compare against — a return with nothing to beat "
            "is not evidence of skill",
            sample=len(strategy_r),
        )

    mismatched = [
        name for name, series in baselines.items() if len(series) != len(strategy_r)
    ]
    if mismatched:
        return BenchmarkResult(
            available=False,
            reason=(
                f"{', '.join(sorted(mismatched))} cover a different number of decisions "
                "than the strategy — the comparison would report the window as an edge"
            ),
            sample=len(strategy_r),
        )

    total = math.fsum(strategy_r)
    scores = {name: math.fsum(series) for name, series in baselines.items()}
    return BenchmarkResult(
        available=True,
        strategy_total_r=total,
        baselines=scores,
        beaten=sorted(n for n, v in scores.items() if total > v),
        lost_to=sorted(n for n, v in scores.items() if total <= v),
        sample=len(strategy_r),
    )
