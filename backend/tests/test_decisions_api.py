"""Decision, posture and readiness endpoint tests (phases 38-40).

These are the three screens an operator actually opens, so the tests are about
what the screens must never say: that the system can trade when it cannot, that
a decision is an order, or that a figure was measured when nobody measured it.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.enums import Timeframe
from tests.conftest import BASE_TIME, insert_bar


@pytest.fixture()
def client(session):
    from app.db.session import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def seed(session, instrument, provider, count=400):
    for hour in range(count):
        close = 1.10 + hour * 0.0002
        insert_bar(
            session, instrument.id, provider.id,
            event_time=BASE_TIME + timedelta(hours=hour),
            ingested_at=BASE_TIME + timedelta(hours=hour),
            close=round(close, 8), open_=round(close - 0.0002, 8),
        )
    session.commit()


class TestPosture:
    def test_the_default_deployment_cannot_trade(self, client):
        payload = client.get("/api/v1/decisions/posture").json()

        assert payload["can_trade"] is False
        assert len(payload["blockers"]) >= 3

    def test_every_blocker_is_named(self, client):
        blockers = client.get("/api/v1/decisions/posture").json()["blockers"]

        joined = " ".join(blockers)
        assert "disabled" in joined
        assert "dry run" in joined
        assert "authentication" in joined

    def test_it_reports_the_live_router_table(self, client):
        """A posture view built from a stored summary reassures during the
        incident it should be flagging."""
        payload = client.get("/api/v1/decisions/posture").json()

        assert payload["routes"]["mutating"] == []
        assert payload["routes"]["ungated"] == []

    def test_it_changes_nothing(self, client):
        assert "changes nothing" in client.get("/api/v1/decisions/posture").json()["note"]


class TestReadiness:
    def test_readiness_is_not_health(self, client):
        """A process can be entirely healthy and entirely unready."""
        health = client.get("/health/live")
        readiness = client.get("/api/v1/decisions/readiness")

        assert health.status_code == 200
        assert readiness.json()["safe_to_trade"] is False

    def test_what_the_process_cannot_see_is_graded_as_unknown(self, client):
        """Guessing the host's disk or restore history is the one thing the
        readiness module refuses to do."""
        checks = {c["name"]: c for c in client.get("/api/v1/decisions/readiness").json()["checks"]}

        assert "could not be determined" in checks["disk_headroom"]["detail"]
        assert "could not be determined" in checks["restore_drill_recent"]["detail"]

    def test_what_it_can_see_is_graded_properly(self, client):
        checks = {c["name"]: c for c in client.get("/api/v1/decisions/readiness").json()["checks"]}

        assert checks["no_ungated_mutating_routes"]["passed"] is True
        assert checks["kill_switch_defaults_engaged"]["passed"] is True

    def test_it_never_grades_the_strategy(self, client):
        payload = client.get("/api/v1/decisions/readiness").json()

        assert "not whether the strategy" in payload["note"]


class TestDecisionPreview:
    def test_a_decision_returns_its_trace(self, client, session, instrument, provider):
        seed(session, instrument, provider)

        response = client.get(
            f"/api/v1/decisions/{instrument.id}",
            params={"timeframe": Timeframe.H1.value,
                    "as_of": (BASE_TIME + timedelta(hours=399)).isoformat()},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["symbol"] == instrument.symbol
        assert isinstance(payload["stages"], list)

    def test_the_chain_stops_and_the_trace_says_where(
        self, client, session, instrument, provider
    ):
        seed(session, instrument, provider)

        payload = client.get(
            f"/api/v1/decisions/{instrument.id}",
            params={"as_of": (BASE_TIME + timedelta(hours=399)).isoformat()},
        ).json()

        assert payload["reached_intent"] is False
        assert payload["stopped_at"] is not None

    def test_a_decision_is_never_an_order(self, client, session, instrument, provider):
        seed(session, instrument, provider)

        payload = client.get(
            f"/api/v1/decisions/{instrument.id}",
            params={"as_of": (BASE_TIME + timedelta(hours=399)).isoformat()},
        ).json()

        assert payload["authorises_execution"] is False

    def test_the_policy_constants_are_visible_to_the_reader(
        self, client, session, instrument, provider
    ):
        """So nobody reads the levels as derived facts."""
        seed(session, instrument, provider)

        payload = client.get(
            f"/api/v1/decisions/{instrument.id}",
            params={"as_of": (BASE_TIME + timedelta(hours=399)).isoformat()},
        ).json()

        assert payload["policy"]["stop_atr_multiple"] > 0

    def test_an_unknown_instrument_is_a_clean_error(self, client):
        response = client.get("/api/v1/decisions/00000000-0000-0000-0000-000000000000")

        assert response.status_code in (404, 409, 422)

    def test_a_non_positive_equity_is_refused(self, client, instrument):
        response = client.get(
            f"/api/v1/decisions/{instrument.id}", params={"equity": 0}
        )

        assert response.status_code == 422

    def test_the_preview_invents_no_trade_history(
        self, client, session, instrument, provider
    ):
        """A plausible history would let stress project survival for an account
        that has never traded."""
        seed(session, instrument, provider)

        payload = client.get(
            f"/api/v1/decisions/{instrument.id}",
            params={"as_of": (BASE_TIME + timedelta(hours=399)).isoformat()},
        ).json()
        stress = [s for s in payload["stages"] if s["stage"] == "stress"]

        assert stress == [] or stress[0]["passed"] is False
