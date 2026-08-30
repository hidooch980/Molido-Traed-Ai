"""What `MOLIDO_REQUIRE_AUTH=true` does, and the door it must not close.

The flag makes `resolve_principal` refuse every caller without a key or a
session. Applied without exception it closes the sign-in route too - and a
deployment with the flag on and nobody signed in can never be signed into
again. That failure is total, silent until somebody tries, and unfixable from
outside the machine.

This file is mostly about that one sentence. The rest is the other half: with
the flag on, everything that is not one of the seven bootstrap routes must
actually be refused, because a flag that reaches only the routes that declared
a dependency is the failure this deployment already had once - eighteen of
eighty-eight routes answering anonymously with the switch on.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.guard import BOOTSTRAP_PATHS, PUBLIC_PATHS, find_ungated_routes
from app.core.enums import UserRole
from app.core.security import hash_password
from app.models.tenancy import Tenant, User

PASSWORD = "a-password-nobody-else-knows"
EMAIL = "owner@molidotrade.local"


@pytest.fixture()
def locked(session, monkeypatch):
    """A deployment with the flag on, driven over HTTP."""
    from app.core.config import get_settings
    from app.db.session import get_db
    from app.main import app

    settings = get_settings()
    monkeypatch.setattr(settings, "require_auth", True, raising=False)
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture()
def owner(session):
    tenant = Tenant(slug="default", name="MolidoTrade", locale="fa")
    session.add(tenant)
    session.flush()
    user = User(
        tenant_id=tenant.id,
        email=EMAIL,
        display_name="owner",
        role=UserRole.OWNER,
        password_hash=hash_password(PASSWORD),
        is_active=True,
    )
    session.add(user)
    session.flush()
    return user


class TestTheDoorStaysOpen:
    """The one that matters. Everything else in this file is recoverable."""

    def test_a_locked_deployment_can_still_be_signed_into(self, locked, owner):
        response = locked.post(
            "/api/v1/session/sign-in", json={"email": EMAIL, "password": PASSWORD}
        )

        assert response.status_code == 200, response.text
        assert response.json()["signed_in"] is True

    def test_the_proof_of_work_can_still_be_obtained(self, locked):
        """It is demanded by the sign-in route, so a locked deployment that
        refused to issue one would refuse every sign-in that needed it."""
        assert locked.get("/api/v1/session/challenge").status_code == 200

    def test_whether_it_is_claimed_can_still_be_asked(self, locked):
        """The sign-in page decides between "claim this deployment" and "sign
        in" from this, before anybody could possibly be signed in."""
        assert locked.get("/api/v1/users/setup").status_code == 200

    def test_an_unclaimed_deployment_can_still_be_claimed(self, locked, session):
        """The worst case in the file: flag on, no account, no way in. If this
        ever fails the only repair is a shell on the server."""
        response = locked.post(
            "/api/v1/users/claim",
            json={"email": "first@molido.test", "password": "a-long-enough-password"},
        )

        assert response.status_code == 201, response.text

    def test_signing_out_works_without_a_live_session(self, locked):
        """Somebody whose cookie expired must still be able to press it."""
        assert locked.post("/api/v1/session/sign-out").status_code == 200


class TestEverythingElseIsRefused:
    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/instruments",
            "/api/v1/access/roles",
            "/api/v1/decisions/posture",
            "/api/v1/execution/autopilot",
            "/api/v1/security/events",
        ],
    )
    def test_a_read_needs_a_credential(self, locked, path):
        assert locked.get(path).status_code == 401

    def test_the_same_reads_are_open_when_the_flag_is_off(self, session):
        """So the test above is measuring the flag rather than a broken route."""
        from app.db.session import get_db
        from app.main import app

        app.dependency_overrides[get_db] = lambda: session
        with TestClient(app) as client:
            assert client.get("/api/v1/instruments").status_code == 200
        app.dependency_overrides.clear()


class TestTheProbesSurvive:
    """Docker asks these before anything is signed in, and a probe that needs a
    credential reports the credential's health rather than the service's."""

    @pytest.mark.parametrize("path", ["/health/live", "/health/ready"])
    def test_the_container_can_still_be_checked(self, locked, path):
        assert locked.get(path).status_code in (200, 503)


class TestTheGateAgrees:
    def test_no_route_is_left_answering_anonymously(self, session):
        """The failure this deployment already had: the flag was turned on and
        eighteen of eighty-eight routes kept answering, because it only reaches
        routes that declared a dependency and those never had."""
        from app.main import app

        assert find_ungated_routes(app, require_auth=True) == []

    def test_the_exemptions_are_a_short_written_list(self):
        """Both lists are named and defended in `api.guard`. This asserts they
        stay small - an exemption list that grows quietly is a flag that means
        less every release."""
        assert len(BOOTSTRAP_PATHS) <= 8
        assert len(PUBLIC_PATHS) <= 6

    def test_nothing_that_moves_money_is_exempt(self):
        for path in BOOTSTRAP_PATHS | PUBLIC_PATHS:
            assert "execution" not in path, path
            assert "broker" not in path, path
            assert "risk" not in path, path
