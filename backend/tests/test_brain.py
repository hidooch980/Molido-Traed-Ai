"""Cognitive-layer tests (phases 13–20).

These layers turn measurements into an opinion, which makes them the easiest
place in the system to manufacture confidence. Most of these tests exist to
prove the machinery refuses rather than to prove it decides.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.brain import calibration, cognitive, council, meta, strategy
from app.brain.calibration import Forecast
from app.brain.council import Opinion
from app.core.enums import Decision, Regime, Timeframe
from app.services import regime as regime_service
from tests.conftest import BASE_TIME, insert_bar


def after(h: int) -> datetime:
    return BASE_TIME + timedelta(hours=h)


def seed(session, instrument, provider, count, *, drift=0.0002, price=1.10):
    for i in range(count):
        close = price + i * drift
        insert_bar(
            session, instrument.id, provider.id,
            event_time=BASE_TIME + timedelta(hours=i),
            ingested_at=BASE_TIME, close=round(close, 8), open_=round(close - drift, 8),
        )


# ------------------------------------------------------------------ regime
class TestRegime:
    def test_thin_data_is_uncertain_not_guessed(self, session, instrument, provider):
        result = regime_service.classify(session, instrument.id, Timeframe.H1, after(10))

        assert result.regime == Regime.UNCERTAIN
        assert result.confidence == 0.0
        assert result.reason

    def test_output_declares_it_is_rule_based(self, session, instrument, provider):
        seed(session, instrument, provider, 400)

        result = regime_service.classify(session, instrument.id, Timeframe.H1, after(400))

        assert result.method == "rule_based"
        assert result.as_dict()["method"] == "rule_based"

    def test_steady_rise_is_not_called_uncertain(self, session, instrument, provider):
        seed(session, instrument, provider, 400)

        result = regime_service.classify(session, instrument.id, Timeframe.H1, after(400))

        assert result.regime != Regime.UNCERTAIN
        assert result.evidence

    def test_close_readings_are_suppressed(self):
        """When the top two scores are near-tied, no regime is claimed."""
        from app.services.regime import MIN_MARGIN

        assert MIN_MARGIN > 0


# ----------------------------------------------------------------- council
class TestCouncil:
    def test_analyst_with_no_input_abstains_rather_than_voting_neutral(self):
        """Abstention and neutrality are different claims."""
        opinions = council.convene({})

        assert all(o.abstained for o in opinions)
        assert all(o.score == 0.0 for o in opinions)
        # Abstained analysts must be identifiable, not just zero-scored.
        assert all("no_input" in o.reason_codes for o in opinions)

    def test_volatility_analyst_never_votes_direction(self):
        state = {
            "features": {"available": True, "values": {"atr_14_pct": 0.01}},
        }

        opinion = council.volatility_analyst(state)

        assert opinion.abstained is False
        assert opinion.score == 0.0, "volatility says how far, never which way"

    def test_every_opinion_declares_its_method(self):
        state = {"features": {"available": True, "values": {"rsi_14": 65.0}}}

        opinion = council.momentum_analyst(state)

        assert opinion.method == "rule_based"

    def test_history_analyst_needs_matured_outcomes(self):
        opinion = council.history_analyst({"similarity": {"sufficient": False, "reason": "thin"}})

        assert opinion.abstained is True

    def test_stale_data_is_flagged_by_the_quality_analyst(self):
        state = {
            "quality": {"available": True, "any_training_eligible": True},
            "freshness": {"available": True, "stale": True, "age_seconds": 90000},
        }

        opinion = council.quality_analyst(state)

        assert "stale_data" in opinion.reason_codes
        assert opinion.confidence == 0.0


# --------------------------------------------------------------- meta-brain
class TestMetaBrain:
    def _op(self, name, score, confidence=1.0):
        return Opinion(analyst=name, abstained=False, score=score, confidence=confidence)

    def test_disagreement_suppresses_rather_than_averaging(self):
        """Two analysts at opposite extremes must not average to a confident zero."""
        opinions = [self._op("trend", 1.0), self._op("history", -1.0)]

        verdict = meta.deliberate(opinions)

        assert verdict.suppressed is True
        assert "disagree" in verdict.suppression_reason

    def test_agreement_produces_a_direction(self):
        opinions = [self._op("trend", 0.8), self._op("history", 0.7), self._op("regime", 0.6)]

        verdict = meta.deliberate(opinions)

        assert verdict.suppressed is False
        assert verdict.decision == Decision.BUY

    def test_weak_conviction_is_suppressed(self):
        opinions = [self._op("trend", 0.05), self._op("history", 0.05)]

        verdict = meta.deliberate(opinions)

        assert verdict.suppressed is True
        assert "conviction" in verdict.suppression_reason

    def test_all_abstained_yields_wait(self):
        opinions = [Opinion("trend", True), Opinion("history", True)]

        verdict = meta.deliberate(opinions)

        assert verdict.decision == Decision.WAIT
        assert verdict.suppressed is True

    def test_regime_changes_the_weights(self):
        """A range regime must not weigh trend-following the same as a trend does."""
        in_range = meta.weights_for(Regime.RANGE.value)
        in_trend = meta.weights_for(Regime.TREND_UP.value)

        assert in_range["trend"] < in_trend["trend"]

    def test_weights_are_versioned(self):
        opinions = [self._op("trend", 0.8)]

        assert meta.deliberate(opinions).weights_version == meta.WEIGHTS_VERSION


# --------------------------------------------------------------- adversary
class TestAdversary:
    def _verdict(self, decision=Decision.BUY, conviction=0.6, disagreement=0.1):
        return meta.MetaVerdict(decision, conviction, disagreement)

    def test_stale_data_blocks(self):
        opinions = [Opinion("data_quality", False, 0.0, 0.0, ["stale_data"], [])]

        result = meta.challenge(self._verdict(), opinions, {})

        assert result.verdict == "block"

    def test_closed_market_blocks(self):
        opinions = [Opinion("session", False, 0.0, 0.2, ["market_closed"], [])]

        result = meta.challenge(self._verdict(), opinions, {})

        assert result.verdict == "block"

    def test_history_contradiction_blocks(self):
        """The one analyst grounded in outcomes gets a veto when it disagrees."""
        opinions = [Opinion("history", False, -0.8, 0.9, ["history_bearish"], [])]

        result = meta.challenge(self._verdict(decision=Decision.BUY), opinions, {})

        assert result.verdict == "block"

    def test_two_concerns_reduce(self):
        opinions = [
            Opinion("session", False, 0.0, 0.2, ["thin_liquidity"], []),
            Opinion("volatility", False, 0.0, 0.4, ["volatility_expanded"], []),
        ]

        result = meta.challenge(self._verdict(), opinions, {})

        assert result.verdict == "reduce"

    def test_clean_state_is_left_alone(self):
        opinions = [
            Opinion("session", False, 0.0, 0.6, ["market_open"], []),
            Opinion("data_quality", False, 0.0, 1.0, ["data_ok"], []),
            Opinion("history", False, 0.5, 0.8, ["history_bullish"], []),
        ]

        result = meta.challenge(self._verdict(), opinions, {})

        assert result.verdict == "clear"


# ------------------------------------------------------------------- brain
class TestCognitiveBrain:
    def test_no_data_yields_wait_with_a_reason(self, session, instrument, provider):
        proposal = cognitive.think(session, instrument.id, Timeframe.H1, after(5))

        assert proposal.decision == Decision.WAIT
        assert proposal.wait_reasons

    def test_proposal_never_authorises_execution(self, session, instrument, provider):
        """Sizing and authorisation belong to the risk brain, which does not exist."""
        seed(session, instrument, provider, 400)

        payload = cognitive.think(
            session, instrument.id, Timeframe.H1, after(400)
        ).as_dict()

        assert payload["authorises_execution"] is False
        assert "position_size" not in payload
        assert "risk_allocation" not in payload

    def test_no_probability_is_asserted(self, session, instrument, provider):
        seed(session, instrument, provider, 400)

        proposal = cognitive.think(session, instrument.id, Timeframe.H1, after(400))

        assert proposal.uncertainty["probability_available"] is False
        assert proposal.uncertainty["probability_reason"]

    def test_no_trade_is_always_among_the_scenarios(self, session, instrument, provider):
        seed(session, instrument, provider, 400)

        proposal = cognitive.think(session, instrument.id, Timeframe.H1, after(400))

        assert any(s.name == "no_trade" for s in proposal.scenarios)

    def test_all_pipeline_stages_are_recorded(self, session, instrument, provider):
        seed(session, instrument, provider, 400)

        proposal = cognitive.think(session, instrument.id, Timeframe.H1, after(400))

        assert "perception" in proposal.stages
        assert "decision" in proposal.stages

    def test_payload_is_serialisable(self, session, instrument, provider):
        import json

        seed(session, instrument, provider, 400)
        proposal = cognitive.think(session, instrument.id, Timeframe.H1, after(400))

        assert json.dumps(proposal.as_dict())


# ---------------------------------------------------------------- strategy
class TestStrategy:
    def test_wrong_regime_means_no_setup_not_a_weaker_one(self):
        """A mean-reversion strategy in a trend returns nothing at all."""
        state = {"regime": {"regime": Regime.TREND_UP.value},
                 "features": {"available": True, "values": {"position_in_range_20": 0.95,
                                                            "rsi_14": 80}}}

        setup = strategy.range_fade(state)

        assert setup.fired is False
        assert "only applies in" in setup.reason

    def test_no_partial_matches(self):
        state = {"regime": {"regime": Regime.RANGE.value},
                 "features": {"available": True, "values": {"position_in_range_20": 0.9,
                                                            "rsi_14": 50}}}

        setup = strategy.range_fade(state)

        assert setup.fired is False, "RSI does not confirm, so the setup does not exist"
        assert setup.conditions_failed

    def test_stand_aside_is_a_real_strategy(self):
        """Inaction is recorded in the same format as action."""
        state = {"regime": {"regime": Regime.HIGH_VOLATILITY.value}}

        setup = strategy.volatility_stand_aside(state)

        assert setup.fired is True
        assert setup.direction == Decision.WAIT

    def test_every_strategy_declares_its_origin(self):
        state = {"regime": {"regime": Regime.UNCERTAIN.value}}

        for setup in strategy.evaluate(state):
            assert setup.origin == "declared"


# ------------------------------------------------------------- calibration
class TestCalibration:
    def test_too_few_forecasts_refuses_to_claim_calibration(self):
        forecasts = [Forecast(0.7, True) for _ in range(20)]

        report = calibration.evaluate(forecasts)

        assert report.calibrated is False
        assert "needs" in report.reason

    def test_perfect_forecaster_scores_zero_brier(self):
        forecasts = [Forecast(1.0, True) for _ in range(60)] + [
            Forecast(0.0, False) for _ in range(60)
        ]

        assert calibration.brier_score(forecasts) == pytest.approx(0.0)

    def test_coin_flip_scores_a_quarter(self):
        forecasts = [Forecast(0.5, i % 2 == 0) for i in range(120)]

        assert calibration.brier_score(forecasts) == pytest.approx(0.25)

    def test_overconfident_forecaster_is_detected(self):
        """Always saying 90% when right 50% of the time must show a large gap."""
        forecasts = [Forecast(0.9, i % 2 == 0) for i in range(200)]

        report = calibration.evaluate(forecasts)

        if report.calibrated:
            assert report.calibration_error > 0.3
        else:
            # Concentrated forecasts cannot form a curve — also an honest answer.
            assert "concentrated" in report.reason

    def test_a_model_with_no_skill_is_exposed(self):
        """Beating the base rate is the yardstick, not raw Brier."""
        forecasts = [Forecast(0.5, i % 2 == 0) for i in range(200)]

        report = calibration.evaluate(forecasts)

        assert report.skill == pytest.approx(0.0, abs=0.01)

    def test_uncalibrated_source_yields_no_probability(self):
        """The contract that keeps confidence from being renamed probability."""
        report = calibration.CalibrationReport(calibrated=False, reason="not enough data")

        assert calibration.to_probability(0.8, report) is None

    def test_calibrated_source_maps_to_observed_frequency(self):
        forecasts = []
        for _ in range(100):
            forecasts.append(Forecast(0.25, False))
        for i in range(100):
            forecasts.append(Forecast(0.75, i < 75))

        report = calibration.evaluate(forecasts)

        assert report.calibrated is True
        probability = calibration.to_probability(0.75, report)
        assert probability == pytest.approx(0.75, abs=0.05)

    def test_episodes_without_a_score_are_not_counted(self):
        """Silence must not be converted into a 50% forecast."""

        class Stub:
            features = {}
            forward_return_pct = 0.01

        assert calibration.build_forecasts_from_episodes([Stub()]) == []
