"""Probability and calibration (spec phase 20, §19).

The spec is blunt about the thing this module exists to prevent: *do not equate
model confidence with true probability.* Every layer below produces confidence
numbers — a regime margin, a council conviction, a similarity share — and none
of them has earned the word "probability".

So this module does not produce probabilities. It **measures** whether any
score deserves to be treated as one, by scoring past predictions against what
actually happened.

The machinery is standard and deliberately unglamorous:

* **Brier score** — mean squared error of a probabilistic forecast. Lower is
  better; 0.25 is what you get by always saying 50%.
* **Reliability curve** — bucket the forecasts, and for each bucket compare the
  average forecast with the observed frequency. A well-calibrated 70% bucket
  comes true about 70% of the time.
* **Calibration error** — the average gap between those two, weighted by how
  many forecasts landed in each bucket.

Until enough matured outcomes exist, every function here returns
`calibrated: false` with a reason. That is the point: an uncalibrated system
that says so is safe, and one that emits confident percentages is not.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

# Below this many resolved forecasts, no calibration claim is made. Reliability
# needs several forecasts per bucket, and ten buckets is the coarsest split
# that still shows a curve.
MIN_FORECASTS = 100
MIN_PER_BUCKET = 10
BUCKETS = 10


@dataclass
class Forecast:
    """One prediction paired with what actually happened."""

    score: float  # the raw confidence being tested, 0..1
    outcome: bool  # did the predicted direction happen
    source: str = "unknown"  # which layer produced the score


@dataclass
class Bucket:
    lower: float
    upper: float
    count: int
    mean_forecast: float
    observed_rate: float

    @property
    def gap(self) -> float:
        return abs(self.mean_forecast - self.observed_rate)


@dataclass
class CalibrationReport:
    calibrated: bool
    reason: str | None = None
    source: str = "unknown"
    count: int = 0
    brier: float | None = None
    baseline_brier: float | None = None
    skill: float | None = None
    calibration_error: float | None = None
    base_rate: float | None = None
    buckets: list[Bucket] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "calibrated": self.calibrated,
            "reason": self.reason,
            "source": self.source,
            "count": self.count,
            "brier": round(self.brier, 6) if self.brier is not None else None,
            "baseline_brier": (
                round(self.baseline_brier, 6) if self.baseline_brier is not None else None
            ),
            "skill_vs_base_rate": round(self.skill, 6) if self.skill is not None else None,
            "calibration_error": (
                round(self.calibration_error, 6)
                if self.calibration_error is not None
                else None
            ),
            "base_rate": round(self.base_rate, 4) if self.base_rate is not None else None,
            "reliability": [
                {
                    "range": [round(b.lower, 2), round(b.upper, 2)],
                    "count": b.count,
                    "mean_forecast": round(b.mean_forecast, 4),
                    "observed_rate": round(b.observed_rate, 4),
                    "gap": round(b.gap, 4),
                }
                for b in self.buckets
            ],
        }


def brier_score(forecasts: list[Forecast]) -> float:
    """Mean squared error between forecast and outcome."""
    return statistics.fmean([(f.score - (1.0 if f.outcome else 0.0)) ** 2 for f in forecasts])


def evaluate(forecasts: list[Forecast], source: str = "unknown") -> CalibrationReport:
    """Measure whether these scores behave like probabilities."""
    if len(forecasts) < MIN_FORECASTS:
        return CalibrationReport(
            calibrated=False,
            source=source,
            count=len(forecasts),
            reason=(
                f"{len(forecasts)} resolved forecasts, needs {MIN_FORECASTS} before "
                "any calibration claim is meaningful"
            ),
        )

    base_rate = statistics.fmean([1.0 if f.outcome else 0.0 for f in forecasts])
    brier = brier_score(forecasts)

    # The honest yardstick: what you would score by ignoring the model and
    # always predicting the base rate. A model that cannot beat this has no
    # skill, however good its Brier score looks in isolation.
    baseline = statistics.fmean(
        [(base_rate - (1.0 if f.outcome else 0.0)) ** 2 for f in forecasts]
    )
    skill = (baseline - brier) / baseline if baseline > 0 else 0.0

    buckets: list[Bucket] = []
    weighted_gap = 0.0
    counted = 0

    for i in range(BUCKETS):
        lower, upper = i / BUCKETS, (i + 1) / BUCKETS
        is_last = i == BUCKETS - 1
        in_bucket = [
            f
            for f in forecasts
            if lower <= f.score < upper or (is_last and f.score == 1.0)
        ]
        if len(in_bucket) < MIN_PER_BUCKET:
            continue
        mean_forecast = statistics.fmean([f.score for f in in_bucket])
        observed = statistics.fmean([1.0 if f.outcome else 0.0 for f in in_bucket])
        bucket = Bucket(lower, upper, len(in_bucket), mean_forecast, observed)
        buckets.append(bucket)
        weighted_gap += bucket.gap * len(in_bucket)
        counted += len(in_bucket)

    if not buckets:
        return CalibrationReport(
            calibrated=False,
            source=source,
            count=len(forecasts),
            brier=brier,
            baseline_brier=baseline,
            skill=skill,
            base_rate=base_rate,
            reason=(
                "forecasts are too concentrated to form a reliability curve; "
                f"no bucket reached {MIN_PER_BUCKET} samples"
            ),
        )

    return CalibrationReport(
        calibrated=True,
        source=source,
        count=len(forecasts),
        brier=brier,
        baseline_brier=baseline,
        skill=skill,
        calibration_error=weighted_gap / counted,
        base_rate=base_rate,
        buckets=buckets,
    )


def to_probability(score: float, report: CalibrationReport) -> float | None:
    """Map a raw score to a probability — only if calibration allows it.

    Returns None when the source is uncalibrated. That is the whole contract:
    a caller that wants a probability must first prove one exists, and the type
    signature forces it to handle the case where it does not.
    """
    if not report.calibrated or not report.buckets:
        return None

    for bucket in report.buckets:
        if bucket.lower <= score < bucket.upper or (
            bucket.upper >= 1.0 and score >= bucket.upper
        ):
            # The observed frequency in this bucket *is* the empirical
            # probability. No curve fitting: with a few hundred samples a
            # fitted curve would be reading noise.
            return bucket.observed_rate
    return None


def build_forecasts_from_episodes(episodes: list, score_key: str = "conviction") -> list[Forecast]:
    """Turn matured episodes into resolved forecasts.

    Only episodes carrying both a stored score and a realised outcome qualify.
    Episodes without a score were produced before the brain existed, and
    counting them as 50% forecasts would manufacture calibration data out of
    silence.
    """
    out: list[Forecast] = []
    for ep in episodes:
        features = getattr(ep, "features", None) or {}
        score = features.get(score_key)
        forward = getattr(ep, "forward_return_pct", None)
        if score is None or forward is None:
            continue
        out.append(Forecast(score=float(score), outcome=float(forward) > 0, source=score_key))
    return out
