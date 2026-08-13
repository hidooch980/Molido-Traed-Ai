"""Risk endpoints (spec §21-24, §30).

These expose four brains that already have thorough suites of their own, so
these tests are not about whether the brains decide well. They are about the
two ways an HTTP layer quietly makes a strict brain permissive: by defaulting a
parameter the brain treats as unknown, and by dropping a refusal on the way out.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(session):
    from app.db.session import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class TestLimits:
    def test_the_hard_limits_are_published(self, client):
        """A limit nobody can see is a limit nobody can plan against."""
        payload = client.get("/api/v1/risk/limits").json()

        assert payload["hard"]["max_total_drawdown_pct"] > 0
        assert payload["hard"]["max_risk_per_trade_r"] > 0
        assert payload["hard_limits_are_frozen"] is True

    def test_the_endpoint_offers_no_way_to_change_them(self, client):
        assert client.post("/api/v1/risk/limits").status_code == 405

    def test_portfolio_ceilings_are_published_too(self, client):
        payload = client.get("/api/v1/risk/limits").json()

        assert payload["portfolio"]["max_total_risk_r"] > 0
        assert 0 < payload["portfolio"]["correlation_cluster"] <= 1


class TestAuthorise:
    def test_an_omitted_feed_age_blocks(self, client):
        """The endpoint must not be more permissive than the brain.

        `data_age_bars` omitted means unknown, and unknown blocks. Defaulting
        it to zero here would have made every caller who forgot it look fresh.
        """
        payload = client.get("/api/v1/risk/authorise").json()

        assert payload["verdict"] == "block"
        assert any("freshness unknown" in b for b in payload["hard_breaches"])

    def test_a_fresh_calibrated_account_is_permitted_something(self, client):
        payload = client.get(
            "/api/v1/risk/authorise",
            params={
                "requested_risk_r": 1.0, "data_age_bars": 0.5,
                "calibrated": True, "training_eligible": True,
            },
        ).json()

        assert payload["verdict"] == "approve"
        assert payload["permitted_risk_r"] == pytest.approx(1.0)

    def test_uncertainty_reduces_the_permitted_size(self, client):
        certain = client.get(
            "/api/v1/risk/authorise",
            params={"data_age_bars": 0.5, "calibrated": True, "training_eligible": True},
        ).json()
        uncertain = client.get(
            "/api/v1/risk/authorise",
            params={"data_age_bars": 0.5, "calibrated": False, "training_eligible": True},
        ).json()

        assert uncertain["permitted_risk_r"] < certain["permitted_risk_r"]

    def test_safe_mode_blocks_over_http_too(self, client):
        payload = client.get(
            "/api/v1/risk/authorise",
            params={"data_age_bars": 0.5, "calibrated": True, "safe_mode": True},
        ).json()

        assert payload["verdict"] == "block"

    def test_a_drawdown_at_the_ceiling_blocks(self, client):
        payload = client.get(
            "/api/v1/risk/authorise",
            params={
                "equity": 89_000, "peak_equity": 100_000,
                "data_age_bars": 0.5, "calibrated": True,
            },
        ).json()

        assert payload["verdict"] == "block"

    def test_no_response_claims_execution_authority(self, client):
        payload = client.get(
            "/api/v1/risk/authorise", params={"data_age_bars": 0.5, "calibrated": True}
        ).json()

        assert payload["authorises_execution"] is False

    def test_a_non_positive_request_is_refused_by_validation(self, client):
        assert client.get(
            "/api/v1/risk/authorise", params={"requested_risk_r": 0}
        ).status_code == 422


class TestPortfolio:
    def test_an_empty_book_approves_in_full(self, client):
        payload = client.get(
            "/api/v1/risk/portfolio", params={"symbol": "EURUSD"}
        ).json()

        assert payload["verdict"] == "approve"
        assert payload["max_additional_risk_r"] == pytest.approx(1.0)

    def test_a_full_book_blocks(self, client):
        book = ",".join(f"SYM{i}USD:buy:1.0" for i in range(6))
        payload = client.get(
            "/api/v1/risk/portfolio", params={"symbol": "EURUSD", "open_symbols": book}
        ).json()

        assert payload["verdict"] == "block"
        assert payload["positions_parsed"] == 6

    def test_unmeasured_correlation_is_reported_not_assumed_away(self, client):
        payload = client.get(
            "/api/v1/risk/portfolio",
            params={"symbol": "EURUSD", "open_symbols": "GBPUSD:buy:1.0"},
        ).json()

        assert any("not as uncorrelated" in w for w in payload["warnings"])

    def test_correlations_cannot_be_asserted_by_the_caller(self, client):
        """They are measured from bars. Letting a caller supply them hands the
        one input that makes a book look diversified to whoever wants that."""
        response = client.get(
            "/api/v1/risk/portfolio",
            params={"symbol": "EURUSD", "correlations": "GBPUSD:0.0"},
        )

        assert response.status_code == 200
        assert "correlations" not in response.json()

    def test_a_malformed_position_is_skipped_not_guessed(self, client):
        payload = client.get(
            "/api/v1/risk/portfolio",
            params={"symbol": "EURUSD", "open_symbols": "nonsense,GBPUSD:buy:1.0"},
        ).json()

        assert payload["positions_parsed"] == 1


class TestStress:
    def test_an_impossible_history_is_refused_not_projected(self, client):
        """More wins than trades is a broken input, not a number to clamp."""
        payload = client.get(
            "/api/v1/risk/stress",
            params={"trades": 200, "wins": 300, "average_win_r": 1.5,
                    "average_loss_r": 1.0, "calibrated": True},
        ).json()

        assert payload["available"] is False
        assert "invented" in payload["note"]

    def test_an_uncalibrated_history_yields_no_ruin_figure(self, client):
        payload = client.get(
            "/api/v1/risk/stress",
            params={"trades": 300, "wins": 170, "average_win_r": 1.6,
                    "average_loss_r": 1.0, "calibrated": False},
        ).json()

        assert payload["risk_of_ruin"]["available"] is False

    def test_all_four_scenarios_are_returned(self, client):
        payload = client.get(
            "/api/v1/risk/stress",
            params={"trades": 300, "wins": 170, "average_win_r": 1.6,
                    "average_loss_r": 1.0, "calibrated": True},
        ).json()

        assert set(payload["scenarios"]) == {"base", "adverse", "stress", "extreme"}

    def test_oversizing_is_visible_in_the_verdict(self, client):
        params = {"trades": 300, "wins": 170, "average_win_r": 1.6,
                  "average_loss_r": 1.0, "calibrated": True}
        small = client.get("/api/v1/risk/stress", params={**params, "r_value_pct": 0.002}).json()
        large = client.get("/api/v1/risk/stress", params={**params, "r_value_pct": 0.05}).json()

        assert small["verdict"] != "block"
        assert large["verdict"] == "block"


class TestChallenge:
    def test_a_healthy_account_is_in_progress(self, client):
        payload = client.get("/api/v1/risk/challenge").json()

        assert payload["status"] == "in_progress"

    def test_a_breached_total_drawdown_fails_the_challenge(self, client):
        payload = client.get(
            "/api/v1/risk/challenge",
            params={"current_equity": 88_000, "daily_starting_equity": 88_500},
        ).json()

        assert payload["status"] == "failed"
        assert payload["breaches"]

    def test_the_rulebook_says_it_is_an_example(self, client):
        """Defaults are for a demonstration. A real provider's rules have to be
        entered and confirmed by whoever signed up for them."""
        payload = client.get("/api/v1/risk/challenge").json()

        assert "not a provider's verified rules" in payload["rulebook_source"]

    def test_no_challenge_response_authorises_execution(self, client):
        payload = client.get("/api/v1/risk/challenge").json()

        assert payload["authorises_execution"] is False


class TestTheGateStillHolds:
    def test_none_of_these_routes_mutate(self, client):
        from app.api.guard import find_ungated_routes, mutating_routes
        from app.main import app

        assert mutating_routes(app) == []
        assert find_ungated_routes(app, require_auth=False) == []
