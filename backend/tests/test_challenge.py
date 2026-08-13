"""Challenge-engine tests (phase 28).

A challenge is lost in the moment a limit prints, not in the review afterwards,
so these tests are almost entirely about refusal: the sizes this module must
not clear, the rules it must not report as satisfied, and the numbers it must
not invent when the account state does not contain them.
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from app.brain import challenge as ch

TODAY = date(2026, 3, 12)


def rules(**overrides) -> ch.ChallengeRules:
    """A conventional two-phase prop-firm rulebook on a 100k account."""
    defaults = dict(
        profit_target_pct=0.10,
        max_daily_drawdown_pct=0.05,
        max_total_drawdown_pct=0.10,
        min_trading_days=4,
        max_trading_days=30,
        max_leverage=30.0,
        max_single_day_profit_share=0.40,
        news_trading_allowed=False,
        weekend_holding_allowed=False,
        max_concurrent_positions=3,
        # Stated rather than assumed: this provider quotes its percentages of
        # the initial account size. With the basis left unspecified the module
        # reads it the stricter way, which is a different rulebook.
        allowance_basis=ch.AllowanceBasis.STARTING_BALANCE,
    )
    defaults.update(overrides)
    return ch.ChallengeRules(**defaults)


def state(**overrides) -> ch.ChallengeState:
    """A healthy, fully-measured account: flat on the day, no open risk."""
    defaults = dict(
        starting_balance=100_000.0,
        current_equity=100_000.0,
        peak_equity=100_000.0,
        daily_starting_equity=100_000.0,
        days_traded=5,
        open_positions=0,
        current_date=TODAY,
        daily_profits={},
        current_balance=100_000.0,
        current_leverage=0.0,
        currency_per_r=500.0,
        in_news_window=False,
        weekend_ahead=False,
    )
    defaults.update(overrides)
    return ch.ChallengeState(**defaults)


# ======================================================== absent versus zero
def uncapped() -> ch.ChallengeRules:
    """A provider whose documentation was read and carries no rule at all.

    Spelled out field by field on purpose. `ChallengeRules()` used to mean this
    and now means the opposite, and a helper that hid the difference behind a
    short name is how the two would drift back together.
    """
    return ch.ChallengeRules(
            profit_target_pct=ch.NOT_IMPOSED,
            max_daily_drawdown_pct=ch.NOT_IMPOSED,
            max_total_drawdown_pct=ch.NOT_IMPOSED,
            min_trading_days=ch.NOT_IMPOSED,
            max_trading_days=ch.NOT_IMPOSED,
            max_leverage=ch.NOT_IMPOSED,
            max_single_day_profit_share=ch.NOT_IMPOSED,
            news_trading_allowed=ch.NOT_IMPOSED,
            weekend_holding_allowed=ch.NOT_IMPOSED,
            max_concurrent_positions=ch.NOT_IMPOSED,
        )


class TestRuleAbsence:
    def test_a_rulebook_nobody_entered_blocks(self):
        """The bug this separation exists for.

        `ChallengeRules()` used to approve: every field was `None`, `None` read
        as "the provider imposes no such rule", and the module ended up
        asserting that an unnamed provider caps nothing on the strength of
        fields nobody had filled in. No breach, no gate, nothing in
        `unverified` — a challenge account cleared to trade against rules the
        system had never seen.
        """
        verdict = ch.check(ch.ChallengeRules(), state(), 1.0)

        assert verdict.verdict == "block"
        assert verdict.allowed is False
        assert verdict.daily.imposed is True
        assert verdict.daily.available is False
        assert any("never entered" in u for u in verdict.unverified)

    def test_an_empty_rulebook_imposes_nothing(self):
        """Still true, but it has to be said now rather than defaulted into."""
        verdict = ch.check(uncapped(), state(), 1.0)

        assert verdict.verdict == "approve"
        assert verdict.breaches == []
        assert verdict.daily.imposed is False
        # No drawdown rule means no cap from this module — distinct from a cap
        # of zero, which would block.
        assert verdict.max_additional_risk_r is None

    def test_unknown_and_not_imposed_reach_opposite_verdicts(self):
        """One value carrying both meanings is the whole defect."""
        unknown = ch.check(ch.ChallengeRules(), state(), 1.0)
        stated = ch.check(uncapped(), state(), 1.0)

        assert unknown.allowed is False
        assert stated.allowed is True

    def test_the_marker_is_falsey_so_a_truthiness_check_reads_as_no_cap(self):
        """`if rules.max_leverage:` is the mistake waiting to be made; it must
        fail toward "there is no cap here" rather than enforce a phantom one."""
        assert not ch.NOT_IMPOSED

    def test_a_zero_daily_rule_is_not_an_absent_one(self):
        """The distinction the dataclass exists to preserve."""
        absent = ch.check(rules(max_daily_drawdown_pct=ch.NOT_IMPOSED), state(), 1.0)
        zero = ch.check(rules(max_daily_drawdown_pct=0.0), state(), 1.0)

        assert absent.daily.imposed is False
        assert zero.daily.imposed is True
        assert zero.daily.allowance == pytest.approx(0.0)
        assert zero.verdict == "block"

    def test_a_zero_daily_rule_is_not_an_unknown_one_either(self):
        unknown = ch.check(rules(max_daily_drawdown_pct=None), state(), 1.0)
        zero = ch.check(rules(max_daily_drawdown_pct=0.0), state(), 1.0)

        assert unknown.daily.available is False
        assert zero.daily.available is True
        assert zero.daily.allowance == pytest.approx(0.0)

    def test_a_zero_rule_still_permits_giving_back_the_day_s_profit(self):
        """Zero daily *loss* is measured from the day's open, not from flat."""
        verdict = ch.check(
            rules(max_daily_drawdown_pct=0.0),
            state(current_equity=101_000.0, daily_starting_equity=100_000.0),
            1.0,
        )

        assert verdict.daily.amount == pytest.approx(1_000.0)
        assert verdict.daily.breached is False

    def test_zero_concurrent_positions_blocks_while_absent_does_not(self):
        blocked = ch.check(rules(max_concurrent_positions=0), state(), 1.0)
        open_ended = ch.check(rules(max_concurrent_positions=None), state(), 1.0)

        assert blocked.allowed is False
        assert open_ended.allowed is True
        assert blocked.breaches == []  # being at a cap violates nothing


# ============================================================ daily drawdown
class TestDailyDrawdown:
    def test_measured_from_the_day_s_opening_equity_not_the_start(self):
        """Yesterday's losses must not eat today's allowance."""
        verdict = ch.check(
            rules(),
            state(current_equity=94_000.0, daily_starting_equity=95_000.0, peak_equity=100_000.0),
            None,
        )

        # 5% of 100k is 5,000 off the day's open at 95,000 — floor 90,000.
        assert verdict.daily.floor == pytest.approx(90_000.0)
        assert verdict.daily.breached is False
        assert verdict.daily.amount == pytest.approx(4_000.0)

    def test_floating_loss_counts_immediately_on_equity(self):
        """The distinction that ends accounts: equity moves, balance waits.

        Balance says the account is untouched because nothing has closed. The
        provider's server is watching equity and has already failed it.
        """
        verdict = ch.check(
            rules(),
            state(current_equity=94_500.0, current_balance=100_000.0),
            None,
        )

        assert verdict.daily.breached is True
        assert verdict.status == "failed"
        assert verdict.allowed is False

    def test_balance_basis_does_not_silently_fall_back_to_equity(self):
        """A missing balance is a hole in the measurement, not a licence."""
        verdict = ch.check(
            rules(drawdown_basis=ch.DrawdownBasis.BALANCE),
            state(current_balance=None, current_equity=100_000.0),
            1.0,
        )

        assert verdict.daily.available is False
        assert verdict.verdict == "block"
        assert verdict.breaches == []  # unmeasured is not violated
        assert any("balance" in u for u in verdict.unverified)

    def test_exactly_on_the_floor_is_not_yet_a_breach_but_has_no_room(self):
        verdict = ch.check(rules(), state(current_equity=95_000.0), 1.0)

        assert verdict.daily.breached is False
        assert verdict.daily.amount == pytest.approx(0.0)
        assert verdict.verdict == "block"

    def test_a_spent_allowance_warns_before_it_binds(self):
        verdict = ch.check(rules(), state(current_equity=95_400.0), None)

        assert verdict.daily.consumed == pytest.approx(0.92)
        assert any("daily drawdown allowance" in w for w in verdict.warnings)


# ============================================================ total drawdown
class TestTotalDrawdown:
    def test_static_anchor_measures_from_the_starting_balance(self):
        verdict = ch.check(
            rules(total_drawdown_trailing=False),
            state(current_equity=105_000.0, peak_equity=108_000.0),
            None,
        )

        assert verdict.total.floor == pytest.approx(90_000.0)

    def test_trailing_anchor_measures_from_the_peak(self):
        verdict = ch.check(
            rules(total_drawdown_trailing=True),
            state(current_equity=105_000.0, peak_equity=108_000.0),
            None,
        )

        assert verdict.total.floor == pytest.approx(98_000.0)

    def test_an_unspecified_anchor_takes_the_stricter_one_and_says_so(self):
        """Guessing the permissive anchor is guessing away the account."""
        verdict = ch.check(
            rules(total_drawdown_trailing=None),
            state(current_equity=105_000.0, peak_equity=108_000.0),
            None,
        )

        assert verdict.total.floor == pytest.approx(98_000.0)
        assert any("anchor unspecified" in u for u in verdict.unverified)

    def test_a_stale_peak_does_not_lower_the_trailing_floor(self):
        """A peak below current equity is a stale assembler, not more rope."""
        verdict = ch.check(
            rules(total_drawdown_trailing=True),
            state(current_equity=106_000.0, peak_equity=100_000.0),
            None,
        )

        assert verdict.total.floor == pytest.approx(96_000.0)
        assert any("the supplied peak" in u for u in verdict.unverified)

    def test_a_breached_total_drawdown_fails_the_challenge(self):
        verdict = ch.check(rules(), state(current_equity=89_000.0, daily_starting_equity=89_500.0))

        assert verdict.status == "failed"
        assert verdict.failed is True
        assert any("total drawdown" in b for b in verdict.breaches)


# ================================================================ projection
class TestLossProjection:
    def test_a_trade_whose_full_loss_ends_the_challenge_is_refused_first(self):
        """The point of the module: refused before it is taken, not after."""
        verdict = ch.check(
            rules(),
            state(current_equity=95_600.0, currency_per_r=1_000.0),
            1.0,
        )

        assert verdict.projection.available is True
        assert verdict.projection.breaches_daily is True
        assert verdict.projection.survivable is False
        assert verdict.verdict != "approve"
        assert any("full" in w for w in verdict.warnings)

    def test_a_smaller_size_is_offered_rather_than_a_flat_refusal(self):
        verdict = ch.check(
            rules(),
            state(current_equity=95_600.0, currency_per_r=1_000.0),
            1.0,
        )

        assert verdict.verdict == "reduce"
        assert verdict.max_additional_risk_r == pytest.approx(0.54)  # 600 * 0.9 / 1000

    def test_the_offered_size_survives_its_own_projection(self):
        """Whatever this module clears, it must clear against itself."""
        first = ch.check(rules(), state(current_equity=95_600.0, currency_per_r=1_000.0), 1.0)
        again = ch.check(
            rules(),
            state(current_equity=95_600.0, currency_per_r=1_000.0),
            first.max_additional_risk_r,
        )

        assert again.verdict == "approve"
        assert again.projection.survivable is True

    def test_an_unpriced_r_blocks_rather_than_assuming_a_size(self):
        """Without the currency value of one R there is no projection at all."""
        verdict = ch.check(rules(), state(currency_per_r=None), 1.0)

        assert verdict.projection.available is False
        assert verdict.projection.survivable is None
        assert verdict.verdict == "block"
        assert verdict.max_additional_risk_r == 0.0

    def test_no_proposed_trade_still_answers_the_standing_question(self):
        verdict = ch.check(rules(), state(), None)

        assert verdict.projection.available is False
        assert verdict.projection.reason == "no trade proposed"
        assert verdict.allowed is True
        assert verdict.max_additional_risk_r == pytest.approx(9.0)  # 5,000 * 0.9 / 500

    def test_the_binding_limit_is_the_tighter_of_the_two(self):
        """A day with room left is no help once the total limit is close."""
        account = state(
            current_equity=93_000.0,
            daily_starting_equity=94_000.0,
            peak_equity=100_000.0,
        )

        verdict = ch.check(rules(), account, 8.0)

        assert verdict.daily.amount == pytest.approx(4_000.0)
        assert verdict.total.amount == pytest.approx(3_000.0)
        # 3,000 of headroom, buffered, at 500 per R.
        assert verdict.max_additional_risk_r == pytest.approx(5.4)
        assert verdict.projection.breaches_total is True
        assert verdict.projection.breaches_daily is False
        assert verdict.verdict == "reduce"

    def test_a_non_positive_proposal_is_refused(self):
        verdict = ch.check(rules(), state(), 0.0)

        assert verdict.verdict == "block"
        assert verdict.allowed is False


# =============================================================== consistency
class TestConsistency:
    def test_too_little_history_is_reported_not_passed(self):
        """The rule this module must never satisfy by default."""
        report = ch.evaluate_consistency(0.40, {TODAY: 4_000.0})

        assert report.available is False
        assert "insufficient days" in report.reason
        assert report.within_limit is None

    def test_a_single_dominant_day_is_caught(self):
        report = ch.evaluate_consistency(
            0.40,
            {
                date(2026, 3, 9): 500.0,
                date(2026, 3, 10): 400.0,
                date(2026, 3, 11): 9_100.0,
            },
        )

        assert report.available is True
        assert report.best_day == date(2026, 3, 11)
        assert report.best_day_share == pytest.approx(0.91)
        assert report.within_limit is False

    def test_evenly_spread_profit_passes(self):
        report = ch.evaluate_consistency(
            0.40,
            {
                date(2026, 3, 9): 1_000.0,
                date(2026, 3, 10): 1_200.0,
                date(2026, 3, 11): 900.0,
            },
        )

        assert report.within_limit is True

    def test_losing_days_net_against_the_total(self):
        report = ch.evaluate_consistency(
            0.40,
            {
                date(2026, 3, 9): -800.0,
                date(2026, 3, 10): 1_000.0,
                date(2026, 3, 11): 1_000.0,
            },
        )

        assert report.total_profit == pytest.approx(1_200.0)
        assert report.best_day_share == pytest.approx(1_000.0 / 1_200.0)
        assert report.within_limit is False

    def test_no_profit_yet_is_unjudgeable_not_compliant(self):
        report = ch.evaluate_consistency(
            0.40,
            {
                date(2026, 3, 9): -500.0,
                date(2026, 3, 10): -200.0,
                date(2026, 3, 11): 100.0,
            },
        )

        assert report.available is False
        assert "apportion" in report.reason
        assert report.within_limit is None

    def test_an_absent_rule_is_not_a_failed_one(self):
        report = ch.evaluate_consistency(ch.NOT_IMPOSED, {TODAY: 1_000.0})

        assert report.available is False
        assert report.within_limit is None
        assert "no consistency rule" in report.reason

    def test_an_unentered_rule_says_so_rather_than_claiming_the_provider_has_none(self):
        report = ch.evaluate_consistency(None, {TODAY: 1_000.0})

        assert report.available is False
        assert report.within_limit is None
        assert "never entered" in report.reason

    def test_a_concentrated_history_warns_on_the_verdict(self):
        verdict = ch.check(
            rules(),
            state(
                daily_profits={
                    date(2026, 3, 9): 200.0,
                    date(2026, 3, 10): 300.0,
                    date(2026, 3, 11): 9_500.0,
                }
            ),
        )

        assert any("consistency" in w for w in verdict.warnings)
        assert verdict.breaches == []  # curable by trading more days


# ==================================================================== status
class TestStatus:
    def test_a_met_target_with_everything_else_done_passes(self):
        verdict = ch.check(
            rules(),
            state(
                current_balance=110_000.0,
                current_equity=110_000.0,
                peak_equity=110_000.0,
                daily_starting_equity=110_000.0,
                days_traded=6,
                daily_profits={
                    date(2026, 3, 9): 3_500.0,
                    date(2026, 3, 10): 3_000.0,
                    date(2026, 3, 11): 3_500.0,
                },
            ),
        )

        assert verdict.status == "passed"

    def test_a_target_reached_on_floating_profit_does_not_pass(self):
        """No provider pays out on a position that has not closed."""
        verdict = ch.check(
            rules(),
            state(current_equity=112_000.0, current_balance=None, days_traded=6),
            None,
        )

        assert verdict.status != "passed"
        assert any("closed profit" in u for u in verdict.unverified)

    def test_a_met_target_without_the_minimum_days_is_still_in_progress(self):
        verdict = ch.check(
            rules(),
            state(
                current_balance=110_000.0,
                current_equity=110_000.0,
                days_traded=2,
                daily_profits={
                    date(2026, 3, 10): 5_000.0,
                    date(2026, 3, 11): 5_000.0,
                },
            ),
        )

        assert verdict.status == "in_progress"
        assert any("more trading day" in w for w in verdict.warnings)

    def test_an_unjudgeable_consistency_rule_withholds_the_pass(self):
        """Passing on a rule nobody checked is the fabrication this forbids."""
        verdict = ch.check(
            rules(),
            state(
                current_balance=110_000.0,
                current_equity=110_000.0,
                days_traded=6,
                daily_profits={},
            ),
        )

        assert verdict.status == "in_progress"
        assert any("consistency" in u for u in verdict.unverified)

    def test_exceeding_the_maximum_days_fails(self):
        verdict = ch.check(rules(max_trading_days=30), state(days_traded=31))

        assert verdict.status == "failed"
        assert verdict.allowed is False

    def test_the_last_permitted_day_warns(self):
        verdict = ch.check(rules(max_trading_days=30), state(days_traded=30))

        assert verdict.status == "in_progress"
        assert any("last permitted trading day" in w for w in verdict.warnings)


# ===================================================== gates on a new trade
class TestGates:
    def test_the_position_cap_blocks_without_accusing(self):
        verdict = ch.check(rules(max_concurrent_positions=3), state(open_positions=3), 1.0)

        assert verdict.allowed is False
        assert verdict.verdict == "block"
        assert verdict.status == "in_progress"
        assert verdict.breaches == []

    def test_more_positions_than_permitted_is_a_breach(self):
        verdict = ch.check(rules(max_concurrent_positions=3), state(open_positions=4), 1.0)

        assert verdict.status == "failed"

    def test_an_unknown_news_window_blocks_when_the_rule_exists(self):
        """Not knowing whether news is running is not evidence that it is not."""
        verdict = ch.check(
            rules(news_trading_allowed=False), state(in_news_window=None), 1.0
        )

        assert verdict.allowed is False
        assert any("news-window" in u for u in verdict.unverified)

    def test_an_unstated_news_rule_does_not_gate_but_is_never_silent(self):
        """Rewritten: this asserted only `allowed is True`, which pinned
        silence in the rulebook as permission from the provider. The module
        cannot tell "this provider imposes nothing" from "nobody filled this
        in", so it does not gate — but it must say which check it skipped."""
        verdict = ch.check(rules(news_trading_allowed=None), state(in_news_window=None), 1.0)

        assert verdict.allowed is True
        assert any("does not say whether" in u and "news" in u for u in verdict.unverified)

    def test_being_inside_a_news_window_blocks_new_risk_only(self):
        verdict = ch.check(rules(), state(in_news_window=True, open_positions=1), 1.0)

        assert verdict.allowed is False
        assert verdict.breaches == []

    def test_an_unknown_weekend_proximity_blocks_when_holding_is_forbidden(self):
        verdict = ch.check(rules(weekend_holding_allowed=False), state(weekend_ahead=None), 1.0)

        assert verdict.allowed is False
        assert any("weekend" in u for u in verdict.unverified)

    def test_open_positions_before_a_forbidden_weekend_are_flagged(self):
        verdict = ch.check(rules(), state(weekend_ahead=True, open_positions=2), 1.0)

        assert verdict.allowed is False
        assert any("closed before the weekend" in w for w in verdict.warnings)

    def test_unmeasured_leverage_blocks_when_a_cap_exists(self):
        verdict = ch.check(rules(max_leverage=30.0), state(current_leverage=None), 1.0)

        assert verdict.allowed is False
        assert verdict.breaches == []
        assert any("leverage" in u for u in verdict.unverified)

    def test_leverage_above_the_cap_is_a_breach(self):
        verdict = ch.check(rules(max_leverage=30.0), state(current_leverage=31.0), 1.0)

        assert verdict.status == "failed"

    def test_leverage_at_the_cap_blocks_new_risk_without_failing(self):
        verdict = ch.check(rules(max_leverage=30.0), state(current_leverage=30.0), 1.0)

        assert verdict.status == "in_progress"
        assert verdict.allowed is False


# ================================================================= integrity
class TestIntegrity:
    def test_a_history_from_the_future_is_refused_outright(self):
        """A state that cannot be true must not be measured as if it were."""
        verdict = ch.check(
            rules(), state(daily_profits={date(2026, 3, 20): 1_000.0}), 1.0
        )

        assert verdict.verdict == "block"
        assert any("not internally consistent" in u for u in verdict.unverified)

    def test_a_non_positive_starting_balance_is_refused(self):
        verdict = ch.check(rules(), state(starting_balance=0.0), 1.0)

        assert verdict.verdict == "block"
        assert verdict.daily.available is False

    def test_no_unknown_makes_the_engine_more_permissive(self):
        """The adversarial property: every hole must cost, never pay."""
        known = ch.check(rules(), state(), 1.0)

        for hole in (
            dict(current_leverage=None),
            dict(in_news_window=None),
            dict(weekend_ahead=None),
            dict(currency_per_r=None),
        ):
            unknown = ch.check(rules(), state(**hole), 1.0)

            assert (unknown.max_additional_risk_r or 0.0) <= (
                known.max_additional_risk_r or 0.0
            )
            assert unknown.allowed <= known.allowed

    def test_a_failed_challenge_allows_nothing(self):
        verdict = ch.check(rules(), state(current_equity=80_000.0), 0.1)

        assert verdict.status == "failed"
        assert verdict.allowed is False
        assert verdict.max_additional_risk_r == 0.0

    def test_a_clean_account_approves_a_normal_trade(self):
        verdict = ch.check(rules(), state(), 1.0)

        assert verdict.verdict == "approve"
        assert verdict.allowed is True
        assert verdict.status == "in_progress"

    def test_no_response_claims_execution_authority(self):
        payload = ch.check(rules(), state(), 1.0).as_dict()

        assert payload["authorises_execution"] is False
        assert "before execution" in payload["note"]

    def test_the_payload_keeps_absent_and_measured_apart(self):
        payload = ch.check(
            rules(max_daily_drawdown_pct=ch.NOT_IMPOSED), state(), 1.0
        ).as_dict()

        assert payload["headroom"]["daily"]["imposed"] is False
        assert payload["headroom"]["total"]["imposed"] is True
        assert payload["headroom"]["total"]["amount"] == pytest.approx(10_000.0)

    def test_the_payload_keeps_unknown_apart_from_both(self):
        """Three states, three renderings. A sizer downstream reads all three
        differently, and two of them used to arrive identical."""
        payload = ch.check(rules(max_daily_drawdown_pct=None), state(), 1.0).as_dict()
        daily = payload["headroom"]["daily"]

        assert daily["imposed"] is True
        assert daily["available"] is False
        # No `amount` key at all, rather than a null one. An unmeasurable
        # headroom publishes the reason and nothing numeric.
        assert "amount" not in daily
        assert "never entered" in daily["reason"]


# ===================================================== adversarial review fixes
class TestTheCapCannotBeMistakenForNoCap:
    """`None` used to mean both "this provider caps nothing" and "we could not
    work out the cap", and the second came back with verdict=approve."""

    def test_an_unpriced_r_blocks_instead_of_reporting_no_cap(self):
        verdict = ch.check(rules(), state(currency_per_r=None), None)

        assert verdict.risk_cap_measurable is False
        assert verdict.allowed is False
        assert verdict.verdict == "block"
        assert verdict.max_additional_risk_r == 0.0

    def test_a_rulebook_with_no_drawdown_rule_really_has_no_cap(self):
        verdict = ch.check(
            dataclasses.replace(uncapped(), profit_target_pct=0.10), state(), None
        )

        assert verdict.risk_cap_measurable is True
        assert verdict.max_additional_risk_r is None
        assert verdict.allowed is True

    def test_the_two_are_distinguishable_in_the_payload(self):
        """The whole point: a downstream sizer reads these differently."""
        unmeasurable = ch.check(rules(), state(currency_per_r=None), None).as_dict()
        no_cap = ch.check(uncapped(), state(), None).as_dict()
        unknown = ch.check(ch.ChallengeRules(), state(), None).as_dict()

        assert unmeasurable["max_additional_risk_r"] != no_cap["max_additional_risk_r"]
        assert unmeasurable["risk_cap_measurable"] is False
        assert no_cap["risk_cap_measurable"] is True
        # The third state, which the payload could not previously express: not
        # a cap, not the absence of one, but a rulebook nobody supplied.
        assert unknown["risk_cap_measurable"] is False
        assert unknown["max_additional_risk_r"] == 0.0


class TestBalanceBasisIsReadOnItsOwnRuler:
    def test_the_daily_floor_uses_the_opening_balance_not_the_opening_equity(self):
        """The reproduction: a day that opened with a 3,000 floating loss got a
        floor 3,000 lower than the provider's, and 60% more risk with it."""
        verdict = ch.check(
            rules(drawdown_basis=ch.DrawdownBasis.BALANCE),
            state(
                current_balance=100_000.0,
                daily_starting_balance=100_000.0,
                daily_starting_equity=97_000.0,
                current_equity=97_000.0,
            ),
            None,
        )

        assert verdict.daily.floor == pytest.approx(95_000.0)
        assert verdict.daily.amount == pytest.approx(5_000.0)

    def test_a_balance_account_without_an_opening_balance_is_refused(self):
        """Substituting the opening equity is the error this replaces."""
        verdict = ch.check(
            rules(drawdown_basis=ch.DrawdownBasis.BALANCE),
            state(current_balance=100_000.0, daily_starting_balance=None),
            None,
        )

        assert verdict.daily.available is False
        assert "different ruler" in verdict.daily.reason
        assert verdict.allowed is False

    def test_floating_profit_does_not_declare_a_balance_account_dead(self):
        """`max(peak, current_equity)` mixed the rulers the other way and
        reported a flat account as failed on an 11k floating profit."""
        verdict = ch.check(
            rules(total_drawdown_trailing=True, drawdown_basis=ch.DrawdownBasis.BALANCE),
            state(
                peak_equity=100_000.0,
                current_balance=100_000.0,
                daily_starting_balance=100_000.0,
                current_equity=111_000.0,
            ),
            None,
        )

        assert verdict.status != "failed"
        assert verdict.total.floor == pytest.approx(90_000.0)


class TestSilenceInTheRulebookIsVisible:
    def test_an_unstated_news_rule_is_reported_as_unchecked(self):
        """Rewritten: the previous version pinned silence as permission."""
        verdict = ch.check(
            rules(news_trading_allowed=None), state(in_news_window=True), None
        )

        assert any("news" in u for u in verdict.unverified)

    def test_an_unstated_weekend_rule_is_reported_as_unchecked(self):
        verdict = ch.check(
            rules(weekend_holding_allowed=None), state(weekend_ahead=True), None
        )

        assert any("weekend" in u for u in verdict.unverified)

    def test_an_unstated_leverage_cap_is_reported_as_unchecked(self):
        verdict = ch.check(rules(max_leverage=None), state(), None)

        assert any("leverage" in u for u in verdict.unverified)

    def test_an_unstated_allowance_basis_takes_the_smaller_figure(self):
        drawn_down = state(current_equity=90_000.0, current_balance=90_000.0,
                           daily_starting_equity=90_000.0)

        stated = ch.check(rules(), drawn_down, None)
        unstated = ch.check(rules(allowance_basis=None), drawn_down, None)

        assert unstated.daily.allowance == pytest.approx(4_500.0)
        assert stated.daily.allowance == pytest.approx(5_000.0)
        assert any("allowance basis unspecified" in u for u in unstated.unverified)


class TestAnUndefinedRatioIsNotAMeasurement:
    def test_a_zero_allowance_reports_no_share_spent(self):
        """0.0 and 1.0 were both published for a quantity that is undefined."""
        verdict = ch.check(
            rules(max_daily_drawdown_pct=0.0), state(current_equity=90_000.0), None
        )

        assert verdict.daily.consumed is None
        assert verdict.daily.as_dict()["consumed"] is None

class TestTheMarkerDidNotBreakTheRulesItTouched:
    """Regressions the three-state split introduced, found by driving the
    deployed endpoint rather than by reading the diff again.

    Adding NOT_IMPOSED changed what `is not None` means for every rule field,
    and two checks were left reading the old meaning. Both were silent: the
    suite stayed green and the endpoint kept answering, just wrongly.
    """

    def test_a_met_target_passes_when_no_consistency_rule_is_imposed(self):
        """`is not None` saw NOT_IMPOSED as an imposed rule, so an account that
        had made its target sat at in_progress waiting on a rule its provider
        does not have."""
        verdict = ch.check(
            dataclasses.replace(uncapped(), profit_target_pct=0.10),
            state(current_equity=111_000.0, current_balance=111_000.0),
            None,
        )

        assert verdict.status == "passed"

    def test_a_met_target_still_waits_on_a_real_consistency_rule(self):
        """The other half: an imposed rule with nothing to judge it on must
        still hold the pass back."""
        verdict = ch.check(
            dataclasses.replace(
                uncapped(), profit_target_pct=0.10, max_single_day_profit_share=0.4
            ),
            state(current_equity=111_000.0, current_balance=111_000.0),
            None,
        )

        assert verdict.status == "in_progress"
        assert any("consistency" in w for w in verdict.warnings)

    def test_an_unpriced_r_is_the_reason_a_healthy_account_blocks(self):
        """Driving the live endpoint, every state blocked - including a fresh
        untouched account. The cause was not the rulebook: one R had no value
        in account currency, so no allowance could become a risk figure. The
        block is right; an endpoint with no way to supply the number is not."""
        healthy = state(currency_per_r=None)

        assert ch.check(rules(), healthy, 1.0).allowed is False
        assert ch.check(rules(), state(currency_per_r=200.0), 1.0).allowed is True
