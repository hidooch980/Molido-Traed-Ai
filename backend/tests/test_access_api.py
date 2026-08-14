"""The access layer over HTTP.

The published matrix has to be the enforced one. A permission table that lives
in a handler rather than being read from the dependency's own table is a
document, and documents drift - it would keep telling an auditor the system
does something it stopped doing months ago.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import ROLE_PERMISSIONS
from app.core.plans import CATALOG, Feature, Plan


@pytest.fixture()
def client(session):
    from app.db.session import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class TestTheRoutesExist:
    @pytest.mark.parametrize("path", ["roles", "plans", "features", "matrix"])
    def test_it_answers(self, client, path):
        assert client.get(f"/api/v1/access/{path}").status_code == 200

    def test_none_of_them_mutate(self, client):
        from app.api.guard import find_ungated_routes
        from app.main import app

        # Not "there are no mutating routes" - there is one now, and the
        # gate was built for exactly that. What must stay true is that
        # every one of them is gated.
        assert find_ungated_routes(app, require_auth=False) == []


class TestThePublishedMatrixIsTheEnforcedOne:
    def test_roles_come_from_the_dependency_table(self, client):
        """Not a copy. A hand-written table in the handler would pass its own
        tests forever while the real one changed underneath it."""
        payload = client.get("/api/v1/access/roles").json()
        published = {row["role"]: set(row["permissions"]) for row in payload["roles"]}
        enforced = {
            role.value: {p.value for p in perms} for role, perms in ROLE_PERMISSIONS.items()
        }

        assert published == enforced

    def test_every_catalogued_feature_is_published(self, client):
        payload = client.get("/api/v1/access/plans").json()

        assert len(payload["features"]) == len(CATALOG)

    def test_every_feature_carries_its_reason(self, client):
        payload = client.get("/api/v1/access/plans").json()

        assert all(len(f["why"]) > 20 for f in payload["features"])


class TestTheTwoAxesStayApart:
    def test_an_admin_on_free_cannot_reach_live_execution(self, client):
        """The load-bearing row. A role grants authority to act; a plan grants
        access to the capability. If this were true, the two checks would have
        collapsed into one and the safer one would have lost."""
        rows = client.get("/api/v1/access/matrix").json()["matrix"]
        admin_free = next(r for r in rows if r["role"] == "admin" and r["plan"] == "free")

        assert admin_free["holds_execute_permission"] is True
        assert admin_free["plan_includes_live_execution"] is False
        assert admin_free["could_place_an_order"] is False

    def test_a_viewer_on_paid_cannot_place_an_order_either(self, client):
        rows = client.get("/api/v1/access/matrix").json()["matrix"]
        viewer_paid = next(r for r in rows if r["role"] == "viewer" and r["plan"] == "paid")

        assert viewer_paid["plan_includes_live_execution"] is True
        assert viewer_paid["holds_execute_permission"] is False
        assert viewer_paid["could_place_an_order"] is False

    def test_only_both_together_open_it(self, client):
        rows = client.get("/api/v1/access/matrix").json()["matrix"]
        opens = [r for r in rows if r["could_place_an_order"]]

        assert opens
        assert all(r["plan"] == "paid" for r in opens)
        assert all(r["holds_execute_permission"] for r in opens)

    def test_the_response_says_it_still_refuses(self, client):
        """The matrix describes what the model would permit. This deployment
        permits none of it, and the payload has to say so or the table reads as
        a live capability."""
        payload = client.get("/api/v1/access/matrix").json()

        assert "no route in this API places an order" in payload["still_refused_here"]


class TestConditionsAreReportedApartFromPaywalls:
    def test_a_condition_is_not_reported_as_a_missing_plan(self, client):
        payload = client.get(
            "/api/v1/access/features", params={"plan": "conditional"}
        ).json()

        assert Feature.JOURNAL.value in payload["awaiting_condition"]
        assert Feature.LIVE_EXECUTION.value in payload["beyond_plan"]

    def test_meeting_a_condition_moves_the_feature(self, client):
        before = client.get(
            "/api/v1/access/features", params={"plan": "conditional"}
        ).json()
        after = client.get(
            "/api/v1/access/features",
            params={"plan": "conditional", "satisfied": "fifty_resolved_trades"},
        ).json()

        assert Feature.JOURNAL.value in before["awaiting_condition"]
        assert Feature.JOURNAL.value in after["included"]

    def test_an_unknown_condition_is_ignored_rather_than_honoured(self, client):
        """A caller must not unlock anything by naming a condition that does
        not exist."""
        payload = client.get(
            "/api/v1/access/features",
            params={"plan": "conditional", "satisfied": "i_am_definitely_calibrated"},
        ).json()

        assert payload["conditions_met"] == []
        assert Feature.JOURNAL.value in payload["awaiting_condition"]

    def test_measurement_is_free_at_every_tier(self, client):
        for plan in Plan:
            payload = client.get("/api/v1/access/features", params={"plan": plan.value}).json()

            assert Feature.MEASUREMENT.value in payload["included"]

    def test_the_payload_states_there_is_no_billing(self, client):
        payload = client.get("/api/v1/access/plans").json()

        assert "no payment processor" in payload["billing"]
