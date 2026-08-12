"""Decision-journal tests (phase 29).

A journal is only worth keeping if it cannot be tidied up after the fact, so
most of these tests try to do exactly that: rewrite a thesis once the outcome
is known, close an entry twice, delete an inconvenient observation, append to a
finished record, or extract a percentage from two trades hiding behind eighteen
abandoned ones. All of it must be refused.
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib
from datetime import UTC, datetime, timedelta

import pytest

from app.brain import journal
from app.brain.journal import ObservationKind, Outcome
from app.core.enums import Decision, Regime
from app.core.errors import ValidationFailedError

OPENED_AT = datetime(2024, 3, 1, 9, 0, tzinfo=UTC)


def open_entry(**overrides) -> journal.JournalEntry:
    defaults = dict(
        symbol="EURUSD",
        decision=Decision.BUY,
        thesis="H4 uptrend, pullback into the level it broke out of",
        invalidation="H4 closes below 1.0900",
        probability=0.6,
        regime=Regime.TREND_UP,
        at=OPENED_AT,
    )
    defaults.update(overrides)
    return journal.create_entry(**defaults)


def closed_entries(
    count: int,
    *,
    outcome: Outcome,
    r_multiple: float | None,
    invalidation_triggered: bool | None = None,
    r_reason: str | None = None,
) -> list[journal.JournalEntry]:
    entries = []
    for _ in range(count):
        entry = open_entry()
        journal.close_entry(
            entry,
            outcome=outcome,
            r_multiple=r_multiple,
            r_multiple_unavailable_reason=r_reason,
            invalidation_triggered=invalidation_triggered,
            at=OPENED_AT + timedelta(hours=6),
        )
        entries.append(entry)
    return entries


# ==================================================================== BEFORE
class TestEntryCreation:
    def test_entry_without_an_invalidation_is_refused(self):
        """The rule the whole module exists for: no invalidation, no thesis."""
        with pytest.raises(ValidationFailedError) as exc:
            open_entry(invalidation="")

        assert "invalidation" in str(exc.value)

    def test_whitespace_is_not_an_invalidation(self):
        with pytest.raises(ValidationFailedError):
            open_entry(invalidation="   ")

    def test_the_dataclass_itself_refuses_a_missing_invalidation(self):
        """Bypassing `create_entry` must not bypass the rule."""
        with pytest.raises(ValidationFailedError):
            journal.BeforeMoment(
                thesis="it feels right",
                invalidation="",
                recorded_at=OPENED_AT,
                probability=0.6,
            )

    def test_blank_thesis_is_refused(self):
        with pytest.raises(ValidationFailedError):
            open_entry(thesis="")

    def test_absent_probability_must_be_explained(self):
        """Silence about the probability is indistinguishable from forgetting."""
        with pytest.raises(ValidationFailedError) as exc:
            open_entry(probability=None)

        assert "probability" in str(exc.value)

    def test_probability_and_an_unavailable_reason_cannot_both_be_true(self):
        with pytest.raises(ValidationFailedError):
            open_entry(probability=0.6, probability_unavailable_reason="uncalibrated")

    def test_an_explained_absence_is_accepted(self):
        entry = open_entry(
            probability=None,
            probability_unavailable_reason="council score is not calibrated yet",
        )

        assert entry.before.probability is None
        assert "calibrated" in entry.before.probability_unavailable_reason

    def test_probability_outside_zero_to_one_is_refused(self):
        with pytest.raises(ValidationFailedError):
            open_entry(probability=1.4)

    def test_naive_timestamps_are_refused(self):
        with pytest.raises(ValidationFailedError):
            open_entry(at=datetime(2024, 3, 1, 9, 0))

    def test_unrecorded_risk_is_none_not_zero(self):
        """A WAIT that risked nothing and an entry nobody filled in are not
        the same fact, and the caller has to be able to tell them apart."""
        unrecorded = open_entry()
        deliberate = open_entry(risk_allocated_r=0.0)

        assert unrecorded.before.risk_allocated_r is None
        assert deliberate.before.risk_allocated_r == 0.0

    def test_before_moment_is_frozen(self):
        """A thesis editable after the outcome is known is not a record of one."""
        entry = open_entry()

        with pytest.raises(dataclasses.FrozenInstanceError):
            entry.before.thesis = "I knew it would go the other way"  # type: ignore[misc]

    def test_the_invalidation_cannot_be_rewritten_either(self):
        entry = open_entry()

        with pytest.raises(dataclasses.FrozenInstanceError):
            entry.before.invalidation = "whatever just happened"  # type: ignore[misc]


# ======================================================== numeric validation
class TestNumbersAreValidatedAtTheBoundary:
    """NaN and infinity are refused where they enter, not where they surface.

    A NaN compares false against every bound, so it passes each range and sign
    check on the way in and then turns an average into `nan` on the way out,
    where it reads as a rendering fault rather than as a bad record.
    """

    def test_a_nan_probability_is_refused_as_not_a_number(self):
        with pytest.raises(ValidationFailedError) as exc:
            open_entry(probability=float("nan"))

        assert "finite" in str(exc.value)

    def test_an_infinite_expected_value_is_refused(self):
        with pytest.raises(ValidationFailedError) as exc:
            open_entry(expected_value_r=float("inf"))

        assert "finite" in str(exc.value)

    def test_a_nan_expected_value_is_refused(self):
        with pytest.raises(ValidationFailedError):
            open_entry(expected_value_r=float("nan"))

    def test_negative_allocated_risk_is_refused(self):
        """Risk is a magnitude; a negative allocation is a record nobody can act on."""
        with pytest.raises(ValidationFailedError):
            open_entry(risk_allocated_r=-5.0)

    def test_a_measured_zero_risk_is_still_accepted(self):
        entry = open_entry(risk_allocated_r=0.0)

        assert entry.before.risk_allocated_r == 0.0

    def test_a_nan_r_multiple_is_refused(self):
        entry = open_entry()

        with pytest.raises(ValidationFailedError) as exc:
            journal.close_entry(entry, outcome=Outcome.WIN, r_multiple=float("nan"))

        assert "finite" in str(exc.value)
        assert entry.after is None

    def test_an_infinite_r_multiple_is_refused(self):
        entry = open_entry()

        with pytest.raises(ValidationFailedError):
            journal.close_entry(entry, outcome=Outcome.WIN, r_multiple=float("inf"))

    def test_non_finite_observation_levels_are_refused(self):
        entry = open_entry()

        with pytest.raises(ValidationFailedError):
            journal.observe(
                entry, ObservationKind.STOP_CHANGE, "moved it",
                from_value=1.09, to_value=float("nan"),
            )

    def test_a_nan_r_multiple_cannot_reach_the_average(self):
        """The reproduction: one unvalidated NaN made the whole average nan."""
        clean = closed_entries(20, outcome=Outcome.WIN, r_multiple=1.0)
        poisoned = open_entry()

        with pytest.raises(ValidationFailedError):
            journal.close_entry(
                poisoned, outcome=Outcome.WIN, r_multiple=float("nan"),
                at=OPENED_AT + timedelta(hours=6),
            )

        summary = journal.summarise([*clean, poisoned])
        assert summary.average_r == pytest.approx(1.0)


# ==================================================================== DURING
class TestObservations:
    def test_observations_append_in_order(self):
        entry = open_entry()

        journal.observe(
            entry, ObservationKind.REGIME_CHANGE, "trend gave way to range",
            at=OPENED_AT + timedelta(hours=1),
        )
        journal.observe(
            entry, ObservationKind.STOP_CHANGE, "stop moved to breakeven",
            from_value=1.0900, to_value=1.0950, at=OPENED_AT + timedelta(hours=2),
        )

        kinds = [o.kind for o in entry.during.observations]
        assert kinds == [ObservationKind.REGIME_CHANGE, ObservationKind.STOP_CHANGE]
        assert entry.during.observations[1].to_value == 1.0950

    def test_a_stop_change_without_levels_records_none_not_zero(self):
        entry = open_entry()

        observation = journal.observe(
            entry, ObservationKind.STOP_CHANGE, "widened it, did not note where"
        )

        assert observation.from_value is None
        assert observation.to_value is None

    def test_appending_after_close_is_refused(self):
        """The DURING record's value is that it was written before the answer."""
        entry = open_entry()
        journal.close_entry(entry, outcome=Outcome.LOSS, r_multiple=-1.0)

        with pytest.raises(ValidationFailedError) as exc:
            journal.observe(entry, ObservationKind.MARKET_CHANGE, "in hindsight")

        assert "closed" in str(exc.value)

    def test_an_observation_cannot_predate_the_entry(self):
        entry = open_entry()

        with pytest.raises(ValidationFailedError):
            journal.observe(
                entry, ObservationKind.MARKET_CHANGE, "yesterday's news",
                at=OPENED_AT - timedelta(hours=1),
            )

    def test_blank_observations_are_refused(self):
        entry = open_entry()

        with pytest.raises(ValidationFailedError):
            journal.observe(entry, ObservationKind.MODEL_CHANGE, "  ")

    def test_an_empty_during_record_does_not_read_as_a_quiet_entry(self):
        """A count of zero says nobody wrote anything down, not that nothing
        happened, and no reader can tell those apart from the number alone."""
        payload = open_entry().during.as_dict()

        assert payload["count"] == 0
        assert payload["nothing_recorded_note"]

    def test_a_written_record_carries_no_such_caveat(self):
        entry = open_entry()
        journal.observe(entry, ObservationKind.MARKET_CHANGE, "momentum faded")

        assert entry.during.as_dict()["nothing_recorded_note"] is None


class TestOrderingIsTruthful:
    """The order of the record is the only proof BEFORE preceded AFTER."""

    def test_an_observation_cannot_predate_the_previous_one(self):
        entry = open_entry()
        journal.observe(
            entry, ObservationKind.MARKET_CHANGE, "gapped through the level",
            at=OPENED_AT + timedelta(days=30),
        )

        with pytest.raises(ValidationFailedError) as exc:
            journal.observe(
                entry, ObservationKind.MARKET_CHANGE, "actually it was quiet",
                at=OPENED_AT + timedelta(minutes=1),
            )

        assert "previous observation" in str(exc.value)
        assert len(entry.during.observations) == 1

    def test_an_entry_cannot_close_before_its_last_observation(self):
        """Otherwise a DURING record postdates the AFTER it is supposed to precede."""
        entry = open_entry()
        journal.observe(
            entry, ObservationKind.MARKET_CHANGE, "gapped through the level",
            at=OPENED_AT + timedelta(days=30),
        )

        with pytest.raises(ValidationFailedError):
            journal.close_entry(
                entry, outcome=Outcome.WIN, r_multiple=1.0,
                at=OPENED_AT + timedelta(hours=1),
            )

        assert entry.after is None

    def test_an_entry_cannot_be_opened_in_the_future(self):
        with pytest.raises(ValidationFailedError) as exc:
            open_entry(at=datetime.now(UTC) + timedelta(days=1))

        assert "future" in str(exc.value)

    def test_an_observation_cannot_be_stamped_in_the_future(self):
        entry = open_entry()

        with pytest.raises(ValidationFailedError):
            journal.observe(
                entry, ObservationKind.MARKET_CHANGE, "it will fall tomorrow",
                at=datetime.now(UTC) + timedelta(days=1),
            )

    def test_an_entry_cannot_close_in_the_future(self):
        entry = open_entry()

        with pytest.raises(ValidationFailedError):
            journal.close_entry(
                entry, outcome=Outcome.WIN, r_multiple=1.0,
                at=datetime.now(UTC) + timedelta(days=1),
            )


class TestAppendOnlyIsEnforced:
    """Append-only is a structure here, not a promise in a docstring.

    The old test for this scanned attribute names for the word "delete" and
    passed while `observations.pop()` erased a recorded fact. These call the
    real surface instead.
    """

    def test_an_observation_cannot_be_popped_off_the_record(self):
        entry = open_entry()
        journal.observe(
            entry, ObservationKind.INVALIDATION_TRIGGERED, "H4 closed at 1.0880"
        )

        with pytest.raises(AttributeError):
            entry.during.observations.pop()  # type: ignore[attr-defined]

        assert entry.during.invalidation_observed is True

    def test_an_observation_cannot_be_overwritten_in_place(self):
        entry = open_entry()
        journal.observe(
            entry, ObservationKind.INVALIDATION_TRIGGERED, "H4 closed at 1.0880"
        )
        replacement = entry.during.observations[0]

        with pytest.raises(TypeError):
            entry.during.observations[0] = replacement  # type: ignore[index]

    def test_the_running_record_cannot_be_swapped_for_an_empty_one(self):
        entry = open_entry()
        journal.observe(
            entry, ObservationKind.INVALIDATION_TRIGGERED, "H4 closed at 1.0880"
        )

        with pytest.raises(AttributeError):
            entry.during.observations = ()  # type: ignore[misc]
        with pytest.raises(ValidationFailedError):
            entry.during = journal.DuringMoment()

        assert entry.during.invalidation_observed is True

    def test_deleting_the_evidence_cannot_unlock_the_denial(self):
        """The full reproduction: erase the INVALIDATION_TRIGGERED observation,
        then close the entry claiming the invalidation never fired."""
        entry = open_entry()
        journal.observe(
            entry, ObservationKind.INVALIDATION_TRIGGERED, "H4 closed at 1.0880"
        )

        with pytest.raises(AttributeError):
            entry.during.observations.pop()  # type: ignore[attr-defined]

        with pytest.raises(ValidationFailedError):
            journal.close_entry(
                entry, outcome=Outcome.LOSS, r_multiple=-1.0,
                invalidation_triggered=False,
            )


class TestTheRecordCannotBeRewritten:
    def test_the_before_moment_cannot_be_swapped_after_the_outcome(self):
        """Freezing the moment is not enough if the whole moment can be replaced."""
        entry = open_entry(probability=0.6)
        journal.close_entry(entry, outcome=Outcome.LOSS, r_multiple=-1.0)

        with pytest.raises(ValidationFailedError):
            entry.before = journal.BeforeMoment(
                thesis="I said all along that it would fall",
                invalidation="H4 closes above 1.1000",
                recorded_at=OPENED_AT,
                probability=0.05,
            )

        assert entry.before.probability == 0.6
        assert entry.after.prediction_vs_reality.brier == pytest.approx(0.36)

    def test_a_closed_entry_cannot_be_reopened_by_clearing_the_outcome(self):
        entry = open_entry()
        journal.close_entry(entry, outcome=Outcome.LOSS, r_multiple=-1.0)

        with pytest.raises(ValidationFailedError):
            entry.after = None

        assert entry.is_closed is True

    def test_the_outcome_cannot_be_deleted(self):
        entry = open_entry()
        journal.close_entry(entry, outcome=Outcome.LOSS, r_multiple=-1.0)

        with pytest.raises(ValidationFailedError):
            del entry.after

        assert entry.after.outcome is Outcome.LOSS

    def test_the_outcome_cannot_be_replaced_with_a_better_one(self):
        entry = open_entry()
        journal.close_entry(entry, outcome=Outcome.LOSS, r_multiple=-1.0)
        original = entry.after

        with pytest.raises(ValidationFailedError):
            entry.after = dataclasses.replace(original, outcome=Outcome.WIN)

        assert entry.after.outcome is Outcome.LOSS

    def test_the_symbol_of_a_recorded_entry_is_fixed(self):
        entry = open_entry()

        with pytest.raises(ValidationFailedError):
            entry.symbol = "GBPUSD"


# ===================================================================== AFTER
class TestClosing:
    def test_an_entry_closes_exactly_once(self):
        entry = open_entry()
        journal.close_entry(entry, outcome=Outcome.WIN, r_multiple=2.0, lesson="held it")

        with pytest.raises(ValidationFailedError) as exc:
            journal.close_entry(entry, outcome=Outcome.LOSS, r_multiple=-1.0)

        assert "already closed" in str(exc.value)

    def test_a_refused_second_close_leaves_the_first_record_intact(self):
        entry = open_entry()
        journal.close_entry(entry, outcome=Outcome.WIN, r_multiple=2.0)

        with pytest.raises(ValidationFailedError):
            journal.close_entry(entry, outcome=Outcome.LOSS, r_multiple=-1.0)

        assert entry.after.outcome is Outcome.WIN
        assert entry.after.r_multiple == 2.0

    def test_closing_before_opening_is_refused(self):
        entry = open_entry()

        with pytest.raises(ValidationFailedError):
            journal.close_entry(
                entry, outcome=Outcome.WIN, r_multiple=1.0,
                at=OPENED_AT - timedelta(minutes=1),
            )

    def test_missing_r_multiple_must_be_explained(self):
        entry = open_entry()

        with pytest.raises(ValidationFailedError):
            journal.close_entry(entry, outcome=Outcome.WIN)

    def test_an_abandoned_entry_may_not_carry_an_r_multiple(self):
        entry = open_entry()

        with pytest.raises(ValidationFailedError) as exc:
            journal.close_entry(entry, outcome=Outcome.ABANDONED, r_multiple=0.0)

        assert "abandoned" in str(exc.value)

    def test_an_abandoned_entry_states_why_it_has_no_r(self):
        entry = open_entry()
        journal.close_entry(entry, outcome=Outcome.ABANDONED)

        assert entry.after.r_multiple is None
        assert entry.after.r_multiple_unavailable_reason

    def test_a_win_with_a_negative_r_is_refused(self):
        """One of the label and the number is a typo, and later nobody knows which."""
        entry = open_entry()

        with pytest.raises(ValidationFailedError):
            journal.close_entry(entry, outcome=Outcome.WIN, r_multiple=-1.5)

    def test_a_loss_with_a_positive_r_is_refused(self):
        entry = open_entry()

        with pytest.raises(ValidationFailedError):
            journal.close_entry(entry, outcome=Outcome.LOSS, r_multiple=1.5)

    def test_after_moment_is_frozen(self):
        entry = open_entry()
        journal.close_entry(entry, outcome=Outcome.LOSS, r_multiple=-1.0)

        with pytest.raises(dataclasses.FrozenInstanceError):
            entry.after.lesson = "it was the broker's fault"  # type: ignore[misc]

    def test_the_dataclass_itself_refuses_a_contradictory_outcome(self):
        """Bypassing `close_entry` must not bypass the cross-check."""
        with pytest.raises(ValidationFailedError):
            journal.AfterMoment(
                outcome=Outcome.WIN,
                closed_at=OPENED_AT,
                prediction_vs_reality=journal.PredictionCheck(available=False),
                r_multiple=-3.0,
            )


class TestLabelAndNumberMustAgree:
    def test_a_breakeven_carrying_a_full_winner_is_refused(self):
        """Scratches are excluded from the win rate but counted in the average
        R, so one mislabelled winner moves the average with nothing to show it."""
        entry = open_entry()

        with pytest.raises(ValidationFailedError) as exc:
            journal.close_entry(entry, outcome=Outcome.BREAKEVEN, r_multiple=5.0)

        assert "breakeven" in str(exc.value)

    def test_a_breakeven_carrying_a_full_loser_is_refused(self):
        entry = open_entry()

        with pytest.raises(ValidationFailedError):
            journal.close_entry(entry, outcome=Outcome.BREAKEVEN, r_multiple=-4.0)

    def test_a_scratch_that_lands_a_little_either_side_of_zero_is_accepted(self):
        """Costs mean a real scratch rarely lands on exactly 0.0 R."""
        entry = open_entry()
        journal.close_entry(entry, outcome=Outcome.BREAKEVEN, r_multiple=-0.05)

        assert entry.after.r_multiple == pytest.approx(-0.05)

    def test_a_win_of_exactly_zero_r_is_refused(self):
        entry = open_entry()

        with pytest.raises(ValidationFailedError):
            journal.close_entry(entry, outcome=Outcome.WIN, r_multiple=0.0)

    def test_a_loss_of_exactly_zero_r_is_refused(self):
        entry = open_entry()

        with pytest.raises(ValidationFailedError):
            journal.close_entry(entry, outcome=Outcome.LOSS, r_multiple=0.0)

    def test_a_mislabelled_scratch_cannot_move_the_average(self):
        """The reproduction: 19 wins at 1.0 R and one BREAKEVEN at +5.0 R
        reported an average of 1.2."""
        clean = closed_entries(20, outcome=Outcome.WIN, r_multiple=1.0)
        scratch = open_entry()

        with pytest.raises(ValidationFailedError):
            journal.close_entry(
                scratch, outcome=Outcome.BREAKEVEN, r_multiple=5.0,
                at=OPENED_AT + timedelta(hours=6),
            )

        summary = journal.summarise([*clean, scratch])
        assert summary.average_r == pytest.approx(1.0)


class TestGeneratedTextIsMarked:
    def test_a_filled_in_reason_is_flagged_as_generated(self):
        """An explanation nobody wrote must not read later as one somebody did."""
        entry = open_entry()
        journal.close_entry(entry, outcome=Outcome.ABANDONED)

        assert entry.after.r_multiple_unavailable_reason_generated is True
        assert entry.as_dict()["after"]["r_multiple_unavailable_reason_generated"] is True

    def test_an_authors_own_reason_is_not_flagged(self):
        entry = open_entry()
        journal.close_entry(
            entry,
            outcome=Outcome.ABANDONED,
            r_multiple_unavailable_reason="the session filter fired before entry",
        )

        assert entry.after.r_multiple_unavailable_reason_generated is False
        assert "session filter" in entry.after.r_multiple_unavailable_reason


class TestPredictionVersusReality:
    def test_a_recorded_probability_is_scored(self):
        entry = open_entry(probability=0.6)
        journal.close_entry(entry, outcome=Outcome.WIN, r_multiple=2.0)

        check = entry.after.prediction_vs_reality
        assert check.available is True
        assert check.realised == 1.0
        assert check.surprise == pytest.approx(0.4)
        assert check.brier == pytest.approx(0.16)

    def test_surprise_is_signed(self):
        """Over-confidence and timid correctness are different lessons."""
        entry = open_entry(probability=0.8)
        journal.close_entry(entry, outcome=Outcome.LOSS, r_multiple=-1.0)

        assert entry.after.prediction_vs_reality.surprise == pytest.approx(-0.8)

    def test_no_probability_means_no_comparison_not_a_zero(self):
        """The central refusal: an unscored entry is not a 50% forecast."""
        entry = open_entry(
            probability=None, probability_unavailable_reason="source is uncalibrated"
        )
        journal.close_entry(entry, outcome=Outcome.WIN, r_multiple=2.0)

        check = entry.after.prediction_vs_reality
        assert check.available is False
        assert check.probability is None
        assert check.brier is None
        assert check.surprise is None
        assert "uncalibrated" in check.reason

    def test_the_unavailable_payload_carries_no_numbers_at_all(self):
        """Asserts the reason's content, not the reason against itself: the
        previous version compared `payload["reason"]` with itself and so
        checked nothing about it."""
        entry = open_entry(
            probability=None, probability_unavailable_reason="no calibration yet"
        )
        journal.close_entry(entry, outcome=Outcome.LOSS, r_multiple=-1.0)

        payload = entry.after.prediction_vs_reality.as_dict()

        assert set(payload) == {"available", "reason"}
        assert payload["available"] is False
        assert "no calibration yet" in payload["reason"]

    def test_a_scratch_resolves_the_trade_but_not_the_thesis(self):
        entry = open_entry(probability=0.6)
        journal.close_entry(entry, outcome=Outcome.BREAKEVEN, r_multiple=0.0)

        check = entry.after.prediction_vs_reality
        assert check.available is False
        assert "thesis" in check.reason

    def test_an_abandoned_entry_never_resolved_its_forecast(self):
        entry = open_entry(probability=0.6)
        journal.close_entry(entry, outcome=Outcome.ABANDONED)

        assert entry.after.prediction_vs_reality.available is False
        assert "never" in entry.after.prediction_vs_reality.reason


class TestInvalidationRecord:
    def test_unassessed_invalidation_stays_none(self):
        """Nobody checked and it did not fire are different facts."""
        entry = open_entry()
        journal.close_entry(entry, outcome=Outcome.LOSS, r_multiple=-1.0)

        assert entry.after.invalidation_triggered is None

    def test_an_observed_trigger_survives_the_close(self):
        entry = open_entry()
        journal.observe(
            entry, ObservationKind.INVALIDATION_TRIGGERED, "H4 closed at 1.0880"
        )
        journal.close_entry(entry, outcome=Outcome.LOSS, r_multiple=-1.0)

        assert entry.after.invalidation_triggered is True

    def test_closing_cannot_deny_an_observed_trigger(self):
        """Writing the lesson is exactly when awkward evidence tends to vanish."""
        entry = open_entry()
        journal.observe(
            entry, ObservationKind.INVALIDATION_TRIGGERED, "H4 closed at 1.0880"
        )

        with pytest.raises(ValidationFailedError):
            journal.close_entry(
                entry, outcome=Outcome.LOSS, r_multiple=-1.0,
                invalidation_triggered=False,
            )

    def test_a_deliberate_no_is_recorded_as_false(self):
        entry = open_entry()
        journal.close_entry(
            entry, outcome=Outcome.LOSS, r_multiple=-1.0, invalidation_triggered=False
        )

        assert entry.after.invalidation_triggered is False


# =================================================================== summary
class TestSummary:
    def test_an_empty_journal_reports_nothing_rather_than_zeroes(self):
        summary = journal.summarise([])

        assert summary.available is False
        assert summary.win_rate is None
        assert summary.average_r is None
        assert summary.entries == 0

    def test_below_twenty_entries_no_percentage_is_quoted(self):
        entries = closed_entries(19, outcome=Outcome.WIN, r_multiple=1.0)

        summary = journal.summarise(entries)

        assert summary.available is False
        assert summary.win_rate is None
        assert summary.average_r is None
        assert "19 closed entries" in summary.reason

    def test_counts_are_reported_even_when_rates_are_not(self):
        """Counts are observations; rates are claims. Only the claims go null."""
        entries = closed_entries(5, outcome=Outcome.WIN, r_multiple=1.0)

        summary = journal.summarise(entries)

        assert summary.closed == 5
        assert summary.wins == 5
        assert summary.as_dict()["win_rate"] is None

    def test_twenty_decided_entries_is_enough(self):
        entries = closed_entries(20, outcome=Outcome.WIN, r_multiple=1.0)

        summary = journal.summarise(entries)

        assert summary.available is True
        assert summary.win_rate == pytest.approx(1.0)
        assert summary.average_r == pytest.approx(1.0)

    def test_open_entries_are_not_counted_as_closed(self):
        entries = closed_entries(20, outcome=Outcome.WIN, r_multiple=1.0)
        entries.append(open_entry())

        summary = journal.summarise(entries)

        assert summary.entries == 21
        assert summary.closed == 20
        assert summary.open_entries == 1

    def test_win_rate_excludes_scratches_and_abandoned_entries(self):
        """Rewritten: the previous version used 10 wins and 5 losses among 20
        closed entries and asserted a win rate off a 15-entry denominator,
        which blessed the defect this suite now refuses. The exclusion rule is
        the same; the sample is now large enough to quote."""
        entries = (
            closed_entries(20, outcome=Outcome.WIN, r_multiple=1.0)
            + closed_entries(10, outcome=Outcome.LOSS, r_multiple=-1.0)
            + closed_entries(3, outcome=Outcome.BREAKEVEN, r_multiple=0.0)
            + closed_entries(2, outcome=Outcome.ABANDONED, r_multiple=None)
        )

        summary = journal.summarise(entries)

        assert summary.decided == 30
        assert summary.win_rate == pytest.approx(20 / 30, abs=1e-4)
        assert any("scratch" in note and "abandoned" in note for note in summary.notes)

    def test_a_win_rate_needs_twenty_decided_entries_not_twenty_closed(self):
        """The critical one: eighteen abandoned theses and two trades are
        twenty closed entries and a two-trade win rate. Uncertainty about the
        eighteen must not buy the two a headline."""
        entries = (
            closed_entries(18, outcome=Outcome.ABANDONED, r_multiple=None)
            + closed_entries(1, outcome=Outcome.WIN, r_multiple=1.0)
            + closed_entries(1, outcome=Outcome.LOSS, r_multiple=-1.0)
        )

        summary = journal.summarise(entries)

        assert summary.closed == 20
        assert summary.decided == 2
        assert summary.win_rate is None
        assert summary.average_r is None
        assert summary.available is False
        assert any("decided" in note for note in summary.notes)

    def test_average_r_needs_twenty_recorded_r_multiples(self):
        entries = (
            closed_entries(18, outcome=Outcome.WIN, r_multiple=None,
                           r_reason="broker fill data unavailable")
            + closed_entries(2, outcome=Outcome.WIN, r_multiple=5.0)
        )

        summary = journal.summarise(entries)

        assert summary.r_sample == 2
        assert summary.average_r is None
        assert summary.average_r_coverage is None

    def test_a_measured_zero_r_counts_but_a_missing_one_does_not(self):
        """The distinction the average would otherwise quietly destroy.

        Rewritten with a 20-entry R sample: the average now carries its own
        gate, so the previous 18-entry version no longer quoted a number."""
        entries = (
            closed_entries(20, outcome=Outcome.BREAKEVEN, r_multiple=0.0)
            + closed_entries(2, outcome=Outcome.WIN, r_multiple=None,
                             r_reason="broker fill data unavailable")
        )

        summary = journal.summarise(entries)

        assert summary.r_sample == 20
        assert summary.average_r == pytest.approx(0.0)
        assert summary.average_r_coverage == pytest.approx(20 / 22, abs=1e-4)
        assert any("not counted as zero" in note for note in summary.notes)

    def test_average_r_is_unavailable_when_no_entry_recorded_one(self):
        entries = closed_entries(
            20, outcome=Outcome.WIN, r_multiple=None, r_reason="no fill data"
        )

        summary = journal.summarise(entries)

        assert summary.average_r is None
        assert summary.r_sample == 0

    def test_average_r_is_withheld_when_most_traded_entries_recorded_none(self):
        """Half the trades unmeasured is not an average of the trades."""
        entries = (
            closed_entries(20, outcome=Outcome.WIN, r_multiple=3.0)
            + closed_entries(60, outcome=Outcome.LOSS, r_multiple=None,
                             r_reason="broker fill data unavailable")
        )

        summary = journal.summarise(entries)

        assert summary.r_sample == 20
        assert summary.average_r is None
        assert any("below the" in note and "reached the market" in note
                   for note in summary.notes)

    def test_invalidation_share_is_reported_when_enough_were_assessed(self):
        entries = (
            closed_entries(8, outcome=Outcome.LOSS, r_multiple=-1.0,
                           invalidation_triggered=True)
            + closed_entries(12, outcome=Outcome.WIN, r_multiple=1.0,
                             invalidation_triggered=False)
        )

        summary = journal.summarise(entries)

        assert summary.invalidation_assessed == 20
        assert summary.invalidation_triggered_share == pytest.approx(0.4)

    def test_a_published_share_carries_its_coverage(self):
        entries = (
            closed_entries(8, outcome=Outcome.LOSS, r_multiple=-1.0,
                           invalidation_triggered=True)
            + closed_entries(12, outcome=Outcome.WIN, r_multiple=1.0,
                             invalidation_triggered=False)
        )

        summary = journal.summarise(entries)

        assert summary.invalidation_coverage == pytest.approx(1.0)
        assert summary.as_dict()["invalidation_coverage"] == pytest.approx(1.0)

    def test_a_published_win_rate_carries_its_denominator(self):
        entries = (
            closed_entries(20, outcome=Outcome.WIN, r_multiple=1.0)
            + closed_entries(20, outcome=Outcome.ABANDONED, r_multiple=None)
        )

        summary = journal.summarise(entries)

        assert summary.decided == 20
        assert summary.win_rate == pytest.approx(1.0)
        assert summary.win_rate_coverage == pytest.approx(0.5)
        assert summary.as_dict()["decided"] == 20

    def test_a_share_resting_on_a_sliver_of_the_journal_is_withheld(self):
        """20 assessed of 500 closed reported a flawless 1.0 with no caveat:
        the 480 nobody checked were missing from numerator and denominator
        both, so the reader had nothing to correct the number with."""
        entries = (
            closed_entries(20, outcome=Outcome.LOSS, r_multiple=-1.0,
                           invalidation_triggered=True)
            + closed_entries(480, outcome=Outcome.LOSS, r_multiple=-1.0)
        )

        summary = journal.summarise(entries)

        assert summary.invalidation_assessed == 20
        assert summary.invalidation_triggered == 20
        assert summary.invalidation_triggered_share is None
        assert summary.invalidation_coverage is None
        assert any("4%" in note for note in summary.notes)

    def test_an_unassessed_invalidation_is_not_counted_as_untriggered(self):
        """Otherwise a journal nobody checks reports a flawless 0% trigger rate."""
        entries = closed_entries(20, outcome=Outcome.LOSS, r_multiple=-1.0)

        summary = journal.summarise(entries)

        assert summary.invalidation_assessed == 0
        assert summary.invalidation_triggered_share is None
        assert any("below the" in note for note in summary.notes)

    def test_losses_the_thesis_never_saw_coming_are_counted(self):
        entries = (
            closed_entries(6, outcome=Outcome.LOSS, r_multiple=-1.0,
                           invalidation_triggered=True)
            + closed_entries(4, outcome=Outcome.LOSS, r_multiple=-1.0,
                             invalidation_triggered=False)
            + closed_entries(10, outcome=Outcome.WIN, r_multiple=2.0,
                             invalidation_triggered=False)
        )

        summary = journal.summarise(entries)

        assert summary.losses_assessed == 10
        assert summary.unanticipated_losses == 4

    def test_one_assessed_loss_does_not_become_a_hundred_percent_finding(self):
        """A note is a claim too, and this one was quoted off n=1 — and even on
        a summary that came back unavailable."""
        entry = open_entry()
        journal.close_entry(
            entry, outcome=Outcome.LOSS, r_multiple=-1.0, invalidation_triggered=False
        )

        summary = journal.summarise([entry])

        assert summary.losses_assessed == 1
        assert summary.unanticipated_losses == 1
        assert not any("1 of 1 assessed losses" in note for note in summary.notes)

    def test_a_journal_that_measured_nothing_is_not_available(self):
        """`available` has to come from a statistic, not from a count of rows.

        Twenty abandoned theses measure no win rate, no average R and no
        invalidation share; a consumer gating on `available` must not get a
        green light from them."""
        entries = closed_entries(20, outcome=Outcome.ABANDONED, r_multiple=None)

        summary = journal.summarise(entries)

        assert summary.closed == 20
        assert summary.win_rate is None
        assert summary.average_r is None
        assert summary.invalidation_triggered_share is None
        assert summary.available is False
        assert "no statistic" in summary.reason

    def test_availability_survives_on_a_single_published_statistic(self):
        """One statistic with a real sample is enough — and only that one is
        published; the others stay null with their reasons in the notes."""
        entries = (
            closed_entries(10, outcome=Outcome.ABANDONED, r_multiple=None,
                           invalidation_triggered=True)
            + closed_entries(10, outcome=Outcome.ABANDONED, r_multiple=None,
                             invalidation_triggered=False)
        )

        summary = journal.summarise(entries)

        assert summary.invalidation_triggered_share == pytest.approx(0.5)
        assert summary.win_rate is None
        assert summary.average_r is None
        assert summary.available is True

    def test_summary_payload_never_invents_a_rate(self):
        payload = journal.summarise(closed_entries(3, outcome=Outcome.WIN,
                                                   r_multiple=1.0)).as_dict()

        assert payload["available"] is False
        for key in (
            "win_rate", "win_rate_coverage", "average_r", "average_r_coverage",
            "invalidation_triggered_share", "invalidation_coverage",
        ):
            assert payload[key] is None


class TestRecordsOnly:
    def test_the_module_imports_nothing_that_could_reach_a_broker_or_a_store(self):
        """Behaviour, not vocabulary.

        The previous version scanned attribute names for words like "execute"
        and "persist", so it would have missed any violation that chose
        different words. This reads the module's actual imports: nothing here
        can place an order or write to a database if nothing that does either
        is importable from it.
        """
        tree = ast.parse(pathlib.Path(journal.__file__).read_text(encoding="utf-8"))

        roots: set[str] = set()
        app_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".")[0])
                if node.module.startswith("app"):
                    app_modules.add(node.module)

        assert roots <= {
            "__future__", "collections", "dataclasses", "datetime", "enum",
            "math", "statistics", "typing", "uuid", "app",
        }
        assert app_modules <= {"app.core.enums", "app.core.errors"}

    def test_an_entry_serialises_all_three_moments(self):
        entry = open_entry()
        journal.observe(entry, ObservationKind.MARKET_CHANGE, "momentum faded")
        journal.close_entry(
            entry, outcome=Outcome.WIN, r_multiple=1.8, lesson="trail wider"
        )

        payload = entry.as_dict()

        assert payload["before"]["invalidation"] == "H4 closes below 1.0900"
        assert payload["during"]["count"] == 1
        assert payload["after"]["lesson"] == "trail wider"
        assert payload["closed"] is True
