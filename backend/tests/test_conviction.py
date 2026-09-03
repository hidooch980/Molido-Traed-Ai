"""Conviction shrinks a trade. It never enlarges one.

That invariant is the reason this module exists, so it is tested first, from
several directions, including the arithmetic path that would break it.

The rest is the matrix the specification asks for, with one deliberate
departure recorded in `MIN_MULTIPLIER`: a weak signal is sized down rather
than refused. On this deployment's current evidence - nothing calibrated on
its forward record, no regime confirmed out of sample - every score is low,
so a veto on low scores would stop trading altogether, and stopping trading
is the kill switch's job and a person's decision. What still refuses here is
what already refused upstream: data too stale to size against, and an
execution cost above what the measured edge supports.
"""

from __future__ import annotations

import pytest

from app.execution import conviction as cv
from app.execution.conviction import Factor, Tier


def good_factors(**over) -> list[Factor]:
    defaults = dict(
        agreeing=4,
        opposing=0,
        council=4,
        cost_r=0.02,
        ceiling_r=0.25,
        age_bars=0.2,
        calibrated_sources=2,
        aligned=True,
    )
    defaults.update(over)
    return [
        cv.agreement_factor(
            agreeing=defaults["agreeing"],
            opposing=defaults["opposing"],
            council=defaults["council"],
        ),
        cv.cost_factor(cost_r=defaults["cost_r"], ceiling_r=defaults["ceiling_r"]),
        cv.freshness_factor(age_bars=defaults["age_bars"]),
        cv.calibration_factor(calibrated_sources=defaults["calibrated_sources"]),
        cv.regime_factor(aligned=defaults["aligned"], detail="dispersion high"),
    ]


def judge(*, side="long", proven=True, **over) -> cv.Conviction:
    return cv.assess(side=side, factors=good_factors(**over), proven_edge=proven)


# ================================================== the invariant that matters
class TestItCanOnlyEverShrink:
    def test_a_perfect_signal_gets_exactly_the_permitted_risk_and_no_more(self):
        """Perfect means every factor at its best: unanimous, free to execute,
        current to the tick. Anything less is already a discount - the ordinary
        case below scores 97 on a 0.02 R cost and a fifth of a bar of age."""
        best = judge(cost_r=0.0, age_bars=0.0)

        assert best.score == 100
        assert best.risk_multiplier == 1.0

    def test_an_ordinary_good_trade_is_already_slightly_discounted(self):
        ordinary = judge()

        assert 90 <= ordinary.score < 100
        assert ordinary.risk_multiplier < 1.0

    @pytest.mark.parametrize("agreeing,council", [(4, 4), (8, 8), (20, 20)])
    def test_no_combination_of_inputs_exceeds_one(self, agreeing, council):
        result = judge(agreeing=agreeing, cost_r=0.0)

        assert result.risk_multiplier <= 1.0

    def test_the_cap_holds_when_the_inputs_are_out_of_range(self):
        """The arithmetic path, forced past its own bounds. `min` is
        load-bearing and this is the test that says so: even handed a strength
        and a confidence above 1, which `assess` would never produce, the
        multiplier cannot exceed the risk the gates permitted."""
        forced = cv.Conviction(signal_strength=4.0, confidence=3.0, proven_edge=True)
        forced.factors = good_factors(cost_r=0.0, age_bars=0.0)

        assert forced.score > 100
        assert forced.risk_multiplier == 1.0

    def test_out_of_range_inputs_cannot_lift_an_ordinary_trade_above_its_own_merit(self):
        """The multiplier follows the per-trade factors, so inflating the
        strength and confidence fields cannot buy size the factors did not."""
        forced = cv.Conviction(signal_strength=4.0, confidence=3.0, proven_edge=True)
        forced.factors = good_factors()

        assert forced.risk_multiplier < 1.0

    def test_a_blocked_trade_gets_zero_not_a_small_number(self):
        """"Do not trade" and "trade a little" are different instructions."""
        blocked = judge(age_bars=99.0)

        assert blocked.allowed is False
        assert blocked.risk_multiplier == 0.0

    def test_a_weak_trade_is_a_fraction_of_the_permitted_risk(self):
        weak = judge(agreeing=3, opposing=1, calibrated_sources=0)

        assert weak.allowed is True
        assert cv.MIN_MULTIPLIER <= weak.risk_multiplier < 1.0

    def test_conviction_sizes_and_does_not_veto(self):
        """On today's evidence - nothing calibrated, no confirmed regime -
        the reported score is low. A veto on that would be a halt wearing a
        filter's clothes, and the halt already exists in the kill switch
        where a person operates it."""
        thin = judge(agreeing=1, opposing=1, calibrated_sources=0, aligned=None)

        assert thin.score < 40
        assert thin.allowed is True
        assert thin.risk_multiplier < 1.0


# ============================================================ the test matrix
class TestWeakSignalsAreHarderToExecute:
    def test_a_lone_brain_against_opposition_scores_nothing(self):
        result = judge(agreeing=1, opposing=2)

        assert result.signal_strength == 0.0
        assert result.score == 0
        # Still permitted - the consensus rule upstream is what refuses a
        # motion nobody seconded - but at the smallest size this can produce.
        assert result.risk_multiplier == cv.MIN_MULTIPLIER

    def test_opposition_subtracts_from_agreement(self):
        """Three for and two against is not three for and none."""
        clean = cv.agreement_factor(agreeing=3, opposing=0)
        contested = cv.agreement_factor(agreeing=3, opposing=2)

        assert clean.score > contested.score

    def test_silence_is_not_disagreement(self):
        """A brain that decided nothing about this symbol was looking
        elsewhere. Whether one voice is enough to trade on is the consensus
        rule's question, and the operator sets it."""
        alone = cv.agreement_factor(agreeing=1, opposing=0)

        assert alone.score == 1.0
        assert "of 1 that spoke" in alone.detail

    def test_nobody_speaking_is_unobserved_rather_than_zero(self):
        silent = cv.agreement_factor(agreeing=0, opposing=0)

        assert silent.available is False

    def test_a_low_score_shrinks_the_position_rather_than_refusing_it(self):
        strong = judge()
        thin = judge(agreeing=2, opposing=1, calibrated_sources=0, aligned=None)

        assert thin.score < strong.score
        assert thin.risk_multiplier < strong.risk_multiplier
        assert thin.allowed is True


class TestStrongRequiresAProvenEdge:
    def test_without_one_the_top_tier_is_unreachable(self):
        result = judge(proven=False)

        assert result.score >= 85
        assert result.tier is Tier.VALID
        assert result.tier is not Tier.STRONG

    def test_with_one_it_is_reachable(self):
        assert judge(proven=True).tier is Tier.STRONG

    def test_the_registry_is_empty_today_so_nothing_live_is_strong(self):
        from app.learning import edge as registry

        allowed, _why = registry.live_trading_allowed()

        assert allowed is False
        assert judge(proven=allowed).tier is not Tier.STRONG


class TestBlockingFactors:
    def test_stale_data_blocks_whatever_else_is_true(self):
        result = judge(age_bars=9.0)

        assert result.allowed is False
        assert any("beyond the" in r for r in result.blocks)

    def test_an_unknown_feed_age_blocks(self):
        result = judge(age_bars=None)

        assert result.allowed is False
        assert any("unknown is stale" in r for r in result.blocks)

    def test_a_cost_at_or_above_the_ceiling_blocks(self):
        result = judge(cost_r=0.30, ceiling_r=0.25)

        assert result.allowed is False

    def test_a_zero_ceiling_blocks_because_the_edge_supports_no_cost(self):
        result = judge(ceiling_r=0.0)

        assert result.allowed is False
        assert any("no cost at all" in r for r in result.blocks)

    def test_an_unmeasured_ceiling_blocks_rather_than_being_assumed_generous(self):
        result = judge(ceiling_r=None)

        assert result.allowed is False


class TestMissingIsNotNeutral:
    def test_an_unobserved_factor_lowers_confidence(self):
        seen = judge()
        unseen = judge(aligned=None)

        assert unseen.confidence < seen.confidence
        assert "regime_alignment" in [f.name for f in unseen.unavailable]

    def test_it_is_never_treated_as_a_pass(self):
        result = judge(calibrated_sources=None, aligned=None)

        assert result.confidence < judge().confidence
        assert len(result.unavailable) == 2

    def test_no_factors_at_all_is_no_confidence(self):
        result = cv.assess(side="long", factors=[], proven_edge=True)

        assert result.confidence == 0.0
        assert result.score == 0


class TestTheSignedStrength:
    @pytest.mark.parametrize("side,sign", [("long", 1), ("buy", 1), ("short", -1), ("sell", -1)])
    def test_the_sign_is_the_side(self, side, sign):
        result = judge(side=side)

        assert result.signal_strength * sign > 0

    def test_an_unknown_side_carries_no_strength(self):
        assert judge(side="sideways").signal_strength == 0.0

    def test_the_magnitude_is_agreement_not_an_invented_score(self):
        unopposed = judge(agreeing=4, opposing=0)
        contested = judge(agreeing=4, opposing=1)

        # (4 - 1) / 5 = 0.6: the margin as a share of the voters.
        assert unopposed.signal_strength == pytest.approx(1.0)
        assert contested.signal_strength == pytest.approx(0.6)


class TestThePayload:
    def test_it_names_every_block_and_every_unobserved_factor(self):
        payload = judge(age_bars=None, calibrated_sources=None).as_dict()

        # Blocked by the stale feed, which was a gate upstream too.
        assert payload["allowed"] is False
        assert payload["blocking_reasons"]
        assert set(payload["unobserved"]) >= {"data_freshness", "calibration"}
        assert payload["risk_multiplier"] == 0.0
        assert "never enlarge" in payload["note"]

    def test_the_score_is_strength_times_confidence(self):
        result = judge(agreeing=2, opposing=0, council=4)

        assert result.score == int(round(abs(result.signal_strength) * result.confidence * 100))


class TestTheCycleIntegration:
    """The two behaviours the wiring has to get right, tested where the
    wiring is: `tests/test_autotrade.py` covers the cycle end to end, and
    these state the contract the cycle relies on."""

    def test_the_multiplier_is_the_only_thing_that_touches_size(self):
        """Nothing else in the payload is a number the caller should multiply
        risk by - a second one would be a second opinion about the same
        decision."""
        payload = judge().as_dict()

        multipliers = [
            key
            for key, value in payload.items()
            if isinstance(value, float) and 0.0 < value <= 1.0 and "multiplier" in key
        ]
        assert multipliers == ["risk_multiplier"]

    def test_an_account_wide_factor_does_not_move_the_size(self):
        """Calibration is one fact about the deployment, identical for every
        candidate in the cycle. It belongs in the score and the tier; putting
        it in the multiplier would not rank anything, it would just scale the
        whole account down."""
        with_calibration = judge(calibrated_sources=3)
        without = judge(calibrated_sources=0)

        assert without.score < with_calibration.score
        assert without.risk_multiplier == with_calibration.risk_multiplier

    def test_a_per_trade_factor_does_move_it(self):
        cheap = judge(cost_r=0.01)
        dear = judge(cost_r=0.20)

        assert dear.risk_multiplier < cheap.risk_multiplier
