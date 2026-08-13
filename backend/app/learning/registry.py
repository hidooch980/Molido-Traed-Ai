"""Model registry and champion/challenger (spec phases 31-32, §33-34).

A model that cannot be traced back to the data that made it is not a model, it
is a number generator with good manners. So a registered version carries its
lineage — the feature set, the training window, the code that produced it — and
the registry refuses a version that cannot state all three.

The promotion rule is where this module earns its place. Two ways a challenger
gets promoted in practice, both wrong:

**It beat the champion.** On what sample? A challenger evaluated on fewer
trades than the champion is not a comparison, and the smaller sample is the one
more likely to show a large edge by accident. Promotion requires a minimum
sample *and* an overlap: both models must have been scored on the same
decisions, or they were scored on different markets.

**It beat the champion by a bit.** An edge inside the noise of the measurement
is not an edge. The margin required scales with the sample, so a challenger
that wins by two points over sixty trades does not displace anything.

A challenger runs in shadow: it scores the same decisions the champion scores,
its outputs are recorded, and nothing it says reaches execution. That is the
whole point — the only honest way to know whether a model would have worked is
to let it be wrong where it costs nothing.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.core.errors import ValidationFailedError

# Below this many scored decisions a comparison is not a comparison. Sixty is
# where the standard error on a difference in hit rate falls under about six
# points, which is the smallest margin worth acting on.
MIN_EVALUATION_SAMPLE = 60

# How much of the two samples must be the same decisions. Two models scored on
# different weeks were scored on different markets, and the difference between
# them is mostly the weeks.
MIN_OVERLAP = 0.8

# Multiples of the standard error of the difference. A challenger inside this
# band has not been shown to be better, it has been shown to be similar.
PROMOTION_SIGMA = 2.0


class ModelStage(StrEnum):
    """Where a version sits. The order is the only path through it."""

    REGISTERED = "registered"
    SHADOW = "shadow"
    CHAMPION = "champion"
    RETIRED = "retired"


@dataclass(frozen=True)
class Lineage:
    """What made this model, in enough detail to make it again.

    Every field is required. A lineage with optional fields is a lineage that
    will be half-filled, and half a lineage answers no question worth asking.
    """

    feature_set: tuple[str, ...]
    train_start: datetime
    train_end: datetime
    # The as-of timestamp the training reads were taken at. Separate from
    # `train_end` because they answer different questions: which bars the model
    # saw, and what was known when it saw them.
    as_of: datetime
    code_version: str
    dataset_quality_score: float

    def __post_init__(self) -> None:
        if not self.feature_set:
            raise ValidationFailedError("a model trained on no features has no lineage")
        for name, moment in (
            ("train_start", self.train_start),
            ("train_end", self.train_end),
            ("as_of", self.as_of),
        ):
            if moment.tzinfo is None:
                raise ValidationFailedError(f"{name} must be timezone-aware")
        if self.train_end <= self.train_start:
            raise ValidationFailedError("the training window ends before it starts")
        # The knowledge cutoff cannot precede the last bar the model was shown:
        # that combination means the model saw a bar before it was knowable.
        if self.as_of < self.train_end:
            raise ValidationFailedError(
                "as_of precedes train_end — the model was shown bars that were not "
                "yet known at its stated knowledge cutoff"
            )
        if not self.code_version.strip():
            raise ValidationFailedError("a model must name the code that produced it")

    @property
    def fingerprint(self) -> str:
        """Stable id for "the same model, trained the same way"."""
        material = "|".join(
            [
                ",".join(sorted(self.feature_set)),
                self.train_start.isoformat(),
                self.train_end.isoformat(),
                self.as_of.isoformat(),
                self.code_version,
            ]
        )
        return hashlib.sha256(material.encode()).hexdigest()[:16]

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature_set": list(self.feature_set),
            "train_start": self.train_start.isoformat(),
            "train_end": self.train_end.isoformat(),
            "as_of": self.as_of.isoformat(),
            "code_version": self.code_version,
            "dataset_quality_score": self.dataset_quality_score,
            "fingerprint": self.fingerprint,
        }


@dataclass
class Evaluation:
    """How a version scored, and on which decisions.

    `decision_ids` rather than only a count: the identity of the sample is what
    makes two evaluations comparable, and a count cannot tell you whether two
    models saw the same market.
    """

    decision_ids: tuple[str, ...]
    hits: int
    total_r: float

    def __post_init__(self) -> None:
        if self.hits < 0 or self.hits > len(self.decision_ids):
            raise ValidationFailedError(
                f"{self.hits} hits out of {len(self.decision_ids)} decisions"
            )

    @property
    def sample(self) -> int:
        return len(self.decision_ids)

    @property
    def hit_rate(self) -> float | None:
        return self.hits / self.sample if self.sample else None

    @property
    def average_r(self) -> float | None:
        return self.total_r / self.sample if self.sample else None


@dataclass
class ModelVersion:
    name: str
    version: int
    lineage: Lineage
    stage: ModelStage = ModelStage.REGISTERED
    registered_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    evaluation: Evaluation | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.name}:v{self.version}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "version": self.version,
            "stage": self.stage.value,
            "registered_at": self.registered_at.isoformat(),
            "lineage": self.lineage.as_dict(),
            "sample": self.evaluation.sample if self.evaluation else 0,
            "hit_rate": self.evaluation.hit_rate if self.evaluation else None,
            "average_r": self.evaluation.average_r if self.evaluation else None,
            "notes": self.notes,
        }


@dataclass
class PromotionDecision:
    """Whether the challenger displaces the champion, and why not if not."""

    promote: bool
    reason: str
    margin: float | None = None
    standard_error: float | None = None
    overlap: float | None = None
    challenger_sample: int = 0
    champion_sample: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "promote": self.promote,
            "reason": self.reason,
            "margin": round(self.margin, 6) if self.margin is not None else None,
            "standard_error": (
                round(self.standard_error, 6) if self.standard_error is not None else None
            ),
            "overlap": round(self.overlap, 4) if self.overlap is not None else None,
            "challenger_sample": self.challenger_sample,
            "champion_sample": self.champion_sample,
            "required_sigma": PROMOTION_SIGMA,
        }


def _standard_error(a: Evaluation, b: Evaluation) -> float | None:
    """SE of the difference in hit rate between two independent samples."""
    if not a.sample or not b.sample:
        return None
    pa = a.hits / a.sample
    pb = b.hits / b.sample
    variance = pa * (1 - pa) / a.sample + pb * (1 - pb) / b.sample
    return math.sqrt(variance) if variance > 0 else 0.0


def compare(champion: ModelVersion, challenger: ModelVersion) -> PromotionDecision:
    """Decide whether the challenger has actually been shown to be better.

    Three gates, and the order is deliberate: a sample too small to measure
    makes the other two questions meaningless, and a sample that does not
    overlap makes the margin a statement about the weeks rather than the models.
    """
    champ_eval = champion.evaluation
    chall_eval = challenger.evaluation

    if champ_eval is None or chall_eval is None:
        return PromotionDecision(
            promote=False,
            reason="both versions must have been evaluated before they can be compared",
        )

    if chall_eval.sample < MIN_EVALUATION_SAMPLE or champ_eval.sample < MIN_EVALUATION_SAMPLE:
        return PromotionDecision(
            promote=False,
            reason=(
                f"{min(chall_eval.sample, champ_eval.sample)} scored decisions, below "
                f"the {MIN_EVALUATION_SAMPLE} a comparison needs"
            ),
            challenger_sample=chall_eval.sample,
            champion_sample=champ_eval.sample,
        )

    shared = set(chall_eval.decision_ids) & set(champ_eval.decision_ids)
    overlap = len(shared) / max(chall_eval.sample, champ_eval.sample)
    if overlap < MIN_OVERLAP:
        return PromotionDecision(
            promote=False,
            reason=(
                f"the two were scored on {overlap:.0%} of the same decisions — below "
                f"{MIN_OVERLAP:.0%} they were scored on different markets, and the "
                "difference between them is mostly the weeks"
            ),
            overlap=overlap,
            challenger_sample=chall_eval.sample,
            champion_sample=champ_eval.sample,
        )

    champ_rate = champ_eval.hit_rate or 0.0
    chall_rate = chall_eval.hit_rate or 0.0
    margin = chall_rate - champ_rate
    error = _standard_error(champ_eval, chall_eval)

    if error is None:
        return PromotionDecision(
            promote=False,
            reason="the difference has no measurable error, so it cannot be judged",
            margin=margin,
            overlap=overlap,
        )

    required = PROMOTION_SIGMA * error
    if margin <= required:
        return PromotionDecision(
            promote=False,
            reason=(
                f"the challenger is {margin:+.1%} ahead, inside the {required:.1%} "
                f"needed at {PROMOTION_SIGMA:.0f} standard errors — similar, not better"
            ),
            margin=margin,
            standard_error=error,
            overlap=overlap,
            challenger_sample=chall_eval.sample,
            champion_sample=champ_eval.sample,
        )

    return PromotionDecision(
        promote=True,
        reason=(
            f"the challenger is {margin:+.1%} ahead over {chall_eval.sample} shared "
            f"decisions, beyond the {required:.1%} the sample can produce by chance"
        ),
        margin=margin,
        standard_error=error,
        overlap=overlap,
        challenger_sample=chall_eval.sample,
        champion_sample=champ_eval.sample,
    )


class ModelRegistry:
    """Versions, stages and the rule that only one champion exists.

    In-memory. A deployment backs it with a table, and the "one champion per
    name" rule becomes a partial unique index — which is what actually enforces
    it under concurrency, not this class.
    """

    def __init__(self) -> None:
        self._versions: dict[str, ModelVersion] = {}
        self._next_version: dict[str, int] = {}

    def register(
        self, name: str, lineage: Lineage, *, notes: list[str] | None = None
    ) -> ModelVersion:
        version = self._next_version.get(name, 1)
        self._next_version[name] = version + 1
        record = ModelVersion(
            name=name, version=version, lineage=lineage, notes=list(notes or [])
        )
        self._versions[record.key] = record
        return record

    def get(self, key: str) -> ModelVersion | None:
        return self._versions.get(key)

    def champion(self, name: str) -> ModelVersion | None:
        for record in self._versions.values():
            if record.name == name and record.stage is ModelStage.CHAMPION:
                return record
        return None

    def shadows(self, name: str) -> list[ModelVersion]:
        return [
            r for r in self._versions.values()
            if r.name == name and r.stage is ModelStage.SHADOW
        ]

    def start_shadow(self, key: str) -> ModelVersion:
        record = self._require(key)
        if record.stage is not ModelStage.REGISTERED:
            raise ValidationFailedError(
                f"{key} is {record.stage.value}; only a registered version enters shadow"
            )
        record.stage = ModelStage.SHADOW
        return record

    def promote(self, key: str, *, decision: PromotionDecision) -> ModelVersion:
        """Promote a shadow to champion. Refuses without a passing decision.

        The decision object is required rather than a boolean flag so a caller
        cannot promote by asserting; it has to have run the comparison, and the
        comparison is what carries the sample and the margin.
        """
        record = self._require(key)
        if not decision.promote:
            raise ValidationFailedError(
                f"{key} was not promoted: {decision.reason}", key=key
            )
        if record.stage is not ModelStage.SHADOW:
            raise ValidationFailedError(
                f"{key} is {record.stage.value}; a champion is promoted out of shadow, "
                "so it has been wrong somewhere it cost nothing first"
            )
        previous = self.champion(record.name)
        if previous is not None:
            previous.stage = ModelStage.RETIRED
            previous.notes.append(f"retired in favour of {record.key}: {decision.reason}")
        record.stage = ModelStage.CHAMPION
        record.notes.append(decision.reason)
        return record

    def retire(self, key: str, reason: str) -> ModelVersion:
        record = self._require(key)
        record.stage = ModelStage.RETIRED
        record.notes.append(reason)
        return record

    def _require(self, key: str) -> ModelVersion:
        record = self._versions.get(key)
        if record is None:
            raise ValidationFailedError(f"no such model version: {key}")
        return record

    def as_dict(self) -> dict[str, Any]:
        return {"versions": [v.as_dict() for v in self._versions.values()]}
