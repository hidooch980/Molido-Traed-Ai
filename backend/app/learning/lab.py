"""The learning lab: walk-forward splits that cannot leak (phase 30, §32).

Every other leakage guard in this system protects a *read*. This one protects
an *experiment*, and experiments leak in ways reads do not.

Three specific ways, all of which produce a backtest that looks excellent and a
live system that does not work:

**Random splits.** A shuffled train/test split on time series lets the model
learn from Thursday to predict Wednesday. The result is not optimistic, it is
meaningless — and it is the single most common way a trading model gets built.
Splits here are contiguous and always forward in time.

**Adjacent folds.** A trade opened at the end of the training window resolves
inside the test window, so the label the model learned from is a fact about the
period it is being tested on. The purge removes training samples whose outcomes
mature after the training window ends.

**Serial correlation across the boundary.** Even after purging, a sample taken
minutes before the test window shares most of its features with the first test
sample. The embargo drops a stretch of training data immediately before each
test fold.

`walk_forward` refuses to produce a split it cannot make safe, rather than
producing a smaller or overlapping one. A fold that cannot be built without
leakage is not a fold worth having, and returning one anyway is how the guard
becomes decorative.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.core.errors import InsufficientDataError, ValidationFailedError


@dataclass(frozen=True)
class Sample:
    """One training example, with the two timestamps that make it safe.

    `event_time` is when the setup existed. `outcome_ready_at` is when its
    label became knowable — which is later, always, and by an amount nobody can
    assume. Without the second, a purge has nothing to purge on.
    """

    sample_id: str
    event_time: datetime
    outcome_ready_at: datetime

    def __post_init__(self) -> None:
        if self.event_time.tzinfo is None or self.outcome_ready_at.tzinfo is None:
            raise ValidationFailedError("sample timestamps must be timezone-aware")
        if self.outcome_ready_at < self.event_time:
            raise ValidationFailedError(
                f"{self.sample_id} resolves before it happens"
            )


@dataclass
class Fold:
    """One train/test pair, and the evidence that it is clean."""

    index: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    train: tuple[str, ...] = ()
    test: tuple[str, ...] = ()
    purged: tuple[str, ...] = ()
    embargoed: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "train_start": self.train_start.isoformat(),
            "train_end": self.train_end.isoformat(),
            "test_start": self.test_start.isoformat(),
            "test_end": self.test_end.isoformat(),
            "train_size": len(self.train),
            "test_size": len(self.test),
            "purged": len(self.purged),
            "embargoed": len(self.embargoed),
        }


@dataclass
class WalkForwardPlan:
    folds: list[Fold] = field(default_factory=list)
    embargo: timedelta = timedelta(0)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "folds": [f.as_dict() for f in self.folds],
            "embargo_seconds": self.embargo.total_seconds(),
            "notes": self.notes,
            "total_purged": sum(len(f.purged) for f in self.folds),
            "total_embargoed": sum(len(f.embargoed) for f in self.folds),
        }


def walk_forward(
    samples: list[Sample],
    *,
    folds: int,
    embargo: timedelta,
    min_train: int = 100,
    min_test: int = 20,
) -> WalkForwardPlan:
    """Contiguous, forward-only folds with purging and an embargo.

    The test windows tile the back of the series and each training window is
    everything before its test window — expanding rather than sliding, because
    a sliding window throws away the older regimes that are the only evidence
    of how the strategy behaves in conditions the recent data does not contain.
    """
    if folds < 1:
        raise ValidationFailedError("a walk-forward needs at least one fold")
    if embargo < timedelta(0):
        raise ValidationFailedError("an embargo cannot run backwards")

    ordered = sorted(samples, key=lambda s: (s.event_time, s.sample_id))
    if len(ordered) < min_train + folds * min_test:
        raise InsufficientDataError(
            f"{len(ordered)} samples cannot support {folds} folds of at least "
            f"{min_test} test samples after a {min_train}-sample training minimum",
            samples=len(ordered),
            folds=folds,
        )

    test_width = (len(ordered) - min_train) // folds
    plan = WalkForwardPlan(embargo=embargo)

    for index in range(folds):
        test_lo = min_train + index * test_width
        test_hi = test_lo + test_width if index < folds - 1 else len(ordered)
        test_slice = ordered[test_lo:test_hi]
        if len(test_slice) < min_test:
            raise InsufficientDataError(
                f"fold {index} would test on {len(test_slice)} samples, below "
                f"the {min_test} minimum",
                fold=index,
            )

        test_start = test_slice[0].event_time
        test_end = test_slice[-1].event_time
        embargo_start = test_start - embargo

        train: list[str] = []
        purged: list[str] = []
        embargoed: list[str] = []
        for candidate in ordered[:test_lo]:
            # Purge first: a sample whose outcome matures inside the test window
            # carries a fact about the period being tested, whatever else is
            # true of it.
            if candidate.outcome_ready_at >= test_start:
                purged.append(candidate.sample_id)
                continue
            # Then embargo: even a fully-resolved sample taken minutes before
            # the boundary shares most of its features with the first test
            # sample, so the model can recognise rather than predict it.
            if embargo > timedelta(0) and candidate.event_time >= embargo_start:
                embargoed.append(candidate.sample_id)
                continue
            train.append(candidate.sample_id)

        if not train:
            raise InsufficientDataError(
                f"fold {index} has no training samples left after purge and embargo — "
                "a fold that cannot be made clean is not a fold",
                fold=index,
                purged=len(purged),
                embargoed=len(embargoed),
            )

        plan.folds.append(
            Fold(
                index=index,
                train_start=ordered[0].event_time,
                train_end=ordered[test_lo - 1].event_time,
                test_start=test_start,
                test_end=test_end,
                train=tuple(train),
                test=tuple(s.sample_id for s in test_slice),
                purged=tuple(purged),
                embargoed=tuple(embargoed),
            )
        )

    if embargo == timedelta(0):
        plan.notes.append(
            "no embargo was applied — samples immediately before each test window "
            "share most of their features with it"
        )
    return plan


def assert_no_leakage(plan: WalkForwardPlan, samples: list[Sample]) -> None:
    """Prove the plan is clean, rather than trusting that it was built cleanly.

    Checked against the samples rather than against the plan's own bookkeeping:
    a builder that made a mistake would record the mistake consistently, and a
    verification that reads the same bookkeeping would agree with it.
    """
    by_id = {s.sample_id: s for s in samples}

    for fold in plan.folds:
        overlap = set(fold.train) & set(fold.test)
        if overlap:
            raise ValidationFailedError(
                f"fold {fold.index} trains and tests on the same samples: "
                f"{sorted(overlap)[:5]}",
                fold=fold.index,
            )
        for sample_id in fold.train:
            sample = by_id.get(sample_id)
            if sample is None:
                raise ValidationFailedError(f"fold {fold.index} trains on unknown {sample_id}")
            if sample.event_time >= fold.test_start:
                raise ValidationFailedError(
                    f"fold {fold.index} trains on {sample_id}, which happened inside "
                    "its own test window",
                    fold=fold.index,
                )
            if sample.outcome_ready_at >= fold.test_start:
                raise ValidationFailedError(
                    f"fold {fold.index} trains on {sample_id}, whose outcome matures "
                    "inside the test window",
                    fold=fold.index,
                )
