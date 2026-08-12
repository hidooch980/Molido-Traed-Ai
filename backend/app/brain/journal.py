"""Decision journal (spec phase 29, §31).

Three moments, and their order is the entire point.

**BEFORE is written blind, and then frozen.** A thesis recorded after the
market has voted is not a thesis; it is a memory of one, reshaped by the
result. `BeforeMoment` is a frozen dataclass so the record of what was believed
cannot be quietly improved once what happened is known.

**An entry with no invalidation is refused.** The invalidation is the
observable event that would prove the thesis wrong. Without it there is nothing
the market can do to make the author say "I was wrong", which makes the entry
unfalsifiable — a hope with a price attached. It is the one field with no
default and no way around it.

**DURING is append-only.** There is no edit and no delete, because the whole
value of the running record is that it was written while the outcome was still
unknown.

**AFTER compares the prediction with reality, or admits that it cannot.** If
BEFORE recorded no probability, the comparison comes back unavailable with its
reason — not 0.5, not zero. Scoring an entry against a forecast the system
never made manufactures exactly the calibration data phase 20 exists to measure
honestly.

WAIT decisions belong here as much as trades do. The decisions not to trade are
where a journal earns its keep, and they are the ones no broker statement will
ever show.

This module records. It does not decide, does not size, does not authorise and
does not persist — entries are plain objects the caller holds and hands back.
"""

from __future__ import annotations

import math
import statistics
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.core.enums import Decision, Regime
from app.core.errors import ValidationFailedError

# Below this many closed entries, no rate is reported. Twenty is not a
# statistical threshold; it is the point below which one trade moves the win
# rate by five points, and a number that moves that much gets read as
# performance when it is arithmetic.
MIN_SUMMARY_ENTRIES = 20

# A scratch rarely lands on exactly 0.0 R once costs are paid, so a small
# either-side band is honest. Beyond it, "breakeven" carrying a full winner is
# a mislabel — and scratches are excluded from the win rate while still
# counting toward the average R, so one of them moves the average with nothing
# on the record to explain why.
BREAKEVEN_TOLERANCE_R = 0.25

# A statistic computed from a sliver of the journal is a statistic about a
# different journal. Below this share of the relevant population it is withheld
# rather than published beside a caveat nobody reads.
MIN_COVERAGE = 0.5


class ObservationKind(StrEnum):
    """What kind of change is being recorded during the life of an entry."""

    MARKET_CHANGE = "market_change"
    REGIME_CHANGE = "regime_change"
    STOP_CHANGE = "stop_change"
    TARGET_CHANGE = "target_change"
    MODEL_CHANGE = "model_change"
    INVALIDATION_TRIGGERED = "invalidation_triggered"


class Outcome(StrEnum):
    """How an entry ended.

    ABANDONED is separate from BREAKEVEN on purpose: a thesis dropped before
    entry produced no R multiple at all, while a scratch produced one that
    happened to be near zero. Folding them together is how a journal loses the
    difference between "no trade" and "no profit".
    """

    WIN = "win"
    LOSS = "loss"
    BREAKEVEN = "breakeven"
    ABANDONED = "abandoned"


def _utc(moment: datetime | None, *, label: str) -> datetime:
    """Normalise to UTC, refusing naive timestamps.

    A journal ordered by naive timestamps silently reorders itself across a DST
    boundary, and the ordering is the only thing proving BEFORE was written
    before AFTER.
    """
    if moment is None:
        return datetime.now(UTC)
    if moment.tzinfo is None:
        raise ValidationFailedError(f"{label} must be timezone-aware (UTC)")
    normalised = moment.astimezone(UTC)
    if normalised > datetime.now(UTC):
        raise ValidationFailedError(
            f"{label} is in the future — a journal records what happened, and a "
            "record stamped ahead of the clock cannot have been written when it says"
        )
    return normalised


def _finite(value: float | None, *, label: str, non_negative: bool = False) -> None:
    """Refuse NaN and infinity where they enter the record.

    A NaN compares false against every bound, so it slips through each range
    and sign check on the way in and then turns an average into `nan` on the
    way out — where it reads as a rendering fault rather than as the bad record
    it is. Infinity does the same to a sum.
    """
    if value is None:
        return
    if not math.isfinite(value):
        raise ValidationFailedError(f"{label} must be a finite number, not {value!r}")
    if non_negative and value < 0:
        raise ValidationFailedError(f"{label} is a magnitude; {value} is negative")


def _required_text(value: str | None, *, label: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise ValidationFailedError(f"{label} is required and cannot be blank")
    return cleaned


# ----------------------------------------------------------------- the moments


@dataclass(frozen=True)
class BeforeMoment:
    """What was believed while the outcome was still unknown.

    Frozen, and validated in `__post_init__` rather than only in `create_entry`,
    so there is no construction path that produces an entry without a stated
    invalidation.
    """

    thesis: str
    invalidation: str
    recorded_at: datetime
    supporting: tuple[str, ...] = ()
    contradicting: tuple[str, ...] = ()
    probability: float | None = None
    # Required whenever `probability` is None. The spec asks for the
    # probability *or the explicit fact that none was available*; an entry that
    # is simply silent about it is indistinguishable later from one where
    # someone forgot to write it down.
    probability_unavailable_reason: str | None = None
    expected_value_r: float | None = None
    risk_allocated_r: float | None = None
    regime: Regime | None = None

    def __post_init__(self) -> None:
        if not self.thesis.strip():
            raise ValidationFailedError("thesis is required and cannot be blank")
        if not self.invalidation.strip():
            raise ValidationFailedError(
                "an entry without an invalidation is not a thesis — state the "
                "observable event that would prove it wrong"
            )
        _finite(self.probability, label="probability")
        _finite(self.expected_value_r, label="expected_value_r")
        _finite(self.risk_allocated_r, label="risk_allocated_r", non_negative=True)
        if self.probability is None:
            if not (self.probability_unavailable_reason or "").strip():
                raise ValidationFailedError(
                    "record a probability, or state why none was available"
                )
        else:
            if self.probability_unavailable_reason:
                raise ValidationFailedError(
                    "a probability and a reason it was unavailable cannot both be true"
                )
            if not 0.0 <= self.probability <= 1.0:
                raise ValidationFailedError(
                    f"probability {self.probability} is outside [0, 1]"
                )

    def as_dict(self) -> dict[str, Any]:
        return {
            "thesis": self.thesis,
            "invalidation": self.invalidation,
            "recorded_at": self.recorded_at.isoformat(),
            "supporting": list(self.supporting),
            "contradicting": list(self.contradicting),
            "probability": self.probability,
            "probability_unavailable_reason": self.probability_unavailable_reason,
            "expected_value_r": self.expected_value_r,
            "risk_allocated_r": self.risk_allocated_r,
            "regime": self.regime.value if self.regime else None,
        }


@dataclass(frozen=True)
class Observation:
    """One thing that changed while the entry was live."""

    kind: ObservationKind
    note: str
    at: datetime
    from_value: float | None = None
    to_value: float | None = None

    def __post_init__(self) -> None:
        _finite(self.from_value, label="from_value")
        _finite(self.to_value, label="to_value")

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "note": self.note,
            "at": self.at.isoformat(),
            "from_value": self.from_value,
            "to_value": self.to_value,
        }


@dataclass(frozen=True)
class DuringMoment:
    """The running record, append-only by construction rather than by promise.

    The previous version documented append-only and handed out a list, so
    `observations.pop()` erased a recorded fact — including an
    INVALIDATION_TRIGGERED observation, which is exactly the evidence that goes
    missing at the moment the lesson is being written. Frozen, holding a tuple:
    appending produces a new record instead of editing this one.
    """

    observations: tuple[Observation, ...] = ()

    @property
    def invalidation_observed(self) -> bool:
        return any(
            o.kind is ObservationKind.INVALIDATION_TRIGGERED for o in self.observations
        )

    def appended(self, observation: Observation) -> DuringMoment:
        return DuringMoment(observations=(*self.observations, observation))

    def as_dict(self) -> dict[str, Any]:
        return {
            "count": len(self.observations),
            # A count of zero says nobody wrote anything down, which is not the
            # same claim as "the trade was uneventful" — and no reader can tell
            # those apart from the number on its own.
            "nothing_recorded_note": (
                None
                if self.observations
                else "no observations were recorded; this is silence, not calm"
            ),
            "invalidation_observed": self.invalidation_observed,
            "observations": [o.as_dict() for o in self.observations],
        }


@dataclass(frozen=True)
class PredictionCheck:
    """The BEFORE probability held against what actually happened."""

    available: bool
    reason: str | None = None
    probability: float | None = None
    realised: float | None = None
    # realised − probability. Signed, because "we were more confident than the
    # market justified" and "we were right and timid" are different lessons and
    # an absolute error hides which one this was.
    surprise: float | None = None
    brier: float | None = None

    def as_dict(self) -> dict[str, Any]:
        if not self.available:
            return {"available": False, "reason": self.reason}
        return {
            "available": True,
            "probability": self.probability,
            "realised": self.realised,
            "surprise": self.surprise,
            "brier": self.brier,
        }


def _assert_label_matches_number(outcome: Outcome, r_multiple: float | None) -> None:
    """Refuse an outcome label that its R multiple contradicts.

    A label and a number that disagree corrupt the win rate and the average R
    at once, and months later nothing on the record says which of the two was
    the typo. The scratch case is the expensive one: BREAKEVEN is excluded from
    the win rate but still counted in the average R, so a mislabelled winner
    moves the average with nothing visible to explain it.
    """
    if r_multiple is None:
        return
    if outcome is Outcome.WIN and r_multiple <= 0:
        raise ValidationFailedError(
            f"outcome 'win' contradicts an R multiple of {r_multiple}"
        )
    if outcome is Outcome.LOSS and r_multiple >= 0:
        raise ValidationFailedError(
            f"outcome 'loss' contradicts an R multiple of {r_multiple}"
        )
    if outcome is Outcome.BREAKEVEN and abs(r_multiple) > BREAKEVEN_TOLERANCE_R:
        raise ValidationFailedError(
            f"outcome 'breakeven' contradicts an R multiple of {r_multiple}; "
            f"a scratch lands within {BREAKEVEN_TOLERANCE_R} R of zero"
        )


@dataclass(frozen=True)
class AfterMoment:
    """What happened, and what it taught."""

    outcome: Outcome
    closed_at: datetime
    prediction_vs_reality: PredictionCheck
    r_multiple: float | None = None
    r_multiple_unavailable_reason: str | None = None
    # True when this module filled the reason in rather than an author writing
    # it. Both end up in the same field, and months later a generated sentence
    # is indistinguishable from a considered one unless the record says which.
    r_multiple_unavailable_reason_generated: bool = False
    # None means nobody checked, False means somebody checked and it did not
    # fire. The summary counts only the second kind, so the difference has to
    # survive all the way into the record.
    invalidation_triggered: bool | None = None
    execution_quality: str | None = None
    error: str | None = None
    lesson: str | None = None

    def __post_init__(self) -> None:
        # Enforced on the dataclass, not only in `close_entry`: a caller that
        # builds an AfterMoment directly must not get a looser record than one
        # that goes through the front door.
        _finite(self.r_multiple, label="r_multiple")
        _assert_label_matches_number(self.outcome, self.r_multiple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "closed_at": self.closed_at.isoformat(),
            "r_multiple": self.r_multiple,
            "r_multiple_unavailable_reason": self.r_multiple_unavailable_reason,
            "r_multiple_unavailable_reason_generated": (
                self.r_multiple_unavailable_reason_generated
            ),
            "prediction_vs_reality": self.prediction_vs_reality.as_dict(),
            "invalidation_triggered": self.invalidation_triggered,
            "execution_quality": self.execution_quality,
            "error": self.error,
            "lesson": self.lesson,
        }


# The fields that *are* the record. Once the entry exists they cannot be
# reassigned or deleted through ordinary attribute access: freezing the BEFORE
# moment achieves nothing if the whole moment can be swapped for a better one
# after the outcome is known, and a closed entry that can be reopened by
# clearing `after` was never closed. The module's own functions go through
# `object.__setattr__`, which is deliberately more conspicuous than `=`.
_SEALED_FIELDS = frozenset(
    {"symbol", "decision", "before", "during", "after", "entry_id"}
)


@dataclass
class JournalEntry:
    symbol: str
    decision: Decision
    before: BeforeMoment
    during: DuringMoment = field(default_factory=DuringMoment)
    after: AfterMoment | None = None
    entry_id: uuid.UUID = field(default_factory=uuid.uuid4)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in _SEALED_FIELDS and getattr(self, "_sealed", False):
            raise ValidationFailedError(
                f"{name!r} is part of the record and cannot be reassigned — a "
                "journal that can be tidied up afterwards is not evidence of "
                "anything"
            )
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        if name in _SEALED_FIELDS:
            raise ValidationFailedError(
                f"{name!r} is part of the record and cannot be deleted"
            )
        object.__delattr__(self, name)

    @property
    def is_closed(self) -> bool:
        return self.after is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "entry_id": str(self.entry_id),
            "symbol": self.symbol,
            "decision": self.decision.value,
            "closed": self.is_closed,
            "before": self.before.as_dict(),
            "during": self.during.as_dict(),
            "after": self.after.as_dict() if self.after else None,
        }


# --------------------------------------------------------------------- the API


def create_entry(
    *,
    symbol: str,
    decision: Decision,
    thesis: str,
    invalidation: str,
    supporting: list[str] | None = None,
    contradicting: list[str] | None = None,
    probability: float | None = None,
    probability_unavailable_reason: str | None = None,
    expected_value_r: float | None = None,
    risk_allocated_r: float | None = None,
    regime: Regime | None = None,
    at: datetime | None = None,
) -> JournalEntry:
    """Open an entry at its BEFORE moment.

    `expected_value_r` and `risk_allocated_r` stay None when the caller does not
    supply them. A WAIT that risked nothing passes 0.0 and means it; an entry
    where nobody recorded the allocation keeps None, and the two must not read
    the same afterwards.
    """
    before = BeforeMoment(
        thesis=_required_text(thesis, label="thesis"),
        invalidation=_required_text(invalidation, label="invalidation"),
        recorded_at=_utc(at, label="recorded_at"),
        supporting=tuple(supporting or ()),
        contradicting=tuple(contradicting or ()),
        probability=probability,
        probability_unavailable_reason=probability_unavailable_reason,
        expected_value_r=expected_value_r,
        risk_allocated_r=risk_allocated_r,
        regime=regime,
    )
    return JournalEntry(
        symbol=_required_text(symbol, label="symbol"),
        decision=decision,
        before=before,
    )


def observe(
    entry: JournalEntry,
    kind: ObservationKind,
    note: str,
    *,
    from_value: float | None = None,
    to_value: float | None = None,
    at: datetime | None = None,
) -> Observation:
    """Append one observation to the DURING record."""
    if entry.after is not None:
        raise ValidationFailedError(
            f"entry {entry.entry_id} was closed at "
            f"{entry.after.closed_at.isoformat()}; the DURING record cannot be "
            "extended once the outcome is known",
            entry_id=str(entry.entry_id),
        )

    moment = _utc(at, label="observation time")
    if moment < entry.before.recorded_at:
        raise ValidationFailedError(
            "an observation cannot predate the BEFORE moment it belongs to",
            entry_id=str(entry.entry_id),
        )
    # The order of the record is the only proof that BEFORE preceded AFTER, so
    # an out-of-order stamp is not a cosmetic problem: it is the one property
    # that makes the journal worth reading back.
    if entry.during.observations and moment < entry.during.observations[-1].at:
        raise ValidationFailedError(
            "an observation cannot predate the previous observation in the record",
            entry_id=str(entry.entry_id),
        )

    observation = Observation(
        kind=kind,
        note=_required_text(note, label="observation note"),
        at=moment,
        from_value=from_value,
        to_value=to_value,
    )
    object.__setattr__(entry, "during", entry.during.appended(observation))
    return observation


def compare_prediction(before: BeforeMoment, outcome: Outcome) -> PredictionCheck:
    """Hold the recorded probability against the realised outcome.

    Unavailable is a real answer here, and the common one early on. An entry
    that recorded no probability cannot be scored, and scoring it as 0.5 would
    invent a forecast the system never made — worse than having none, because it
    is indistinguishable from one it did.
    """
    if outcome is Outcome.ABANDONED:
        return PredictionCheck(
            available=False,
            reason="the position was never taken, so the forecast never resolved",
        )
    if outcome is Outcome.BREAKEVEN:
        return PredictionCheck(
            available=False,
            reason="a scratch resolves the trade but not the thesis behind it",
        )
    if before.probability is None:
        return PredictionCheck(
            available=False,
            reason=(
                "no probability was recorded before the trade: "
                + (before.probability_unavailable_reason or "reason not stated")
            ),
        )

    realised = 1.0 if outcome is Outcome.WIN else 0.0
    return PredictionCheck(
        available=True,
        probability=before.probability,
        realised=realised,
        surprise=round(realised - before.probability, 6),
        # One Brier score is not calibration — it is a single squared error and
        # says nothing about whether a 70% call was justified. Phase 20 answers
        # that over hundreds of these; this number only feeds it.
        brier=round((before.probability - realised) ** 2, 6),
    )


def close_entry(
    entry: JournalEntry,
    *,
    outcome: Outcome,
    r_multiple: float | None = None,
    r_multiple_unavailable_reason: str | None = None,
    invalidation_triggered: bool | None = None,
    execution_quality: str | None = None,
    error: str | None = None,
    lesson: str | None = None,
    at: datetime | None = None,
) -> JournalEntry:
    """Write the AFTER moment. Exactly once."""
    if entry.after is not None:
        raise ValidationFailedError(
            f"entry {entry.entry_id} was already closed at "
            f"{entry.after.closed_at.isoformat()} with outcome "
            f"{entry.after.outcome.value!r} — a second close would overwrite "
            "the record it is supposed to preserve",
            entry_id=str(entry.entry_id),
        )

    closed_at = _utc(at, label="closed_at")
    if closed_at < entry.before.recorded_at:
        raise ValidationFailedError(
            "an entry cannot close before it was opened",
            entry_id=str(entry.entry_id),
        )
    if entry.during.observations and closed_at < entry.during.observations[-1].at:
        raise ValidationFailedError(
            "an entry cannot close before its last observation — the DURING "
            "record would postdate the AFTER it is supposed to precede",
            entry_id=str(entry.entry_id),
        )

    generated_reason = False
    if outcome is Outcome.ABANDONED:
        if r_multiple is not None:
            raise ValidationFailedError(
                "an abandoned entry has no R multiple — nothing was risked",
                entry_id=str(entry.entry_id),
            )
        if not (r_multiple_unavailable_reason or "").strip():
            r_multiple_unavailable_reason = "the position was never opened"
            generated_reason = True

    if r_multiple is None:
        if not (r_multiple_unavailable_reason or "").strip():
            raise ValidationFailedError(
                "record the R multiple, or state why it is unavailable",
                entry_id=str(entry.entry_id),
            )
    else:
        if r_multiple_unavailable_reason:
            raise ValidationFailedError(
                "an R multiple and a reason it is unavailable cannot both be true",
                entry_id=str(entry.entry_id),
            )
        # The label/number cross-check lives on AfterMoment, so it applies to
        # every construction path rather than only to this one.

    # An INVALIDATION_TRIGGERED observation is already a recorded fact about
    # this entry. Closing is the moment the lesson gets written, and it is
    # exactly the moment at which inconvenient evidence tends to disappear.
    if entry.during.invalidation_observed:
        if invalidation_triggered is False:
            raise ValidationFailedError(
                "the DURING record already observed the invalidation triggering",
                entry_id=str(entry.entry_id),
            )
        invalidation_triggered = True

    after = AfterMoment(
        outcome=outcome,
        closed_at=closed_at,
        prediction_vs_reality=compare_prediction(entry.before, outcome),
        r_multiple=r_multiple,
        r_multiple_unavailable_reason=r_multiple_unavailable_reason,
        r_multiple_unavailable_reason_generated=generated_reason,
        invalidation_triggered=invalidation_triggered,
        execution_quality=execution_quality,
        error=error,
        lesson=lesson,
    )
    object.__setattr__(entry, "after", after)
    return entry


# ------------------------------------------------------------------- summary


@dataclass
class JournalSummary:
    """Counts are always reported; rates only when their own sample supports them.

    "Their own" is the correction. A single journal-wide gate let twenty closed
    entries publish a win rate resting on the two of them that were actually
    decided, because the other eighteen were abandoned theses — uncertainty
    about most of the journal bought a headline for the rest of it. Each
    statistic now counts the population it is actually about, and publishes its
    coverage of the journal alongside itself so a reader can see how much of it
    the number is not describing.
    """

    available: bool
    reason: str | None = None
    entries: int = 0
    closed: int = 0
    open_entries: int = 0
    wins: int = 0
    losses: int = 0
    breakeven: int = 0
    abandoned: int = 0
    # Wins plus losses: the entries that resolved to something a win rate can
    # be computed from. Scratches and abandoned theses are neither.
    decided: int = 0
    win_rate: float | None = None
    win_rate_coverage: float | None = None
    average_r: float | None = None
    average_r_coverage: float | None = None
    r_sample: int = 0
    invalidation_assessed: int = 0
    invalidation_triggered: int = 0
    invalidation_triggered_share: float | None = None
    invalidation_coverage: float | None = None
    losses_assessed: int = 0
    unanticipated_losses: int = 0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        # The counts survive an unavailable summary because they are
        # observations; only the rates are claims, and only those go null.
        return {
            "available": self.available,
            "reason": self.reason,
            "entries": self.entries,
            "closed": self.closed,
            "open": self.open_entries,
            "wins": self.wins,
            "losses": self.losses,
            "breakeven": self.breakeven,
            "abandoned": self.abandoned,
            "decided": self.decided,
            "win_rate": self.win_rate,
            "win_rate_coverage": self.win_rate_coverage,
            "average_r": self.average_r,
            "average_r_coverage": self.average_r_coverage,
            "r_sample": self.r_sample,
            "invalidation_assessed": self.invalidation_assessed,
            "invalidation_triggered": self.invalidation_triggered,
            "invalidation_triggered_share": self.invalidation_triggered_share,
            "invalidation_coverage": self.invalidation_coverage,
            "losses_assessed": self.losses_assessed,
            "unanticipated_losses": self.unanticipated_losses,
            "notes": self.notes,
        }


def summarise(entries: list[JournalEntry]) -> JournalSummary:
    """What the journal says about itself.

    The share of entries whose invalidation actually triggered is the number to
    read first. An invalidation that never fires across a whole journal was
    never an observable condition — it was decoration, and every entry carrying
    it was unfalsifiable. The win rate cannot show that; nothing else here can
    either.

    Nothing is published on a sample that is not about it. Three separate gates
    apply — a decided count for the win rate, a recorded-R count for the
    average, an assessed count for the invalidation share — and each also has
    to cover enough of the journal to be describing the same journal the reader
    is looking at.
    """
    afters: list[AfterMoment] = []
    for entry in entries:
        if entry.after is not None:
            afters.append(entry.after)

    summary = JournalSummary(
        available=False,
        entries=len(entries),
        closed=len(afters),
        open_entries=len(entries) - len(afters),
        wins=sum(1 for a in afters if a.outcome is Outcome.WIN),
        losses=sum(1 for a in afters if a.outcome is Outcome.LOSS),
        breakeven=sum(1 for a in afters if a.outcome is Outcome.BREAKEVEN),
        abandoned=sum(1 for a in afters if a.outcome is Outcome.ABANDONED),
    )
    summary.decided = summary.wins + summary.losses
    # Abandoned theses never reached the market, so they cannot sit in the
    # denominator of a statistic about what the market did.
    traded = summary.closed - summary.abandoned

    r_values = [a.r_multiple for a in afters if a.r_multiple is not None]
    summary.r_sample = len(r_values)

    assessed = [a for a in afters if a.invalidation_triggered is not None]
    summary.invalidation_assessed = len(assessed)
    summary.invalidation_triggered = sum(1 for a in assessed if a.invalidation_triggered)
    losses_assessed = [a for a in assessed if a.outcome is Outcome.LOSS]
    summary.losses_assessed = len(losses_assessed)
    summary.unanticipated_losses = sum(
        1 for a in losses_assessed if not a.invalidation_triggered
    )
    # A note is a claim too. This one used to be written from any sample at
    # all, so one assessed loss produced "1 of 1 assessed losses" — a hundred
    # per cent finding, quoted even on a summary that came back unavailable.
    if len(losses_assessed) >= MIN_SUMMARY_ENTRIES:
        summary.notes.append(
            f"{summary.unanticipated_losses} of {len(losses_assessed)} assessed "
            "losses happened without the stated invalidation triggering"
        )

    if len(afters) < MIN_SUMMARY_ENTRIES:
        summary.reason = (
            f"{len(afters)} closed entries, needs {MIN_SUMMARY_ENTRIES} before a "
            "win rate or an average R means anything"
        )
        return summary

    if summary.decided >= MIN_SUMMARY_ENTRIES:
        summary.win_rate = round(summary.wins / summary.decided, 4)
        summary.win_rate_coverage = round(summary.decided / summary.closed, 4)
        summary.notes.append(
            f"win rate is over {summary.decided} decided entries; {summary.breakeven} "
            f"scratch and {summary.abandoned} abandoned entries are excluded"
        )
    else:
        summary.notes.append(
            f"{summary.decided} decided entries, below the {MIN_SUMMARY_ENTRIES} "
            "needed to quote a win rate — scratches and abandoned theses are not "
            "decisions and cannot stand in for them"
        )

    if not r_values:
        summary.notes.append("no closed entry recorded an R multiple")
    else:
        r_coverage = len(r_values) / traded if traded else 0.0
        if len(r_values) < MIN_SUMMARY_ENTRIES:
            summary.notes.append(
                f"{len(r_values)} recorded R multiples, below the "
                f"{MIN_SUMMARY_ENTRIES} needed to quote an average"
            )
        elif r_coverage < MIN_COVERAGE:
            summary.notes.append(
                f"average R would rest on {r_coverage:.0%} of the {traded} entries "
                f"that reached the market, below the {MIN_COVERAGE:.0%} needed to "
                "quote it"
            )
        else:
            summary.average_r = round(statistics.fmean(r_values), 4)
            summary.average_r_coverage = round(r_coverage, 4)
            if len(r_values) < traded:
                summary.notes.append(
                    f"average R covers {len(r_values)} of {traded} traded entries; "
                    "the rest recorded no R multiple and are not counted as zero"
                )

    if len(assessed) < MIN_SUMMARY_ENTRIES:
        summary.notes.append(
            f"invalidation was assessed on {len(assessed)} entries, below the "
            f"{MIN_SUMMARY_ENTRIES} needed to quote a share"
        )
    else:
        coverage = len(assessed) / summary.closed
        if coverage < MIN_COVERAGE:
            # The unchecked entries are missing from numerator and denominator
            # both, so a reader has nothing to correct the share with: twenty
            # assessed out of five hundred closed reported a flawless 100% and
            # read as a finding about the journal.
            summary.notes.append(
                f"invalidation was assessed on {coverage:.0%} of the "
                f"{summary.closed} closed entries — too little of the journal for "
                "the share to describe it"
            )
        else:
            summary.invalidation_triggered_share = round(
                summary.invalidation_triggered / len(assessed), 4
            )
            summary.invalidation_coverage = round(coverage, 4)

    # Availability is derived from what was actually published, not from a row
    # count: twenty abandoned theses are twenty closed entries and measure
    # nothing at all, and a consumer gating on this flag must not get a green
    # light from them.
    summary.available = any(
        value is not None
        for value in (
            summary.win_rate,
            summary.average_r,
            summary.invalidation_triggered_share,
        )
    )
    if not summary.available:
        summary.reason = (
            f"{len(afters)} closed entries, but no statistic in them has a sample "
            "large enough to publish"
        )
    return summary
