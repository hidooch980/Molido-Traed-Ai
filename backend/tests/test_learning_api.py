"""Learning endpoints (spec §31-36).

The modules behind these have their own suites. What is tested here is the
thing an HTTP layer is uniquely good at getting wrong in this particular group:
turning a refusal into a number. Every endpoint below has a path where the
honest answer is "not enough evidence", and each of those paths is asserted,
because an endpoint that quietly returns 0.0 or an empty list instead reads as
a healthy system to anybody looking at a dashboard.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.learning import scorecard as sc


@pytest.fixture()
def client(session):
    from app.db.session import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class TestThresholds:
    def test_every_threshold_is_published_with_a_reason(self, client):
        """A line nobody can see is a line nobody can argue with."""
        payload = client.get("/api/v1/learning/thresholds").json()

        for group in ("scorecard", "registry", "drift"):
            assert payload[group]["why"], group

    def test_they_match_the_modules_rather_than_being_retyped(self, client):
        payload = client.get("/api/v1/learning/thresholds").json()

        assert payload["scorecard"]["min_trials"] == sc.MIN_TRIALS

    def test_they_are_named_as_policy_not_measurement(self, client):
        assert "policy" in client.get("/api/v1/learning/thresholds").json()["note"]


class TestScorecard:
    def test_a_small_sample_returns_a_refusal_not_a_rate(self, client):
        payload = client.get(
            "/api/v1/learning/scorecard", params={"wins": 9, "losses": 20}
        ).json()

        assert payload["verdict"] == "insufficient"
        assert payload["hit_rate"] is None
        assert "answerable" in payload["reason"]

    def test_a_real_edge_is_reported_as_one(self, client):
        payload = client.get(
            "/api/v1/learning/scorecard", params={"wins": 300, "losses": 300}
        ).json()

        assert payload["verdict"] == "edge"
        assert payload["hit_rate_95ci"][0] > payload["required_hit_rate"]

    def test_a_losing_strategy_is_named(self, client):
        payload = client.get(
            "/api/v1/learning/scorecard", params={"wins": 60, "losses": 540}
        ).json()

        assert payload["verdict"] == "negative"

    def test_the_realised_payoff_sets_the_bar_not_the_intended_one(self, client):
        """A strategy built to 2R that returns 1.3R needs 43%, not 33%."""
        generous = client.get(
            "/api/v1/learning/scorecard",
            params={"wins": 100, "losses": 200, "average_win_r": 2.0},
        ).json()
        realistic = client.get(
            "/api/v1/learning/scorecard",
            params={"wins": 100, "losses": 200, "average_win_r": 1.3},
        ).json()

        assert realistic["required_hit_rate"] > generous["required_hit_rate"]

    def test_testing_many_strategies_shows_both_verdicts(self, client):
        """The uncorrected verdict is published beside the corrected one, so a
        reader can see exactly what the correction cost."""
        payload = client.get(
            "/api/v1/learning/scorecard",
            params={"wins": 120, "losses": 180, "comparisons": 20},
        ).json()

        assert payload["verdict"] == "insufficient"
        assert payload["uncorrected_comparison"] == "edge"

    def test_a_single_comparison_reports_no_correction(self, client):
        payload = client.get(
            "/api/v1/learning/scorecard", params={"wins": 300, "losses": 300}
        ).json()

        assert payload["uncorrected_comparison"] is None

    def test_unresolved_trials_are_counted_and_excluded(self, client):
        payload = client.get(
            "/api/v1/learning/scorecard",
            params={"wins": 100, "losses": 200, "unresolved": 40},
        ).json()

        assert payload["unresolved"] == 40
        assert payload["trials"] == 300

    def test_a_measured_edge_is_never_called_a_forecast(self, client):
        payload = client.get(
            "/api/v1/learning/scorecard", params={"wins": 300, "losses": 300}
        ).json()

        assert "evidence, not a forecast" in payload["note"]


class TestBreakeven:
    def test_two_to_one_needs_a_third(self, client):
        payload = client.get(
            "/api/v1/learning/breakeven", params={"reward_risk": 2.0}
        ).json()

        assert payload["required_hit_rate"] == pytest.approx(1 / 3, abs=1e-5)

    def test_one_to_one_needs_a_half(self, client):
        payload = client.get(
            "/api/v1/learning/breakeven", params={"reward_risk": 1.0}
        ).json()

        assert payload["required_hit_rate"] == pytest.approx(0.5)

    def test_a_non_positive_payoff_is_refused_by_validation(self, client):
        assert client.get(
            "/api/v1/learning/breakeven", params={"reward_risk": 0}
        ).status_code == 422


class TestWalkForward:
    def test_a_plan_reports_what_purging_and_the_embargo_cost(self, client):
        payload = client.get(
            "/api/v1/learning/walk-forward",
            params={"samples": 400, "folds": 3, "embargo_hours": 6},
        ).json()

        assert payload["available"] is True
        assert payload["total_purged"] > 0
        assert payload["total_embargoed"] > 0

    def test_every_plan_is_verified_rather_than_trusted(self, client):
        """The builder that erred would record the error consistently."""
        payload = client.get("/api/v1/learning/walk-forward").json()

        assert payload["leakage_verified"] is True

    def test_a_longer_maturity_purges_more(self, client):
        short = client.get(
            "/api/v1/learning/walk-forward", params={"maturity_hours": 2}
        ).json()
        long = client.get(
            "/api/v1/learning/walk-forward", params={"maturity_hours": 72}
        ).json()

        assert long["total_purged"] > short["total_purged"]

    def test_too_little_data_refuses_rather_than_shrinking_the_folds(self, client):
        payload = client.get(
            "/api/v1/learning/walk-forward", params={"samples": 40, "folds": 5}
        ).json()

        assert payload["available"] is False
        assert "not a fold" in payload["note"]

    def test_no_embargo_is_reported_in_the_notes(self, client):
        payload = client.get(
            "/api/v1/learning/walk-forward", params={"embargo_hours": 0}
        ).json()

        assert any("no embargo" in n for n in payload["notes"])


class TestDriftAndRegistryRefuseHonestly:
    def test_drift_reports_no_sample_rather_than_stable(self, client):
        """A drift monitor that reports stable before it has data reports
        stable forever."""
        payload = client.get("/api/v1/learning/drift").json()

        assert payload["feature_drift"]["available"] is False
        assert payload["concept_drift"]["available"] is False
        assert "stable forever" in payload["note"]

    def test_each_drift_kind_gives_its_own_reason(self, client):
        payload = client.get("/api/v1/learning/drift").json()

        assert payload["feature_drift"]["reason"]
        assert payload["concept_drift"]["reason"]
        assert payload["feature_drift"]["reason"] != payload["concept_drift"]["reason"]

    def test_an_empty_registry_explains_itself(self, client):
        """An empty list on its own reads as "nothing is wrong"."""
        payload = client.get("/api/v1/learning/registry").json()

        assert payload["versions"] == []
        assert payload["champion"] is None
        assert "expected value refuses" in payload["reason"]

    def test_the_promotion_rules_are_published(self, client):
        payload = client.get("/api/v1/learning/registry").json()

        assert payload["promotion_requires"]["min_overlap"] > 0
        assert "shadow" in payload["promotion_requires"]["and"]


class TestTheGateStillHolds:
    def test_none_of_these_routes_mutate(self, client):
        from app.api.guard import find_ungated_routes, mutating_routes
        from app.main import app

        assert mutating_routes(app) == []
        assert find_ungated_routes(app, require_auth=False) == []
