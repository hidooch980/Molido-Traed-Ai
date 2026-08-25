"""Whether the timeframes agree, and the two ways that question is answered
wrongly.

A stretch on one timeframe and nowhere else is usually the last bar. The same
stretch on five is a move. Counting the agreement is not the same as averaging
the stretches - averaging lets one violent short timeframe outvote four calm
long ones, which is the opposite of what confirmation means.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.brain import crosssection
from app.brain.crosssection import MIN_AGREEMENT, agreement, confirmed

AT = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)


class TestCountingNotAveraging:
    def test_unanimity_is_total(self):
        assert agreement([1.2, 0.9, 1.1, 0.8, 1.0]) == (5, 5, 1.0)

    def test_one_dissenter_is_counted_not_cancelled(self):
        assert agreement([1.2, 0.9, 1.1, -0.8, 1.0]) == (4, 5, 0.8)

    def test_the_majority_direction_wins_either_way(self):
        """Down is a direction, not a failure to be up."""
        assert agreement([-1.2, -0.9, -1.1, 0.8, -1.0]) == (4, 5, 0.8)

    def test_one_violent_timeframe_does_not_outvote_four_calm_ones(self):
        """The whole reason this counts instead of averaging: the mean of
        these is negative, and four of the five say up."""
        loud = [0.4, 0.3, 0.5, 0.4, -9.0]

        agreeing, usable, ratio = agreement(loud)

        assert (agreeing, usable) == (4, 5)
        assert ratio == 0.8
        assert sum(loud) < 0  # the average would have said the opposite


class TestAbsentIsNotAgainst:
    def test_a_timeframe_with_no_opinion_leaves_both_sides(self):
        """None is too little history to have a view, not a vote against."""
        assert agreement([1.0, None, 1.0]) == (2, 2, 1.0)

    def test_a_flat_timeframe_is_not_a_direction(self):
        assert agreement([1.0, 0.0, 1.0]) == (2, 2, 1.0)

    def test_the_total_says_how_many_actually_voted(self):
        """So a caller can tell unanimity-of-five from unanimity-of-one."""
        _, usable, _ = agreement([1.0, None, None, None, None])

        assert usable == 1

    def test_nothing_usable_is_no_evidence_rather_than_no_agreement(self):
        """Zero out of zero is not zero agreement. A ratio of 0.0 would read
        as total disagreement and be compared against a threshold."""
        assert agreement([None, None, 0.0]) == (0, 0, None)


class TestActingOnIt:
    def test_a_clear_majority_acts(self):
        assert confirmed([1.2, 0.9, 1.1, -0.8, 1.0]) is True

    def test_a_thin_majority_holds(self):
        assert confirmed([1.2, 0.9, 1.1, -0.8, -1.0]) is False

    def test_one_timeframe_agreeing_with_itself_is_not_confirmation(self):
        """It scores a perfect 1.0 and would pass every threshold. This is
        the case the whole check exists to catch."""
        assert confirmed([3.0, None, None, None, None]) is False

    def test_two_agreeing_timeframes_are_enough_to_be_asked(self):
        assert confirmed([1.0, 1.0]) is True

    def test_nothing_usable_holds(self):
        assert confirmed([None, None]) is False

    def test_the_threshold_is_settable_for_a_stricter_caller(self):
        four_of_five = [1.2, 0.9, 1.1, -0.8, 1.0]

        assert confirmed(four_of_five, minimum=0.8) is True
        assert confirmed(four_of_five, minimum=1.0) is False

    def test_the_default_is_stricter_than_two_in_three(self):
        """Two out of three is a coin landing the same way twice."""
        assert MIN_AGREEMENT > 2 / 3


class TestConfirmationInsideTheRanking:
    """Wired into `rank` as an optional filter, so the existing contract is
    unchanged and a caller that offers no confirmations ranks as before."""

    @staticmethod
    def series(base: float, drift: float) -> dict[str, object]:
        closes = [base + drift * i for i in range(60)]
        return {
            "closes": closes,
            "bars": [(c + 0.5, c - 0.5, c) for c in closes],
        }

    def snapshot(self, count: int = 24) -> dict[str, object]:
        # Distinct drifts so the ranking has real tails rather than a tie.
        return {
            f"SYM{i:02d}": self.series(100.0 + i, 0.1 + i * 0.01)
            for i in range(count)
        }

    def test_no_confirmations_ranks_exactly_as_before(self):
        snap = self.snapshot()

        without = crosssection.rank(snap, at=AT, universe=None)
        empty = crosssection.rank(snap, at=AT, universe=None, confirmations={})

        assert [r.symbol for r in without.longs] == [r.symbol for r in empty.longs]
        assert without.skipped == empty.skipped

    def test_a_symbol_whose_timeframes_disagree_is_skipped_by_name(self):
        snap = self.snapshot()
        # SYM00 rises here; three other timeframes say it is falling.
        result = crosssection.rank(
            snap, at=AT, universe=None, confirmations={"SYM00": [-1.0, -1.0, -1.0]}
        )

        assert all(r.symbol != "SYM00" for r in result.longs + result.shorts)
        assert any("SYM00" in s and "timeframes agree" in s for s in result.skipped)

    def test_a_symbol_whose_timeframes_agree_survives(self):
        snap = self.snapshot()

        result = crosssection.rank(
            snap, at=AT, universe=None, confirmations={"SYM00": [1.0, 1.0, 1.0]}
        )

        assert not any("SYM00" in s for s in result.skipped)

    def test_a_symbol_absent_from_the_map_is_not_refused(self):
        """No confirmation offered is not confirmation withheld. Refusing on
        absence would empty the ranking the first time a caller passed a
        partial map."""
        snap = self.snapshot()

        result = crosssection.rank(
            snap, at=AT, universe=None, confirmations={"SYM00": [1.0, 1.0]}
        )

        assert not any("timeframes agree" in s for s in result.skipped)

    def test_the_ranked_timeframe_votes_alongside_the_others(self):
        """One dissenting other timeframe against this one plus one agreeing
        other is 2 of 3 - under the threshold, so it is refused."""
        snap = self.snapshot()

        result = crosssection.rank(
            snap, at=AT, universe=None, confirmations={"SYM00": [1.0, -1.0]}
        )

        assert any("SYM00" in s and "2 of 3" in s for s in result.skipped)

    def test_the_skip_reason_names_the_count_and_the_threshold(self):
        snap = self.snapshot()

        result = crosssection.rank(
            snap, at=AT, universe=None, confirmations={"SYM00": [-1.0, -1.0, -1.0]}
        )

        reason = next(s for s in result.skipped if "SYM00" in s)

        assert "1 of 4" in reason
        assert "75%" in reason


class TestConfirmationIsDirectional:
    """The flaw the ranking test caught: agreement among timeframes is not the
    same as agreement with the reading being acted on."""

    def test_three_against_one_is_not_confirmation_of_the_one(self):
        """75% of them agree - with each other, in the opposite direction."""
        assert crosssection.confirmed([1.0, -1.0, -1.0, -1.0]) is True
        assert crosssection.confirmed([1.0, -1.0, -1.0, -1.0], direction=1.0) is False

    def test_agreeing_with_the_reading_confirms_it(self):
        assert crosssection.confirmed([1.0, 1.0, 1.0, -1.0], direction=1.0) is True

    def test_the_same_votes_confirm_the_other_way_too(self):
        assert crosssection.confirmed([-1.0, -1.0, -1.0, 1.0], direction=-1.0) is True

    def test_a_flat_reading_confirms_nothing(self):
        """Zero is not a direction to agree with."""
        assert crosssection.confirmed([1.0, 1.0, 1.0], direction=0.0) is False

    def test_one_usable_timeframe_still_refuses_with_a_direction(self):
        assert crosssection.confirmed([2.0, None, None], direction=2.0) is False
