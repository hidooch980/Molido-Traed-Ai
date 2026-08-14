"""Chat, automation and security endpoints (spec §46-47, §52).

The channel these describe is the one place in the system where instructions
arrive from outside, so these tests are almost entirely about refusal — and
about the difference between describing a channel and being one.
"""

from __future__ import annotations

import ast
import inspect

import pytest
from fastapi.testclient import TestClient

from app.integrations import notify


@pytest.fixture()
def client(session):
    from app.db.session import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class TestNothingInboundCanAct:
    def test_the_module_never_reaches_execution_or_the_pipeline(self):
        import app.api.v1.integrations as module

        tree = ast.parse(inspect.getsource(module))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

        assert not any(m.startswith("app.execution") for m in imported)
        assert not any(m.startswith("app.pipeline") for m in imported)

    @pytest.mark.parametrize(
        "text", ["/buy EURUSD", "/close all", "/setrisk 5", "/disengage", "/execute"]
    )
    def test_every_actionable_command_is_refused(self, client, text):
        payload = client.get(
            "/api/v1/integrations/command-check", params={"text": text}
        ).json()

        assert payload["accepted"] is False
        assert payload["executed"] is False

    def test_the_refusal_explains_the_reasoning(self, client):
        payload = client.get(
            "/api/v1/integrations/command-check", params={"text": "/buy"}
        ).json()

        assert "channel, not a person" in payload["reason"]

    def test_an_accepted_command_is_still_not_run(self, client):
        """Checking a command is not running it."""
        payload = client.get(
            "/api/v1/integrations/command-check", params={"text": "/status"}
        ).json()

        assert payload["accepted"] is True
        assert payload["executed"] is False

    def test_the_allowlist_contains_nothing_that_acts(self, client):
        allowed = set(client.get("/api/v1/integrations/commands").json()["allowed"])

        assert allowed & {"buy", "sell", "close", "execute", "disengage"} == set()

    def test_it_is_an_allowlist_by_design(self, client):
        """A blocklist has to anticipate every verb somebody adds later."""
        payload = client.get("/api/v1/integrations/commands").json()

        assert payload["allowlist_not_blocklist"] is True
        assert "execute permission" in payload["trading_requires"]

    def test_the_endpoints_offer_no_post(self, client):
        for path in ("commands", "command-check", "webhooks", "security"):
            assert client.post(f"/api/v1/integrations/{path}").status_code == 405


class TestWebhooks:
    def test_a_valid_signature_alone_is_not_enough(self, client):
        payload = client.get("/api/v1/integrations/webhooks").json()

        assert payload["max_age_seconds"] == notify.MAX_WEBHOOK_AGE.total_seconds()
        assert "replayed" in payload["why_max_age"]

    def test_constant_time_comparison_is_explained(self, client):
        payload = client.get("/api/v1/integrations/webhooks").json()

        assert "leading bytes" in payload["why_constant_time"]

    def test_an_unset_secret_is_not_accept_everything(self, client):
        payload = client.get("/api/v1/integrations/webhooks").json()

        assert payload["secret_configured"] is False
        assert "never" in payload["unset_secret_means"]

    def test_a_verified_webhook_may_only_ask_read_only_things(self, client):
        payload = client.get("/api/v1/integrations/webhooks").json()

        assert set(payload["verified_webhooks_may"]) == set(notify.READ_ONLY_COMMANDS)


class TestSecurityPosture:
    def test_it_reads_the_live_router_table(self, client):
        payload = client.get("/api/v1/integrations/security").json()

        # One mutating route exists now: the broker link. The claim worth
        # holding is not that the list is empty - it is that the ungated list
        # is, which is the one the gate refuses to boot on.
        assert payload["routes"]["ungated"] == []
        assert payload["routes"]["mutating"] == ["POST /api/v1/brokers/link"]
        assert payload["routes"]["ungated"] == []

    def test_anonymous_holds_read_only(self, client):
        payload = client.get("/api/v1/integrations/security").json()

        assert payload["anonymous_holds"] == ["read"]

    def test_every_role_is_published_with_its_permissions(self, client):
        roles = client.get("/api/v1/integrations/security").json()["roles"]

        assert roles["viewer"] == ["read"]
        assert "execute" in roles["trader"]
        assert "execute" not in roles["analyst"]

    def test_the_gate_is_described_as_running_at_import(self, client):
        """Not at first request. A hole that appears under load is one that
        ships."""
        gate = client.get("/api/v1/integrations/security").json()["gate"]

        assert "import time" in gate["checked_at"]
        assert "refuses to start" in gate["refuses_to_start_if"] or gate["refuses_to_start_if"]

    def test_auth_being_off_is_explained_rather_than_hidden(self, client):
        payload = client.get("/api/v1/integrations/security").json()

        assert payload["require_auth"] is False
        assert "refuses to start" in payload["note"]

    def test_non_read_permissions_always_need_authentication(self, client):
        payload = client.get("/api/v1/integrations/security").json()

        assert payload["non_read_permissions_require_authentication"] is True


class TestTheGateStillHolds:
    def test_no_route_added_by_this_chapter_mutates(self, client):
        from app.api.guard import find_ungated_routes
        from app.main import app

        # Not "there are no mutating routes" - there is one now, and the
        # gate was built for exactly that. What must stay true is that
        # every one of them is gated.
        assert find_ungated_routes(app, require_auth=False) == []
