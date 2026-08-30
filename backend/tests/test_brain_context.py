"""The third brain: a brake, not a second opinion.

Everything here defends one invariant - the context brain can only make a
position smaller. The day a test in this file has to change because a verdict
got bigger, the brain has stopped being a brake and become a trader.
"""

from __future__ import annotations

from app.brain import context
from app.brain.context import Stance
from app.core.enums import Decision


class TestTheInvariant:
    def test_every_stance_scales_to_at_most_one(self):
        assert all(scale <= 1.0 for scale in context.SCALES.values())

    def test_no_input_combination_can_scale_above_one(self):
        """Brute force over the corners of the input space."""
        for decision in (Decision.BUY, Decision.SELL):
            for tilt in (None, -0.9, -0.6, 0.0, 0.6, 0.9):
                for diff in (None, -3.0, 0.0, 3.0):
                    for close in (None, 600.0, 90000.0):
                        verdict = context.read(
                            decision,
                            crowd_tilt=tilt,
                            rate_differential=diff,
                            seconds_to_close=close,
                            gap_seconds=None if close is None else 200000.0,
                        )
                        assert verdict.scale <= 1.0


class TestCrowding:
    def test_joining_an_extreme_crowd_stands_aside(self):
        verdict = context.read(Decision.BUY, crowd_tilt=0.8)

        assert verdict.stance is Stance.STAND_ASIDE
        assert verdict.scale == 0.0
        assert any("one-sided" in reason for reason in verdict.reasons)

    def test_joining_a_crowded_trade_is_cautioned(self):
        verdict = context.read(Decision.SELL, crowd_tilt=-0.6)

        assert verdict.stance is Stance.CAUTION
        assert verdict.scale == 0.5

    def test_entering_against_the_crowd_is_not_penalised(self):
        """A deliberate v1 line: contrarian entries against extremes are a
        strategy, and this brain's mandate is to brake, not to trade."""
        verdict = context.read(Decision.SELL, crowd_tilt=0.8)

        assert verdict.stance is Stance.CLEAR

    def test_a_balanced_crowd_says_nothing(self):
        verdict = context.read(Decision.BUY, crowd_tilt=0.1)

        assert verdict.stance is Stance.CLEAR
        assert verdict.reasons == []


class TestCarry:
    def test_paying_heavily_to_hold_is_cautioned(self):
        # Long the base while the base rate is 2pp below the quote.
        verdict = context.read(Decision.BUY, rate_differential=-2.0)

        assert verdict.stance is Stance.CAUTION
        assert any("paid for out of the edge" in r for r in verdict.reasons)

    def test_being_paid_to_hold_is_not_rewarded(self):
        """Positive carry must not upgrade anything - the brake invariant."""
        verdict = context.read(Decision.BUY, rate_differential=3.0)

        assert verdict.stance is Stance.CLEAR
        assert verdict.scale == 1.0

    def test_the_sign_follows_the_direction(self):
        # Short the base: a positive differential is what costs.
        verdict = context.read(Decision.SELL, rate_differential=2.0)

        assert verdict.stance is Stance.CAUTION


class TestTheClosingBell:
    def test_a_weekend_gap_two_hours_out_is_cautioned(self):
        verdict = context.read(
            Decision.BUY, seconds_to_close=3600.0, gap_seconds=48 * 3600.0
        )

        assert verdict.stance is Stance.CAUTION

    def test_an_ordinary_overnight_close_is_not(self):
        verdict = context.read(
            Decision.BUY, seconds_to_close=3600.0, gap_seconds=8 * 3600.0
        )

        assert verdict.stance is Stance.CLEAR


class TestAbstention:
    def test_missing_signals_are_named_not_defaulted(self):
        verdict = context.read(Decision.BUY)

        assert set(verdict.abstained) == {"positioning", "policy_rates", "calendar"}
        assert verdict.stance is Stance.CLEAR

    def test_clear_with_abstentions_is_distinguishable_from_checked_clear(self):
        """"Clear because nothing was visible" and "clear because everything
        was checked" must never serialise identically."""
        blind = context.read(Decision.BUY).as_dict()
        checked = context.read(
            Decision.BUY,
            crowd_tilt=0.0,
            rate_differential=0.0,
            seconds_to_close=90000.0,
            gap_seconds=8 * 3600.0,
        ).as_dict()

        assert blind["stance"] == checked["stance"] == "clear"
        assert blind["abstained"] and not checked["abstained"]


class TestSignalsCombine:
    def test_the_worst_signal_wins(self):
        verdict = context.read(
            Decision.BUY,
            crowd_tilt=0.8,          # stand aside
            rate_differential=-2.0,  # caution
        )

        assert verdict.stance is Stance.STAND_ASIDE
        assert len(verdict.reasons) == 2

    def test_two_cautions_do_not_escalate_to_standing_aside(self):
        """Worst-of, not sum-of. Two independent yellow lights are still
        yellow; inventing red from them would be a rule nobody wrote."""
        verdict = context.read(
            Decision.BUY,
            crowd_tilt=0.6,
            rate_differential=-2.0,
        )

        assert verdict.stance is Stance.CAUTION


class TestWait:
    def test_a_wait_needs_no_brake(self):
        verdict = context.read(Decision.WAIT, crowd_tilt=0.9)

        assert verdict.stance is Stance.CLEAR
        assert verdict.abstained == []
        assert "nothing to scale" in verdict.reasons[0]


class TestTheAuditTrail:
    def test_the_verdict_says_what_it_is(self):
        payload = context.read(Decision.BUY).as_dict()

        assert payload["method"] == "rule_based"
        assert payload["version"] == 1
