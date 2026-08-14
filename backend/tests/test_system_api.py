"""System settings endpoint (spec §68).

One route, and most of these tests are about a single property: secrets are
absent by design, not deleted at the edge. The redaction test greps the whole
serialised response for the credential shapes rather than checking named
fields, because the failure this guards against is a *new* secret that nobody
added to a blocklist.
"""

from __future__ import annotations

import json

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


class TestNoSecretEverLeavesTheProcess:
    def test_the_database_credentials_are_not_in_the_response(self, client, monkeypatch):
        """Grep the whole body, not named fields: a blocklist of dangerous keys
        has to anticipate every secret somebody adds later."""
        from app.core import config

        config.get_settings.cache_clear()
        monkeypatch.setenv(
            "MOLIDO_DATABASE_URL",
            "postgresql+psycopg://molido:hunter2-secret@dbhost:5432/molidotrade",
        )
        try:
            body = json.dumps(client.get("/api/v1/system/settings").json())
        finally:
            config.get_settings.cache_clear()

        assert "hunter2-secret" not in body
        assert "molido:hunter2" not in body
        assert "***@dbhost" in body  # the redacted form is what remains

    def test_the_redis_dsn_is_redacted_the_same_way(self, client, monkeypatch):
        from app.core import config

        config.get_settings.cache_clear()
        monkeypatch.setenv("MOLIDO_REDIS_URL", "redis://:redispass@cache:6379/0")
        try:
            body = json.dumps(client.get("/api/v1/system/settings").json())
        finally:
            config.get_settings.cache_clear()

        assert "redispass" not in body

    def test_the_provider_mapping_stays_out_of_the_payload(self, client):
        """Symbols only. `EURUSD=X` is ingestion's business, not the page's."""
        collector = client.get("/api/v1/system/settings").json()["collector"]

        assert all("=" not in s and ":" not in s for s in collector["symbols"])


class TestReportingIsNotConfiguring:
    def test_there_is_no_write_method(self, client):
        for method in ("post", "put", "patch", "delete"):
            response = getattr(client, method)("/api/v1/system/settings")
            assert response.status_code == 405, method

    def test_the_response_says_so(self, client):
        payload = client.get("/api/v1/system/settings").json()

        assert payload["read_only"] is True
        assert "offers no way to write" in payload["note"]


class TestTheShape:
    def test_the_execution_switches_are_reported(self, client):
        execution = client.get("/api/v1/system/settings").json()["execution"]

        assert execution["enabled"] is False
        assert execution["dry_run"] is True

    def test_every_retention_policy_carries_its_reason(self, client):
        policies = client.get("/api/v1/system/settings").json()["retention"]

        assert len(policies) >= 3
        assert all(p["reason"] for p in policies)
        assert all(p["protect_reason"] for p in policies if p["protected"])

    def test_the_collector_watchlist_is_summarised(self, client):
        collector = client.get("/api/v1/system/settings").json()["collector"]

        assert collector["watchlist_size"] >= 1
        assert collector["interval_seconds"] > 0

    def test_the_gate_still_holds(self, client):
        from app.api.guard import find_ungated_routes
        from app.main import app

        # Not "there are no mutating routes" - there is one now, and the
        # gate was built for exactly that. What must stay true is that
        # every one of them is gated.
        assert find_ungated_routes(app, require_auth=False) == []
