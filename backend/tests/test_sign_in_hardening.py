"""Sign-in with the limiter and the proof of work actually wired in.

`test_login_guard` and `test_human_check` prove the two mechanisms work.
These prove the route uses them, which is a different claim and the one that
was false: both could be perfect and the route could call neither.

The load-bearing test here is `test_a_failed_attempt_survives_the_rollback`.
`get_db` rolls back on any exception, and a failed sign-in raises one - so the
record of the failure would have been rolled back by the failure it recorded.
A limiter counting rows that are deleted by the thing it counts counts nothing,
forever, and reports no error while doing it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.enums import UserRole
from app.core.security import hash_password
from app.models.login_attempts import LoginAttempt
from app.models.tenancy import Tenant, User
from app.services import human_check, login_guard

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
        role=UserRole.OWNER,
        password_hash=hash_password(PASSWORD),
        is_active=True,
    )
    session.add(user)
    session.flush()
    return user


def attempt(client, *, password="wrong", email=EMAIL, **extra):
    return client.post(
        "/api/v1/session/sign-in",
        json={"email": email, "password": password, **extra},
    )


def solved(client, session, *, email=EMAIL):
    """A challenge for the sign-in form, solved."""
    payload = client.get("/api/v1/session/challenge", params={"email": email}).json()
    nonce = human_check.solve(payload["salt"], payload["difficulty"])
    return {"challenge_id": payload["challenge_id"], "nonce": nonce}


def failures(session, email=EMAIL) -> int:
    return session.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(LoginAttempt.subject == email)
        .where(LoginAttempt.succeeded.is_(False))
    )


class TestTheAttemptIsRecorded:
    def test_a_failed_attempt_survives_the_rollback(self, client, session, owner):
        """The whole module in one assertion. `get_db` rolls back on the
        exception a failed sign-in raises, so without an explicit commit the
        failure record is destroyed by the failure it records - and the
        limiter counts nothing, silently, for the life of the deployment."""
        assert attempt(client).status_code == 401

        assert failures(session) == 1

    def test_a_success_is_recorded_too(self, client, session, owner):
        response = attempt(client, password=PASSWORD)

        assert response.status_code == 200
        rows = session.scalars(
            select(LoginAttempt).where(LoginAttempt.succeeded.is_(True))
        ).all()
        assert len(rows) == 1
        assert rows[0].user_id == owner.id

    def test_no_password_reaches_the_row(self, client, session, owner):
        attempt(client, password="hunter2-is-the-password")

        rows = session.scalars(select(LoginAttempt)).all()
        stored = " ".join(str(v) for row in rows for v in vars(row).values())

        assert "hunter2" not in stored


class TestTheLimiterRefusesBeforeTheCheck:
    def test_enough_failures_produce_a_429(self, client, session, owner):
        for _ in range(login_guard.SUBJECT_THRESHOLD):
            attempt(client, **solved(client, session))

        blocked = attempt(client, **solved(client, session))

        assert blocked.status_code == 429

    def test_the_refusal_says_when_to_come_back(self, client, session, owner):
        for _ in range(login_guard.SUBJECT_THRESHOLD):
            attempt(client, **solved(client, session))

        body = attempt(client, **solved(client, session)).json()

        assert body["context"]["retry_after_seconds"] > 0

    def test_the_right_password_is_refused_too_while_cooling_down(
        self, client, session, owner
    ):
        """It refuses before the password is read. A limiter that lets the
        correct password through has not limited the guessing, it has limited
        the reporting of it."""
        for _ in range(login_guard.SUBJECT_THRESHOLD):
            attempt(client, **solved(client, session))

        assert attempt(client, password=PASSWORD, **solved(client, session)).status_code == 429


class TestTheProofOfWork:
    def test_the_first_attempt_needs_none(self, client, session, owner):
        assert attempt(client, password=PASSWORD).status_code == 200

    def test_it_becomes_required_after_a_few_failures(self, client, session, owner):
        for _ in range(login_guard.HUMAN_CHECK_AFTER):
            attempt(client)

        refused = attempt(client, password=PASSWORD)

        assert refused.status_code == 400
        assert refused.json()["error"] == "human_check_failed"

    def test_a_solved_challenge_lets_the_password_through(self, client, session, owner):
        for _ in range(login_guard.HUMAN_CHECK_AFTER):
            attempt(client)

        response = attempt(client, password=PASSWORD, **solved(client, session))

        assert response.status_code == 200

    def test_skipping_the_proof_still_counts_as_an_attempt(self, client, session, owner):
        """Otherwise a loop that never sends a proof resets nothing and tries
        forever: only attempts that reach the password check would count."""
        for _ in range(login_guard.HUMAN_CHECK_AFTER):
            attempt(client)
        before = failures(session)

        attempt(client, password=PASSWORD)

        assert failures(session) == before + 1

    def test_the_same_proof_cannot_be_replayed(self, client, session, owner):
        for _ in range(login_guard.HUMAN_CHECK_AFTER):
            attempt(client)
        proof = solved(client, session)

        first = attempt(client, password="still-wrong", **proof)
        second = attempt(client, password=PASSWORD, **proof)

        assert first.status_code == 401
        assert second.status_code == 400


class TestTheChallengeEndpoint:
    def test_it_is_reachable_without_signing_in(self, client, session):
        """It has to be. A proof required to sign in that requires signing in
        to obtain is a door that needs a key to reach the key."""
        assert client.get("/api/v1/session/challenge").status_code == 200

    def test_it_says_whether_it_is_required_yet(self, client, session, owner):
        assert client.get(
            "/api/v1/session/challenge", params={"email": EMAIL}
        ).json()["required"] is False

        for _ in range(login_guard.HUMAN_CHECK_AFTER):
            attempt(client)

        assert client.get(
            "/api/v1/session/challenge", params={"email": EMAIL}
        ).json()["required"] is True

    def test_the_difficulty_rises_with_failures(self, client, session, owner):
        easy = client.get("/api/v1/session/challenge", params={"email": EMAIL}).json()

        for _ in range(login_guard.HUMAN_CHECK_AFTER * 2):
            attempt(client)

        harder = client.get("/api/v1/session/challenge", params={"email": EMAIL}).json()

        assert harder["difficulty"] > easy["difficulty"]

    def test_two_calls_are_two_challenges(self, client, session):
        first = client.get("/api/v1/session/challenge").json()
        second = client.get("/api/v1/session/challenge").json()

        assert first["challenge_id"] != second["challenge_id"]


class TestSucceedingClearsTheLadder:
    def test_the_next_mistake_starts_from_zero(self, client, session, owner):
        for _ in range(login_guard.SUBJECT_THRESHOLD - 1):
            attempt(client)

        assert attempt(client, password=PASSWORD, **solved(client, session)).status_code == 200
        assert failures(session) == 0


class TestAForgeableAddressIsNotUsed:
    def test_x_forwarded_for_is_ignored_with_no_proxy_configured(
        self, client, session, owner
    ):
        """The default. A limiter that believed this header would let an
        attacker present a fresh address on every request - which is the same
        as having no address rule, while looking exactly like having one."""
        client.post(
            "/api/v1/session/sign-in",
            json={"email": EMAIL, "password": "wrong"},
            headers={"X-Forwarded-For": "198.51.100.9"},
        )

        rows = session.scalars(select(LoginAttempt)).all()

        assert rows[0].address != "198.51.100.9"
