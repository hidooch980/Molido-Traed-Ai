"""What each role can actually reach, asked of the routes themselves.

`test_access_api` proves the published table matches the enforced one. This
proves the enforced one reaches the routes - which is a different claim, and
the one that was false. The permission model had three tiers, `OWNER`, `ADMIN`
and `TRADER` all held the same three, and every route that needed a finer
distinction wrote its own check in the handler. Those checks were correct and
invisible: nothing outside the module knew they existed, and a route added
without one looked exactly like a route with one.

So these are written per route and per role, against the HTTP layer, with a
principal injected at each of the five roles. A test that asked the table
instead would keep passing if a route's dependency were deleted tomorrow.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.deps import ROLE_PERMISSIONS, Principal, resolve_principal
from app.brain import rulebooks as rulebook_module
from app.core.enums import Permission, UserRole

KEY = rulebook_module.RULEBOOKS[0].key

#: The status codes `require()` produces when it refuses. Asserted as a pair
#: because which one is correct depends on whether the caller was
#: unauthenticated or merely unauthorised, and both are refusals.
REFUSED = (401, 403)


def principal_at(role: UserRole) -> Principal:
    """A signed-in caller at one role, holding exactly what that role holds."""
    return Principal(
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        role=role,
        permissions=frozenset(ROLE_PERMISSIONS[role]),
        authenticated=True,
    )


@pytest.fixture()
def as_role(session):
    """Drive the API as any role, one role at a time."""
    from app.db.session import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: session

    def sign_in(role: UserRole) -> TestClient:
        app.dependency_overrides[resolve_principal] = lambda: principal_at(role)
        return TestClient(app)

    yield sign_in
    app.dependency_overrides.clear()


def holders(permission: Permission) -> set[UserRole]:
    return {role for role, perms in ROLE_PERMISSIONS.items() if permission in perms}


class TestManagingAccounts:
    """Was SIMULATE plus a hand-written owner-or-admin check in the handler.
    The tier could not express it: trader and admin both held EXECUTE, and a
    trader must not be able to mint an admin."""

    def test_only_the_roles_that_hold_the_permission_may_create_a_user(self, as_role):
        allowed, refused = set(), set()
        for role in UserRole:
            response = as_role(role).post(
                "/api/v1/users",
                json={
                    "email": f"{role.value}@example.test",
                    "password": "a-long-enough-password",
                    "role": "viewer",
                },
            )
            (refused if response.status_code in REFUSED else allowed).add(role)

        assert refused == set(UserRole) - holders(Permission.USERS_MANAGE)
        assert allowed == holders(Permission.USERS_MANAGE)

    def test_a_trader_cannot_mint_an_admin(self, as_role):
        """The specific failure the old comment described, now enforced by the
        signature rather than by a check somebody has to remember to call."""
        response = as_role(UserRole.TRADER).post(
            "/api/v1/users",
            json={
                "email": "promoted@example.test",
                "password": "a-long-enough-password",
                "role": "admin",
            },
        )

        assert response.status_code in REFUSED

    def test_the_roster_is_not_readable_by_everyone_who_can_read(self, as_role):
        """Listing users was behind READ with the role check underneath it. A
        viewer reaching it would have seen every address on the deployment."""
        assert as_role(UserRole.VIEWER).get("/api/v1/users").status_code in REFUSED
        assert as_role(UserRole.ANALYST).get("/api/v1/users").status_code in REFUSED
        assert as_role(UserRole.OWNER).get("/api/v1/users").status_code == 200


class TestTranscribingARulebook:
    """A daily-loss limit typed one digit out does not fail - it passes a trade
    that ends the account. That is the holder's decision to get wrong."""

    def test_only_the_owner_may_record_a_challenge_account(self, as_role):
        allowed = set()
        for role in UserRole:
            response = as_role(role).post(
                "/api/v1/risk/challenge-accounts",
                json={
                    "label": f"{role.value} attempt",
                    "rulebook_key": KEY,
                    "starting_balance": "100000",
                },
            )
            if response.status_code not in REFUSED:
                allowed.add(role)

        assert allowed == {UserRole.OWNER}

    def test_an_admin_is_refused_too(self, as_role):
        """Deliberate. Administering the deployment is not the same authority
        as declaring the rules its trading is measured against."""
        response = as_role(UserRole.ADMIN).post(
            "/api/v1/risk/challenge-accounts",
            json={"label": "admin", "rulebook_key": KEY, "starting_balance": "100000"},
        )

        assert response.status_code in REFUSED


class TestConnectingABroker:
    """The point at which a deployment stops being a simulator."""

    def test_an_analyst_cannot_hand_over_a_broker_login(self, as_role):
        """Analyst holds SIMULATE, which used to be all this route asked for."""
        response = as_role(UserRole.ANALYST).post(
            "/api/v1/brokers/link",
            json={"login": "12345678", "server": "Broker-Demo", "password": "secret"},
        )

        assert response.status_code in REFUSED

    def test_the_roles_refused_are_the_ones_without_the_permission(self, as_role):
        refused = set()
        for role in UserRole:
            response = as_role(role).post(
                "/api/v1/brokers/link",
                json={"login": "12345678", "server": "Broker-Demo", "password": "x"},
            )
            if response.status_code in REFUSED:
                refused.add(role)

        assert refused == set(UserRole) - holders(Permission.BROKER_MANAGE)


class TestReadingStaysOpen:
    """The read-only deployment must keep working. Narrowing the mutating
    routes is worth nothing if it narrowed the readable ones by accident."""

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/access/roles",
            "/api/v1/access/matrix",
            "/api/v1/risk/challenge-accounts",
            "/api/v1/users/setup",
        ],
    )
    def test_every_role_can_still_read(self, as_role, path):
        for role in UserRole:
            assert as_role(role).get(path).status_code == 200, (role, path)
