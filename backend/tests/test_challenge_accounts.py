"""Challenge accounts, and the confirmation that makes their rules usable.

Every transcribed rulebook carries `confirmed_by_holder: false`, and that flag
gates a real feature rather than decorating the payload: challenge tracking
stays shut until somebody checks the numbers against their own contract.
Tracking an account against unverified rules produces a confident verdict about
the wrong document, which is worse than no verdict.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.brain import rulebooks as rulebook_module
from app.core.errors import ValidationFailedError
from app.services import challenge_accounts

KEY = rulebook_module.RULEBOOKS[0].key


@pytest.fixture()
def client(session):
    from app.db.session import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def make(session, **overrides):
    payload = {
        "tenant_id": challenge_accounts.default_tenant(session),
        "label": "FundedNext 100k",
        "rulebook_key": KEY,
        "starting_balance": Decimal("100000"),
    }
    payload.update(overrides)
    return challenge_accounts.create(session, **payload)


class TestRecordingAnAccount:
    def test_an_unconfirmed_account_is_stored_rather_than_refused(self, session):
        """Somebody part-way through setup has a real account with rules nobody
        has checked. Refusing the row would lose a true fact; storing it as
        confirmed would invent one."""
        account = make(session)

        assert account.rules_confirmed is False
        assert account.confirmed_at is None

    def test_an_unconfirmed_account_cannot_be_tracked(self, session):
        view = challenge_accounts.AccountView(
            account=make(session), rulebook=challenge_accounts._resolve(KEY)
        )

        assert view.as_dict()["tracking_available"] is False
        assert "wrong document" in view.as_dict()["why_not"]

    def test_confirming_opens_tracking(self, session):
        account = make(session)

        challenge_accounts.confirm(
            session, tenant_id=challenge_accounts.default_tenant(session), account_id=account.id, notes="matches my contract"
        )

        view = challenge_accounts.AccountView(
            account=account, rulebook=challenge_accounts._resolve(KEY)
        )
        assert view.as_dict()["tracking_available"] is True
        assert account.confirmed_at is not None

    def test_an_unknown_rulebook_is_refused_with_the_known_keys(self, session):
        """A silent accept would produce an account measured against nothing,
        and the reader would have no way to see which key was wrong."""
        with pytest.raises(ValidationFailedError) as exc:
            make(session, rulebook_key="fundednext-stellar-42step")

        assert KEY in str(exc.value)

    def test_a_balance_below_the_floor_is_refused(self, session):
        """Under a hundred units a percentage drawdown rounds to nothing and
        every headroom figure is zero, which blocks correctly and uselessly."""
        with pytest.raises(ValidationFailedError):
            make(session, starting_balance=Decimal("5"))

    def test_a_duplicate_label_is_refused(self, session):
        make(session)

        with pytest.raises(ValidationFailedError):
            make(session)

    def test_two_accounts_on_one_rulebook_are_allowed(self, session):
        """Two accounts on the same program is the ordinary case, and each one
        confirms separately."""
        make(session, label="first")
        second = make(session, label="second")

        assert second.rulebook_key == KEY


class TestConfirmationIsPerAccount:
    def test_confirming_one_does_not_confirm_the_other(self, session):
        """Providers change terms and honour the old ones for accounts already
        open, so two holders on one program can be on different contracts."""
        first = make(session, label="first")
        second = make(session, label="second")

        challenge_accounts.confirm(session, tenant_id=challenge_accounts.default_tenant(session), account_id=first.id)

        assert first.rules_confirmed is True
        assert second.rules_confirmed is False

    def test_the_transcription_itself_stays_unconfirmed(self, session):
        """Confirming an account says nothing about the published page it was
        read from, which is still a page nobody's contract."""
        account = make(session)
        challenge_accounts.confirm(session, tenant_id=challenge_accounts.default_tenant(session), account_id=account.id)

        book = challenge_accounts._resolve(KEY)

        assert book.confirmed_by_holder is False


class TestTheSummarySplitsReadiness:
    def test_confirmed_and_unconfirmed_are_counted_apart(self, session):
        """One total would let an account nobody verified pad the number that
        suggests the system is set up."""
        first = make(session, label="first")
        make(session, label="second")
        challenge_accounts.confirm(session, tenant_id=challenge_accounts.default_tenant(session), account_id=first.id)

        summary = challenge_accounts.summary(session, tenant_id=challenge_accounts.default_tenant(session))

        assert summary["total"] == 2
        assert summary["confirmed"] == 1
        assert summary["unconfirmed"] == 1
        assert summary["trackable"] == 1

    def test_an_empty_deployment_reports_zero_rather_than_nothing(self, session):
        summary = challenge_accounts.summary(session, tenant_id=challenge_accounts.default_tenant(session))

        assert summary["total"] == 0
        assert summary["accounts"] == []


class TestOverHttp:
    def test_creating_requires_more_than_read(self, client):
        """The route carries SIMULATE, which `require()` refuses for an
        anonymous caller whether or not authentication is switched on."""
        response = client.post(
            "/api/v1/risk/challenge-accounts",
            json={
                "label": "anonymous attempt",
                "rulebook_key": KEY,
                "starting_balance": "100000",
            },
        )

        assert response.status_code in (401, 403)

    def test_listing_is_readable_without_a_key(self, client):
        response = client.get("/api/v1/risk/challenge-accounts")

        assert response.status_code == 200
        assert response.json()["total"] == 0

    def test_the_gate_covers_both_new_routes(self, client):
        from app.api.guard import find_ungated_routes, mutating_routes
        from app.main import app

        paths = {path for path, _ in mutating_routes(app)}

        assert "/api/v1/risk/challenge-accounts" in paths
        assert find_ungated_routes(app, require_auth=False) == []
