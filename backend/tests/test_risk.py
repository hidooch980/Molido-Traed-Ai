"""Portfolio and risk-brain tests (phases 22-23).

These two modules are the only thing standing between a confident model and an
account. The tests are therefore mostly adversarial: they try to talk the risk
brain into a larger position and check that nothing works.
"""

from __future__ import annotations

import dataclasses

import pytest

from app.brain import portfolio as pf
from app.brain import risk
from app.core.enums import RiskVerdict


def healthy_account(**overrides) -> risk.AccountState:
    defaults = dict(
        equity=10_000.0,
        balance=10_000.0,
        peak_equity=10_000.0,
        daily_pnl_r=0.0,
        open_positions=1,
        used_margin=1_000.0,
        free_margin=9_000.0,
    )
    defaults.update(overrides)
    return risk.AccountState(**defaults)


def good_health(**overrides) -> risk.DataHealth:
    defaults = dict(
        data_age_bars=0.5,
        training_eligible=True,
        calibrated=True,
        correlation_unknown=[],
        safe_mode=False,
    )
    defaults.update(overrides)
    return risk.DataHealth(**defaults)


# ============================================================ portfolio brain
class TestCurrencyNetting:
    def test_two_pairs_sharing_a_leg_accumulate(self):
        """EUR/USD long and EUR/JPY long are one larger long-EUR position."""
        positions = [
            pf.Position("EURUSD", "buy", 1.0, "EUR", "USD"),
            pf.Position("EURJPY", "buy", 1.0, "EUR", "JPY"),
        ]

        exposure = pf.currency_exposure(positions)

        assert exposure["EUR"] == pytest.approx(2.0)
        assert exposure["USD"] == pytest.approx(-1.0)

    def test_opposing_pairs_net_off(self):
        positions = [
            pf.Position("EURUSD", "buy", 1.0, "EUR", "USD"),
            pf.Position("EURUSD", "sell", 1.0, "EUR", "USD"),
        ]

        assert pf.currency_exposure(positions)["EUR"] == pytest.approx(0.0)

    def test_currency_ceiling_caps_a_third_correlated_trade(self):
        positions = [
            pf.Position("EURUSD", "buy", 1.5, "EUR", "USD"),
            pf.Position("EURGBP", "buy", 1.5, "EUR", "GBP"),
        ]

        verdict = pf.evaluate(
            symbol="EURJPY", direction="buy", proposed_risk_r=1.0,
            positions=positions, base_currency="EUR", quote_currency="JPY",
        )

        assert verdict.verdict in ("reduce", "block")
        assert "currency:EUR" in verdict.exposures["limiting_constraint"]


class TestCorrelation:
    def test_measured_correlation_forms_a_cluster(self):
        positions = [pf.Position("GBPUSD", "buy", 1.0, "GBP", "USD")]

        clustered, unknown = pf.correlated_cluster(
            "EURUSD", positions, {"GBPUSD": 0.85}
        )

        assert clustered == ["GBPUSD"]
        assert unknown == []

    def test_unmeasured_correlation_is_flagged_not_assumed_zero(self):
        """The failure this prevents: a book that looks diversified and is not."""
        positions = [pf.Position("GBPUSD", "buy", 1.0, "GBP", "USD")]

        clustered, unknown = pf.correlated_cluster("EURUSD", positions, {})

        assert clustered == []
        assert unknown == ["GBPUSD"]

    def test_unknown_correlation_produces_a_warning(self):
        verdict = pf.evaluate(
            symbol="EURUSD", direction="buy", proposed_risk_r=1.0,
            positions=[pf.Position("GBPUSD", "buy", 1.0, "GBP", "USD")],
            base_currency="EUR", quote_currency="USD", correlations={},
        )

        assert any("not as uncorrelated" in w for w in verdict.warnings)

    def test_cluster_risk_limits_additional_exposure(self):
        positions = [
            pf.Position("GBPUSD", "buy", 1.5, "GBP", "USD"),
            pf.Position("AUDUSD", "buy", 1.5, "AUD", "USD"),
        ]

        verdict = pf.evaluate(
            symbol="NZDUSD", direction="buy", proposed_risk_r=1.0,
            positions=positions, base_currency="NZD", quote_currency="USD",
            correlations={"GBPUSD": 0.8, "AUDUSD": 0.9},
        )

        assert verdict.verdict in ("reduce", "block")


class TestPortfolioHeadroom:
    def test_empty_book_approves_in_full(self):
        verdict = pf.evaluate(
            symbol="EURUSD", direction="buy", proposed_risk_r=1.0,
            positions=[], base_currency="EUR", quote_currency="USD",
        )

        assert verdict.verdict == "approve"
        assert verdict.max_additional_risk_r == pytest.approx(1.0)

    def test_full_book_blocks(self):
        positions = [
            pf.Position(f"SYM{i}", "buy", 1.0, f"C{i}", "USD") for i in range(6)
        ]

        verdict = pf.evaluate(
            symbol="EURUSD", direction="buy", proposed_risk_r=1.0,
            positions=positions, base_currency="EUR", quote_currency="USD",
        )

        assert verdict.verdict == "block"
        assert verdict.max_additional_risk_r == 0.0

    def test_headroom_is_returned_not_just_a_refusal(self):
        """'Reduce to 0.5 R' is more useful downstream than 'no'."""
        positions = [pf.Position("EURUSD", "buy", 1.5, "EUR", "USD")]

        verdict = pf.evaluate(
            symbol="EURUSD", direction="buy", proposed_risk_r=1.0,
            positions=positions, base_currency="EUR", quote_currency="USD",
        )

        assert verdict.verdict == "reduce"
        assert 0 < verdict.max_additional_risk_r < 1.0


# ================================================================ risk brain
class TestHardLimits:
    def test_safe_mode_blocks(self):
        decision = risk.authorise(
            requested_risk_r=0.5, account=healthy_account(),
            health=good_health(safe_mode=True),
        )

        assert decision.verdict is RiskVerdict.BLOCK
        assert decision.permitted_risk_r == 0.0

    def test_drawdown_ceiling_blocks(self):
        decision = risk.authorise(
            requested_risk_r=0.5,
            account=healthy_account(equity=8_900.0, peak_equity=10_000.0),
            health=good_health(),
        )

        assert decision.verdict is RiskVerdict.BLOCK
        assert any("drawdown" in b for b in decision.hard_breaches)

    def test_daily_loss_limit_blocks(self):
        decision = risk.authorise(
            requested_risk_r=0.5,
            account=healthy_account(daily_pnl_r=-3.0), health=good_health(),
        )

        assert decision.verdict is RiskVerdict.BLOCK

    def test_stale_data_blocks(self):
        """The spec is explicit: stale data means no new trade."""
        decision = risk.authorise(
            requested_risk_r=0.5, account=healthy_account(),
            health=good_health(data_age_bars=10.0),
        )

        assert decision.verdict is RiskVerdict.BLOCK
        assert any("bars old" in b for b in decision.hard_breaches)

    def test_unknown_data_age_blocks_like_stale_data(self):
        """Not knowing the feed's age is not evidence that it is fresh."""
        decision = risk.authorise(
            requested_risk_r=0.5, account=healthy_account(),
            health=good_health(data_age_bars=None),
        )

        assert decision.verdict is RiskVerdict.BLOCK
        assert any("freshness unknown" in b for b in decision.hard_breaches)

    def test_oversized_request_blocks_rather_than_silently_capping(self):
        """A request beyond the hard ceiling is a bug upstream, not a rounding."""
        decision = risk.authorise(
            requested_risk_r=5.0, account=healthy_account(), health=good_health()
        )

        assert decision.verdict is RiskVerdict.BLOCK

    def test_margin_ceiling_blocks(self):
        decision = risk.authorise(
            requested_risk_r=0.5,
            account=healthy_account(used_margin=6_000.0, free_margin=4_000.0),
            health=good_health(),
        )

        assert decision.verdict is RiskVerdict.BLOCK

    def test_hard_limits_are_frozen(self):
        """Limits that can be edited in the moment they bind are not limits."""
        limits = risk.HardLimits()

        # FrozenInstanceError specifically: a blanket Exception would also pass
        # if the attribute name were misspelled, which is the opposite of proof.
        with pytest.raises(dataclasses.FrozenInstanceError):
            limits.max_total_drawdown_pct = 0.99  # type: ignore[misc]


class TestUncertaintyReducesRisk:
    def test_uncalibrated_halves_risk(self):
        decision = risk.authorise(
            requested_risk_r=1.0, account=healthy_account(),
            health=good_health(calibrated=False),
        )

        assert decision.verdict is RiskVerdict.REDUCE
        assert decision.permitted_risk_r == pytest.approx(0.5)

    def test_failed_quality_gate_halves_risk(self):
        decision = risk.authorise(
            requested_risk_r=1.0, account=healthy_account(),
            health=good_health(training_eligible=False),
        )

        assert decision.permitted_risk_r == pytest.approx(0.5)

    def test_uncertainties_compound(self):
        decision = risk.authorise(
            requested_risk_r=1.0, account=healthy_account(),
            health=good_health(calibrated=False, training_eligible=False),
        )

        assert decision.permitted_risk_r == pytest.approx(0.25)

    def test_no_input_can_exceed_the_request(self):
        """The adversarial property: nothing makes this module more permissive."""
        best_case = risk.authorise(
            requested_risk_r=0.4, account=healthy_account(), health=good_health()
        )

        assert best_case.permitted_risk_r <= 0.4

    def test_portfolio_headroom_caps_the_verdict(self):
        decision = risk.authorise(
            requested_risk_r=1.0, account=healthy_account(),
            health=good_health(), portfolio_headroom_r=0.3,
        )

        assert decision.permitted_risk_r == pytest.approx(0.3)
        assert decision.verdict is RiskVerdict.REDUCE

    def test_reductions_can_reach_a_block(self):
        decision = risk.authorise(
            requested_risk_r=1.0, account=healthy_account(),
            health=good_health(), portfolio_headroom_r=0.0,
        )

        assert decision.verdict is RiskVerdict.BLOCK
        assert decision.approves is False


class TestIndependence:
    def test_risk_brain_takes_no_conviction_input(self):
        """Independence is structural: there is no parameter to pass one.

        The spec requires the risk engine to be independent of the predictive
        AI. Enforcing that by convention invites a well-meaning `confidence=`
        argument later, so the signature simply has nowhere to put one.
        """
        import inspect

        params = set(inspect.signature(risk.authorise).parameters)

        for forbidden in ("confidence", "conviction", "score", "signal", "probability"):
            assert forbidden not in params

    def test_a_clean_setup_approves(self):
        decision = risk.authorise(
            requested_risk_r=1.0, account=healthy_account(), health=good_health()
        )

        assert decision.verdict is RiskVerdict.APPROVE
        assert decision.permitted_risk_r == pytest.approx(1.0)

    def test_no_response_claims_execution_authority(self):
        payload = risk.authorise(
            requested_risk_r=1.0, account=healthy_account(), health=good_health()
        ).as_dict()

        assert payload["authorises_execution"] is False
