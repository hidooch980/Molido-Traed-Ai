"""Who did what, from where, and whether it worked.

The question after a scare is *did anybody get in, and what did they touch?*
Three pieces of it existed and none were joined: `login_attempts` knew about
passwords and nothing else, `audit_events` knew about ingestion runs and had no
idea who called, and the permission layer refused things leaving no trace at
all.

Two properties carry these tests, and both are the kind that pass silently
while being false:

**A refusal must survive the exception that caused it.** A permission denial is
raised, and the raise is what discards the transaction the record would have
been written in. The same trap the sign-in limiter fell into, one layer up.

**A log must not become a place credentials end up.** Every caller passes a
dict through from somewhere else, and none of them are checking what is in it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import ROLE_PERMISSIONS, Principal, resolve_principal
from app.core.enums import AuditEventType, Permission, Severity, UserRole
from app.core.security import hash_password
from app.models.audit import AuditEvent
from app.models.tenancy import Tenant, User
from app.services import login_guard, security_log

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
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
def as_role(session):
    from app.db.session import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: session

    def sign_in(role: UserRole) -> TestClient:
        app.dependency_overrides[resolve_principal] = lambda: Principal(
            tenant_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            role=role,
            permissions=frozenset(ROLE_PERMISSIONS[role]),
            authenticated=True,
        )
        return TestClient(app)

    yield sign_in
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


def events(session, kind: AuditEventType | None = None) -> list[AuditEvent]:
    statement = select(AuditEvent).order_by(AuditEvent.occurred_at)
    rows = list(session.scalars(statement))
    return [r for r in rows if kind is None or r.event_type == str(kind)]


class TestNothingSecretIsEverWritten:
    """Every caller passes a dict through from somewhere else and none of them
    are looking inside it. So the log checks rather than trusts."""

    @pytest.mark.parametrize(
        "field",
        ["password", "new_password", "api_token", "session_cookie", "client_secret", "key_hash"],
    )
    def test_a_credential_shaped_field_is_withheld(self, session, field):
        security_log.record(
            session,
            AuditEventType.SIGN_IN_FAILED,
            summary="test",
            detail={field: "hunter2-the-actual-secret"},
        )

        stored = str(events(session)[0].payload)

        assert "hunter2" not in stored
        assert "withheld" in stored

    def test_it_says_a_field_was_withheld_rather_than_dropping_it(self, session):
        """A reader has to be able to tell "nothing was passed" from
        "something was passed and refused"."""
        security_log.record(
            session, AuditEventType.SIGN_IN_FAILED, summary="t", detail={"password": "x"}
        )

        assert "password" in events(session)[0].payload

    def test_ordinary_fields_pass_through(self, session):
        security_log.record(
            session, AuditEventType.SIGN_IN_FAILED, summary="t", detail={"path": "/api/v1/users"}
        )

        assert events(session)[0].payload["path"] == "/api/v1/users"


class TestRecordingNeverBreaksTheThingItRecords:
    """A log that can fail a sign-in is a log that takes the deployment down
    the first time the disk fills, and the failure it causes is never the one
    it was written to catch."""

    def test_a_broken_write_returns_none_instead_of_raising(self, session, monkeypatch):
        def explode(*_args, **_kwargs):
            raise RuntimeError("the disk is full")

        monkeypatch.setattr(security_log.audit, "record", explode)

        assert (
            security_log.record(session, AuditEventType.SIGN_IN_FAILED, summary="t") is None
        )

    def test_the_isolated_writer_is_silent_when_there_is_no_database(self, monkeypatch):
        """It is called from an exception handler. One that raises replaces a
        403 the caller can act on with a 500 nobody can."""
        import app.db.session as db

        monkeypatch.setattr(db, "session_scope", lambda: (_ for _ in ()).throw(RuntimeError("no db")))

        security_log.record_isolated(AuditEventType.PERMISSION_DENIED, summary="t")


class TestSeverity:
    def test_the_alarming_ones_are_marked(self, session):
        security_log.record(session, AuditEventType.PERMISSION_DENIED, summary="t")

        assert events(session)[0].severity == Severity.WARNING

    def test_the_ordinary_ones_are_not(self, session):
        security_log.record(session, AuditEventType.SIGN_IN_SUCCEEDED, summary="t")

        assert events(session)[0].severity == Severity.INFO

    def test_releasing_a_halt_is_alarming_and_engaging_one_is_not(self):
        """Stopping moves toward safety; starting moves away from it. The log
        should raise its voice for exactly one of them."""
        assert AuditEventType.KILL_SWITCH_RELEASED in security_log.ALARMING
        assert AuditEventType.KILL_SWITCH_ENGAGED not in security_log.ALARMING


class TestSigningInLeavesATrail:
    def test_a_failure_is_recorded_and_survives_the_rollback(self, client, session, owner):
        client.post(
            "/api/v1/session/sign-in", json={"email": EMAIL, "password": "wrong"}
        )

        rows = events(session, AuditEventType.SIGN_IN_FAILED)

        assert len(rows) == 1
        assert rows[0].payload["subject"] == EMAIL

    def test_a_success_names_the_account_and_the_role(self, client, session, owner):
        client.post(
            "/api/v1/session/sign-in", json={"email": EMAIL, "password": PASSWORD}
        )

        row = events(session, AuditEventType.SIGN_IN_SUCCEEDED)[0]

        assert row.payload["role"] == "owner"
        assert row.user_id == owner.id

    def test_a_throttled_attempt_is_its_own_event(self, client, session, owner):
        """Not a failure. It says nothing about whether the password was
        right, and counting it among the failures overstates how close
        anybody got."""
        for _ in range(login_guard.SUBJECT_THRESHOLD + 1):
            client.post(
                "/api/v1/session/sign-in", json={"email": EMAIL, "password": "wrong"}
            )

        assert events(session, AuditEventType.SIGN_IN_THROTTLED)

    def test_the_password_is_nowhere_in_the_trail(self, client, session, owner):
        client.post(
            "/api/v1/session/sign-in", json={"email": EMAIL, "password": "hunter2-secret"}
        )

        stored = " ".join(str(r.payload) for r in events(session))

        assert "hunter2" not in stored


class TestARefusedPermissionIsRecorded:
    """The record has to be written on a session of its own. `require()`
    refuses by raising, and the raise is what discards the transaction that
    would have carried the record of it."""

    def test_a_denial_reaches_the_log(self, as_role, session, monkeypatch):
        written: list[tuple] = []
        monkeypatch.setattr(
            security_log,
            "record_isolated",
            lambda event, **kw: written.append((event, kw)),
        )

        response = as_role(UserRole.VIEWER).post(
            "/api/v1/users",
            json={"email": "x@y.z", "password": "a-long-enough-password", "role": "viewer"},
        )

        assert response.status_code in (401, 403)
        assert written
        assert written[0][0] is AuditEventType.PERMISSION_DENIED

    def test_it_records_the_path_and_the_role_that_was_refused(self, as_role, monkeypatch):
        written: list[tuple] = []
        monkeypatch.setattr(
            security_log,
            "record_isolated",
            lambda event, **kw: written.append((event, kw)),
        )

        as_role(UserRole.ANALYST).post(
            "/api/v1/brokers/link",
            json={"login": "1", "server": "s", "password": "p"},
        )

        detail = written[0][1]["detail"]
        assert detail["path"] == "/api/v1/brokers/link"
        assert detail["role"] == "analyst"

    def test_an_allowed_call_records_nothing(self, as_role, monkeypatch):
        written: list = []
        monkeypatch.setattr(
            security_log, "record_isolated", lambda event, **kw: written.append(event)
        )

        as_role(UserRole.VIEWER).get("/api/v1/access/roles")

        assert written == []


class TestReadingTheTimeline:
    def test_it_needs_its_own_permission(self, as_role, session):
        """Not part of READ. The log carries the addresses somebody signed in
        from and every account name an attacker has tried."""
        for role in (UserRole.VIEWER, UserRole.ANALYST, UserRole.TRADER):
            assert as_role(role).get("/api/v1/security/events").status_code in (401, 403)

    def test_the_administrative_roles_can_read_it(self, as_role, session):
        for role in (UserRole.OWNER, UserRole.ADMIN):
            assert as_role(role).get("/api/v1/security/events").status_code == 200

    def test_the_roles_that_can_read_it_are_the_ones_holding_the_permission(self, as_role):
        allowed = {
            role
            for role in UserRole
            if as_role(role).get("/api/v1/security/events").status_code == 200
        }
        holders = {r for r, p in ROLE_PERMISSIONS.items() if Permission.AUDIT_READ in p}

        assert allowed == holders

    def test_it_returns_what_was_recorded(self, as_role, session):
        security_log.record(
            session,
            AuditEventType.SIGN_IN_FAILED,
            summary="a failure worth seeing",
            subject="someone@example.test",
            address="203.0.113.7",
        )

        body = as_role(UserRole.OWNER).get("/api/v1/security/events").json()

        assert body["count"] == 1
        assert body["events"][0]["subject"] == "someone@example.test"
        assert body["events"][0]["address"] == "203.0.113.7"

    def test_an_unknown_event_filter_returns_nothing_rather_than_everything(
        self, as_role, session
    ):
        """Silently ignoring a filter is how a reader concludes there were no
        failed sign-ins when they had simply mistyped the name."""
        security_log.record(session, AuditEventType.SIGN_IN_FAILED, summary="t")

        body = as_role(UserRole.OWNER).get(
            "/api/v1/security/events", params={"event": "auth.sign_in.faled"}
        ).json()

        assert body["count"] == 0

    def test_the_window_is_bounded_by_default(self, as_role, session):
        body = as_role(UserRole.OWNER).get("/api/v1/security/events").json()

        assert body["window_hours"] == 168

    def test_the_summary_counts_without_concluding(self, as_role, session):
        for n in range(3):
            security_log.record(
                session,
                AuditEventType.SIGN_IN_FAILED,
                summary="t",
                subject=f"a{n}@example.test",
                address="203.0.113.7",
            )

        summary = as_role(UserRole.OWNER).get("/api/v1/security/events").json()["summary"]

        assert summary["sign_ins"]["failed"] == 3
        assert summary["distinct_addresses"] == 1
        assert summary["distinct_accounts_named"] == 3
        assert "not conclusions" in summary["note"]


class TestTheLockoutIsQueryable:
    """The question an owner actually has when they cannot sign in: am I
    locked out, and for how long?"""

    def test_it_reports_a_clean_account_as_allowed(self, as_role, session):
        body = as_role(UserRole.OWNER).get(
            "/api/v1/security/sign-in-pressure", params={"email": EMAIL}
        ).json()

        assert body["allowed"] is True
        assert body["retry_after_seconds"] == 0

    def test_it_reports_the_wait_after_failures(self, as_role, session):
        for step in range(login_guard.SUBJECT_THRESHOLD):
            login_guard.record(
                session,
                email=EMAIL,
                address=None,
                succeeded=False,
                now=datetime.now(UTC) - timedelta(seconds=step),
            )

        body = as_role(UserRole.OWNER).get(
            "/api/v1/security/sign-in-pressure", params={"email": EMAIL}
        ).json()

        assert body["allowed"] is False
        assert body["retry_after_seconds"] > 0

    def test_it_publishes_the_thresholds_it_is_enforcing(self, as_role, session):
        body = as_role(UserRole.OWNER).get("/api/v1/security/sign-in-pressure").json()

        assert (
            body["thresholds"]["subject_failures_before_waiting"]
            == login_guard.SUBJECT_THRESHOLD
        )
        assert body["thresholds"]["longest_account_wait_seconds"] <= 900
