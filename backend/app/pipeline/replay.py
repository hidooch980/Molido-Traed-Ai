"""Decision replay and what-if (spec phases 41-42, §41-42).

Replay is the payoff for the point-in-time layer. Because every historical read
goes through `get_bars(as_of)`, and a bar is visible only once it has closed
*and* been ingested, re-running a decision at its original `as_of` has to
reproduce it exactly — including the revisions that had not arrived yet. If it
does not, something upstream is reading the present, and `verify_determinism`
is what turns that from a belief into a failing test.

What-if is the same machinery pointed sideways: re-run the chain with one input
changed and report what moved. Two rules keep it from becoming fiction:

**A what-if re-runs the gates; it does not re-score the answer.** Adjusting a
stored verdict would let the analysis disagree with what the system would
actually have done, which is worse than no analysis.

**A what-if cannot know the market's reply.** Changing the size or the stop
changes where the position sits, and the bars in the database are the bars that
happened with the *original* decision, not this one. For size the difference is
proportional and honest; for a moved stop it is not, and this module says so
rather than producing a tidy number.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import Timeframe
from app.core.errors import ValidationFailedError
from app.pipeline.decide import DecisionTrace, decide

# Inputs a what-if may change and still describe something the system would
# genuinely have done. Anything outside this set changes where the position
# sits in the market, and the recorded bars are the bars that happened under
# the original decision.
PROPORTIONAL_INPUTS = frozenset({"account", "health", "open_positions", "correlations"})

# Inputs that move the levels themselves. Permitted, but the result carries a
# caveat rather than a claim: nothing in the data says how the market would
# have treated a stop that was never there.
LEVEL_INPUTS = frozenset({"r_value_pct", "costs", "measured_correlation", "history"})


@dataclass
class StoredTrace:
    """A decision as it was made, with everything needed to make it again."""

    trace_id: uuid.UUID
    instrument_id: uuid.UUID
    timeframe: Timeframe
    as_of: datetime
    inputs: dict[str, Any]
    trace: DecisionTrace

    def as_dict(self) -> dict[str, Any]:
        return {
            "trace_id": str(self.trace_id),
            "instrument_id": str(self.instrument_id),
            "timeframe": self.timeframe.value,
            "as_of": self.as_of.isoformat(),
            "decision": self.trace.as_dict(),
        }


class TraceStore:
    """Every decision the system made, keyed by id.

    In-memory here. A deployment backs it with a table, and the value of that
    table is not audit for its own sake: it is that a decision six months old
    can be re-run against the data as it stood, and the answer compared with
    what was actually done.
    """

    def __init__(self) -> None:
        self._traces: dict[uuid.UUID, StoredTrace] = {}

    def record(
        self,
        trace: DecisionTrace,
        *,
        instrument_id: uuid.UUID,
        inputs: dict[str, Any],
    ) -> StoredTrace:
        stored = StoredTrace(
            trace_id=uuid.uuid4(),
            instrument_id=instrument_id,
            timeframe=trace.timeframe,
            as_of=trace.as_of,
            inputs=dict(inputs),
            trace=trace,
        )
        self._traces[stored.trace_id] = stored
        return stored

    def get(self, trace_id: uuid.UUID) -> StoredTrace | None:
        return self._traces.get(trace_id)

    def all(self) -> list[StoredTrace]:
        return sorted(self._traces.values(), key=lambda s: s.as_of)

    def stopped_at_counts(self) -> dict[str, int]:
        """Where decisions die, across the whole store.

        The single most useful view in the system for an operator: "nothing
        traded this week" becomes "forty-one decisions died at calibration and
        three at the daily loss limit", which is a sentence somebody can act on.
        """
        counts: dict[str, int] = {}
        for stored in self._traces.values():
            key = stored.trace.stopped_at or "reached_intent"
            counts[key] = counts.get(key, 0) + 1
        return counts


@dataclass
class ReplayResult:
    """Whether re-running a decision reproduced it, and what differed if not."""

    matched: bool
    original_stopped_at: str | None
    replayed_stopped_at: str | None
    differences: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "matched": self.matched,
            "original_stopped_at": self.original_stopped_at,
            "replayed_stopped_at": self.replayed_stopped_at,
            "differences": self.differences,
        }


def replay(session: Session, stored: StoredTrace) -> ReplayResult:
    """Re-run a stored decision at its own `as_of` and compare.

    A mismatch is not a curiosity. It means a read somewhere saw data that did
    not exist when the decision was made, which invalidates every backtest
    result the same code path produced.
    """
    again = decide(
        session,
        stored.instrument_id,
        stored.timeframe,
        as_of=stored.as_of,
        **stored.inputs,
    )
    return _compare(stored.trace, again)


def _compare(original: DecisionTrace, replayed: DecisionTrace) -> ReplayResult:
    differences: list[str] = []

    if original.stopped_at != replayed.stopped_at:
        differences.append(
            f"stopped at {original.stopped_at!r} originally, {replayed.stopped_at!r} on replay"
        )

    original_stages = [s.name for s in original.stages]
    replayed_stages = [s.name for s in replayed.stages]
    if original_stages != replayed_stages:
        differences.append(
            f"stages ran {original_stages} originally, {replayed_stages} on replay"
        )

    if original.permitted_risk_r != replayed.permitted_risk_r:
        differences.append(
            f"permitted {original.permitted_risk_r} R originally, "
            f"{replayed.permitted_risk_r} R on replay"
        )

    return ReplayResult(
        matched=not differences,
        original_stopped_at=original.stopped_at,
        replayed_stopped_at=replayed.stopped_at,
        differences=differences,
    )


def verify_determinism(
    session: Session,
    instrument_id: uuid.UUID,
    timeframe: Timeframe,
    as_of: datetime,
    inputs: dict[str, Any],
    *,
    runs: int = 2,
) -> ReplayResult:
    """Run the same decision `runs` times and prove the answers agree.

    Cheap enough to run in CI, and it is the only evidence that the pipeline
    reads through the point-in-time layer rather than around it.
    """
    if runs < 2:
        raise ValidationFailedError("determinism needs at least two runs to compare")

    first = decide(session, instrument_id, timeframe, as_of=as_of, **inputs)
    result = ReplayResult(
        matched=True,
        original_stopped_at=first.stopped_at,
        replayed_stopped_at=first.stopped_at,
    )
    for _ in range(runs - 1):
        again = decide(session, instrument_id, timeframe, as_of=as_of, **inputs)
        comparison = _compare(first, again)
        if not comparison.matched:
            result.matched = False
            result.replayed_stopped_at = again.stopped_at
            result.differences.extend(comparison.differences)
    return result


@dataclass
class WhatIfResult:
    """The same decision under a changed input, and what the change cannot say."""

    changed: dict[str, Any]
    original_stopped_at: str | None
    alternative_stopped_at: str | None
    original_risk_r: float | None
    alternative_risk_r: float | None
    verdict_changed: bool
    caveats: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "changed": sorted(self.changed),
            "original": {
                "stopped_at": self.original_stopped_at,
                "permitted_risk_r": self.original_risk_r,
            },
            "alternative": {
                "stopped_at": self.alternative_stopped_at,
                "permitted_risk_r": self.alternative_risk_r,
            },
            "verdict_changed": self.verdict_changed,
            "caveats": self.caveats,
            # Stated on every response: the bars in the database are the bars
            # that happened under the original decision.
            "note": (
                "the market's reply to this alternative is not in the data; only "
                "the system's own answer to it is"
            ),
        }


def what_if(
    session: Session,
    stored: StoredTrace,
    **overrides: Any,
) -> WhatIfResult:
    """Re-run a stored decision with one or more inputs changed.

    Every gate runs again on the changed input. Nothing is re-scored from the
    stored verdict, because an analysis that disagrees with what the system
    would have done is worse than no analysis at all.
    """
    if not overrides:
        raise ValidationFailedError(
            "a what-if with nothing changed is a replay — call `replay` instead"
        )

    unknown = set(overrides) - set(stored.inputs)
    if unknown:
        raise ValidationFailedError(
            f"{sorted(unknown)} are not inputs of the original decision, so this "
            "would be a different question, not a variation on it"
        )

    inputs = {**stored.inputs, **overrides}
    alternative = decide(
        session, stored.instrument_id, stored.timeframe, as_of=stored.as_of, **inputs
    )

    caveats: list[str] = []
    for name in overrides:
        if name in LEVEL_INPUTS:
            caveats.append(
                f"changing {name} moves where the position sits, and the recorded "
                "bars are the ones that happened under the original levels"
            )
    if alternative.intent is not None and stored.trace.intent is None:
        caveats.append(
            "this alternative reaches an order the original never placed, so there "
            "is no realised outcome to compare it against"
        )

    return WhatIfResult(
        changed=dict(overrides),
        original_stopped_at=stored.trace.stopped_at,
        alternative_stopped_at=alternative.stopped_at,
        original_risk_r=stored.trace.permitted_risk_r,
        alternative_risk_r=alternative.permitted_risk_r,
        verdict_changed=stored.trace.stopped_at != alternative.stopped_at,
        caveats=caveats,
    )
