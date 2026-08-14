"""Signing in, and the one exemption the execution gate now carries.

The gate refused to start with `POST /session/sign-in` on the table, and it was
right to: the route changes state and requires only READ, which anonymous
already holds. But sign-in cannot require more - a door that needs a key to
reach the key is not a door.

So the rule gained an exception, and an exception to a safety gate is dangerous
in proportion to how quiet it is. These tests are what keeps it loud: it must be
claimed by name, it must carry a written reason, it must appear in a list
anybody can read, and nothing else may drift into it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.guard import (
    PUBLIC_MUTATION_ATTR,
    find_ungated_routes,
    mutating_routes,
    public_mutation,
    public_mutations,
)
from app.core.enums import UserRole
from app.core.security import hash_password
from app.models.tenancy import Tenant, User
from app.services import sessions_auth

PASSWORD = "a-password-nobody-else-knows"
EMAIL = "owner@molidotrade.local"


@pytest.fixture()
def client(session):
    from app.db.session import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
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
        role=UserRole.TRADER,
        password_hash=hash_password(PASSWORD),
        is_active=True,
    )
    session.add(user)
    session.flush()
    return user


class TestTheExemptionStaysNarrow:
    def test_the_app_starts_at_all(self, client):
        """It did not, until the exemption existed. That refusal was correct
        and is the reason this file is here."""
        assert client.get("/api/v1/session/me").status_code == 200

    def test_nothing_is_ungated(self, client):
        from app.main import app

        assert find_ungated_routes(app, require_auth=False) == []

    def test_only_these_four_routes_claim_it(self, client):
        """The list is asserted exactly. A new public mutation fails this test
        and makes somebody justify it, which is the entire mechanism.

        Four, and each one is public because requiring a session to reach it
        would require a session that cannot exist yet:

          sign-in / sign-out  the session itself
          users/claim         the first owner of a deployment nobody can sign
                              in to, and refused with 409 forever after
          users/register      self sign-up, which lands as a viewer and can
                              reach nothing that moves money

        The fourth is the one to watch. It is safe only while a viewer holds
        READ and nothing more, which `test_a_viewer_cannot_reach_anything_that_
        moves_money` asserts separately - if that ever changes, an open
        registration form becomes a way in to the broker connection.
        """
        from app.main import app

        claimed = {path for path, _ in public_mutations(app)}

        assert claimed == {
            "/api/v1/session/sign-in",
            "/api/v1/session/sign-out",
            "/api/v1/users/claim",
            "/api/v1/users/register",
        }

    def test_every_claim_carries_a_reason(self, client):
        from app.main import app

        assert all(len(reason) >= 20 for _, reason in public_mutations(app))

    def test_a_reason_is_required_to_claim_it(self):
        """An exemption with an empty reason is an exemption nobody will
        re-examine."""
        with pytest.raises(ValueError):
            public_mutation("")

        with pytest.raises(ValueError):
            public_mutation("because")

    def test_the_marker_cannot_be_inferred(self):
        """A plain function does not carry it. Nothing derives this from a path
        name, an HTTP method or a module - it is set or it is not."""

        def handler():
            return None

        assert getattr(handler, PUBLIC_MUTATION_ATTR, None) is None

    def test_the_other_mutating_routes_still_need_more_than_read(self, client):
        """The exemption did not soften the rule for anything else."""
        from app.main import app

        exempt = {path for path, _ in public_mutations(app)}
        others = {path for path, _ in mutating_routes(app)} - exempt

        assert others
        for path in others:
            response = client.post(path.replace("{account_id}", "x"), json={})
            assert response.status_code != 200


class TestSigningIn:
    def test_a_correct_password_sets_a_cookie(self, client, owner):
        response = client.post(
            "/api/v1/session/sign-in", json={"email": EMAIL, "password": PASSWORD}
        )

        assert response.status_code == 200
        assert response.json()["signed_in"] is True
        assert sessions_auth.COOKIE_NAME in response.cookies

    def test_the_cookie_authenticates_afterwards(self, client, owner):
        client.post("/api/v1/session/sign-in", json={"email": EMAIL, "password": PASSWORD})

        me = client.get("/api/v1/session/me").json()

        assert me["authenticated"] is True
        assert me["can_change_state"] is True

    def test_an_anonymous_caller_holds_read_only(self, client):
        me = client.get("/api/v1/session/me").json()

        assert me["authenticated"] is False
        assert me["permissions"] == ["read"]
        assert me["can_change_state"] is False

    def test_a_wrong_password_is_refused(self, client, owner):
        response = client.post(
            "/api/v1/session/sign-in", json={"email": EMAIL, "password": "not it"}
        )

        assert response.status_code in (401, 403)

    def test_an_unknown_address_fails_identically(self, client, owner):
        """Different messages would tell an attacker which half of the guess was
        right."""
        wrong_password = client.post(
            "/api/v1/session/sign-in", json={"email": EMAIL, "password": "not it"}
        )
        wrong_email = client.post(
            "/api/v1/session/sign-in",
            json={"email": "nobody@example.com", "password": PASSWORD},
        )

        assert wrong_password.status_code == wrong_email.status_code
        assert wrong_password.json() == wrong_email.json()

    def test_a_disabled_account_fails_identically(self, client, owner, session):
        owner.is_active = False
        session.flush()

        response = client.post(
            "/api/v1/session/sign-in", json={"email": EMAIL, "password": PASSWORD}
        )

        assert response.status_code in (401, 403)


class TestSigningOut:
    def test_the_session_is_revoked_not_just_forgotten(self, client, owner, session):
        """Clearing only the cookie would leave a token that still works for
        anybody who kept a copy, which is the opposite of pressing sign-out."""
        client.post("/api/v1/session/sign-in", json={"email": EMAIL, "password": PASSWORD})
        token = client.cookies[sessions_auth.COOKIE_NAME]

        client.post("/api/v1/session/sign-out")

        assert sessions_auth.resolve(session, token) is None

    def test_signing_out_without_a_session_is_not_an_error(self, client):
        response = client.post("/api/v1/session/sign-out")

        assert response.status_code == 200
        assert response.json()["session_revoked"] is False


class TestExpiry:
    def test_an_expired_session_stops_authenticating(self, session, owner):
        from datetime import timedelta

        result = sessions_auth.sign_in(session, email=EMAIL, password=PASSWORD)
        later = result.expires_at + timedelta(seconds=1)

        assert sessions_auth.resolve(session, result.token, now=later) is None

    def test_pruning_removes_only_the_dead(self, session, owner):
        from datetime import timedelta

        live = sessions_auth.sign_in(session, email=EMAIL, password=PASSWORD)
        later = live.expires_at + timedelta(seconds=1)

        assert sessions_auth.prune(session, now=live.expires_at - timedelta(hours=1)) == 0
        assert sessions_auth.prune(session, now=later) == 1
