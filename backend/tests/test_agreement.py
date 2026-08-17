"""Whether the timeframes agree, and the two ways that question is answered
wrongly.

A stretch on one timeframe and nowhere else is usually the last bar. The same
stretch on five is a move. Counting the agreement is not the same as averaging
the stretches - averaging lets one violent short timeframe outvote four calm
long ones, which is the opposite of what confirmation means.
"""

from __future__ import annotations

from app.brain.crosssection import MIN_AGREEMENT, agreement, confirmed


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
