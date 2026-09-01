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
        """The route carries RULEBOOK_WRITE, which `require()` refuses for an
        anonymous caller whether or not authentication is switched on. Which
        role may reach it when signed in is `test_permissions`; this only says
        that nobody reaches it without signing in at all."""
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


class TestTheThreeKinds:
    """A challenge, a funded prop account, and the holder's own live account.

    They differ in one thing that matters here: who imposes the limits. The
    first two are measured against a document somebody else wrote and can be
    ended by it. The third cannot, so it has no rulebook - and the tests below
    are mostly about refusing to pretend otherwise.
    """

    def test_a_live_account_needs_no_rulebook(self, session):
        account = make(session, kind="live", rulebook_key=None, label="RoboForex live")

        assert account.kind == "live"
        assert account.rulebook_key is None

    def test_a_funded_account_still_needs_one(self, session):
        """Passing the evaluation retires the profit target, not the drawdown
        floor. A funded account is still measured against a document."""
        with pytest.raises(ValidationFailedError) as caught:
            make(session, kind="funded", rulebook_key=None, label="Funded no book")

        assert "rulebook" in str(caught.value).lower()

    def test_a_challenge_without_a_rulebook_is_still_refused(self, session):
        with pytest.raises(ValidationFailedError):
            make(session, rulebook_key=None, label="Challenge no book")

    def test_an_unknown_kind_is_refused_and_the_known_ones_are_named(self, session):
        with pytest.raises(ValidationFailedError) as caught:
            make(session, kind="demo", label="Demo")

        message = str(caught.value)
        assert "challenge" in message and "funded" in message and "live" in message

    def test_a_rulebook_sent_with_a_live_account_is_dropped(self, session):
        """A caller that sends both has misunderstood the kind. Storing the key
        would leave a row claiming a programme the holder is not on."""
        account = make(session, kind="live", rulebook_key=KEY, label="Live with book")

        assert account.rulebook_key is None

    def test_a_live_account_is_never_marked_confirmed_on_the_way_in(self, session):
        """"Yes, I checked the rules" is not a statement anybody can truthfully
        make about rules that were never written."""
        account = make(
            session, kind="live", rulebook_key=None, rules_confirmed=True, label="Live"
        )

        assert account.rules_confirmed is False


class TestALiveAccountIsNotAnUnfinishedOne:
    def test_it_says_why_it_is_not_tracked_and_the_reason_is_not_a_missing_step(
        self, session
    ):
        view = challenge_accounts.AccountView(
            account=make(session, kind="live", rulebook_key=None, label="Live"),
            rulebook=None,
        )
        payload = view.as_dict()

        assert payload["tracking_available"] is False
        # The distinction the whole feature turns on: nothing to do, rather
        # than something left undone.
        assert "no rulebook to measure it against" in payload["why_not"]
        assert "confirm" not in payload["why_not"]

    def test_confirming_one_is_refused(self, session):
        account = make(session, kind="live", rulebook_key=None, label="Live")

        with pytest.raises(ValidationFailedError) as caught:
            challenge_accounts.confirm(
                session,
                tenant_id=account.tenant_id,
                account_id=account.id,
            )

        assert "no rulebook" in str(caught.value).lower()

    def test_it_does_not_drag_down_the_confirmation_count(self, session):
        """A deployment with every prop account confirmed and one live account
        should not read as half-finished for a reason nobody can act on."""
        confirmed = make(session, label="Challenge", rules_confirmed=True)
        make(session, kind="live", rulebook_key=None, label="Live")

        totals = challenge_accounts.summary(session, tenant_id=confirmed.tenant_id)

        assert totals["total"] == 2
        assert totals["confirmed"] == 1
        assert totals["unconfirmed"] == 0
        assert totals["by_kind"] == {"challenge": 1, "funded": 0, "live": 1}


@pytest.fixture()
def holder(session):
    """A client carrying the account holder's authority.

    The routes below write, and writing needs `RULEBOOK_WRITE`, which belongs
    to the owner alone. Overriding the principal tests the route rather than
    the session store - the permission it resolves to is the same either way.
    """
    import uuid as uuid_module

    from app.api.deps import ROLE_PERMISSIONS, Principal, resolve_principal
    from app.core.enums import UserRole
    from app.db.session import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[resolve_principal] = lambda: Principal(
        tenant_id=uuid_module.uuid4(),
        user_id=uuid_module.uuid4(),
        role=UserRole.OWNER,
        permissions=frozenset(ROLE_PERMISSIONS[UserRole.OWNER]),
        authenticated=True,
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class TestOverTheApi:
    def test_the_endpoint_records_a_live_account(self, holder):
        response = holder.post(
            "/api/v1/risk/challenge-accounts",
            json={"label": "RoboForex live", "kind": "live", "starting_balance": 5000},
        )

        assert response.status_code == 200, response.text
        account = response.json()["account"]
        assert account["kind"] == "live"
        assert account["rulebook_key"] is None

    def test_a_caller_that_omits_the_kind_still_means_a_challenge(self, holder):
        """The endpoint could only ever record challenges before this column
        existed, so silence has to keep meaning what it meant."""
        response = holder.post(
            "/api/v1/risk/challenge-accounts",
            json={"label": "Old caller", "rulebook_key": KEY, "starting_balance": 100000},
        )

        assert response.status_code == 200, response.text
        assert response.json()["account"]["kind"] == "challenge"

    def test_a_funded_account_over_the_api_carries_its_rulebook(self, holder):
        response = holder.post(
            "/api/v1/risk/challenge-accounts",
            json={
                "label": "Funded 100k",
                "kind": "funded",
                "rulebook_key": KEY,
                "starting_balance": 100000,
            },
        )

        assert response.status_code == 200, response.text
        assert response.json()["account"]["kind"] == "funded"


class TestSwitchingAnAccountOff:
    """Off rather than deleted.

    A failed challenge, an account between funding rounds, one the holder has
    stepped away from - each is a real account with real history. Deleting the
    row would take the history with it, so the switch exists instead.
    """

    def test_an_account_starts_switched_on(self, session):
        assert make(session).is_active is True

    def test_switching_it_off_stops_it_being_tracked(self, session):
        account = make(session, rules_confirmed=True)
        assert challenge_accounts.AccountView(
            account=account, rulebook=challenge_accounts._resolve(KEY)
        ).as_dict()["tracking_available"] is True

        challenge_accounts.set_active(
            session,
            tenant_id=account.tenant_id,
            account_id=account.id,
            active=False,
        )

        view = challenge_accounts.AccountView(
            account=account, rulebook=challenge_accounts._resolve(KEY)
        ).as_dict()
        assert view["tracking_available"] is False
        assert "switched off" in view["why_not"]

    def test_being_off_outranks_every_other_reason(self, session):
        """An account paused mid-setup should say it is paused, not report the
        rulebook problem it had before. Otherwise somebody goes and fixes a
        rulebook for an account nobody is trading."""
        account = make(session, rules_confirmed=False)
        challenge_accounts.set_active(
            session, tenant_id=account.tenant_id, account_id=account.id, active=False
        )

        why = challenge_accounts.AccountView(
            account=account, rulebook=challenge_accounts._resolve(KEY)
        ).as_dict()["why_not"]

        assert "switched off" in why
        assert "confirm" not in why

    def test_switching_it_back_on_keeps_the_confirmation_it_had(self, session):
        """Pausing an account was never a statement about its rulebook."""
        account = make(session, rules_confirmed=True)
        for state in (False, True):
            challenge_accounts.set_active(
                session,
                tenant_id=account.tenant_id,
                account_id=account.id,
                active=state,
            )

        assert account.rules_confirmed is True
        assert challenge_accounts.AccountView(
            account=account, rulebook=challenge_accounts._resolve(KEY)
        ).as_dict()["tracking_available"] is True

    def test_the_history_survives_being_switched_off(self, session):
        account = make(session, notes="phase 1 failed on the daily limit")
        challenge_accounts.set_active(
            session, tenant_id=account.tenant_id, account_id=account.id, active=False
        )

        assert account.notes == "phase 1 failed on the daily limit"
        assert account.starting_balance is not None

    def test_the_summary_counts_the_ones_switched_on(self, session):
        on = make(session, label="On")
        make(session, label="Off")
        off = [a for a in challenge_accounts.listing(session) if a.account.label == "Off"][0]
        challenge_accounts.set_active(
            session, tenant_id=on.tenant_id, account_id=off.account.id, active=False
        )

        totals = challenge_accounts.summary(session, tenant_id=on.tenant_id)

        assert totals["total"] == 2
        assert totals["active"] == 1

    def test_an_unknown_account_is_a_not_found(self, session):
        import uuid as uuid_module

        from app.core.errors import NotFoundError

        with pytest.raises(NotFoundError):
            challenge_accounts.set_active(
                session,
                tenant_id=challenge_accounts.default_tenant(session),
                account_id=uuid_module.uuid4(),
                active=False,
            )

    def test_over_the_api(self, holder, session):
        account = make(session)

        response = holder.post(
            f"/api/v1/risk/challenge-accounts/{account.id}/active",
            json={"active": False},
        )

        assert response.status_code == 200, response.text
        assert response.json()["active"] is False
        assert response.json()["account"]["is_active"] is False

    def test_sending_the_same_state_twice_lands_in_the_same_place(self, holder, session):
        """A stated destination rather than a toggle: a retried request from a
        slow connection must not switch the account back on."""
        account = make(session)
        url = f"/api/v1/risk/challenge-accounts/{account.id}/active"

        holder.post(url, json={"active": False})
        second = holder.post(url, json={"active": False})

        assert second.json()["active"] is False

    def test_a_reader_cannot_switch_an_account(self, client, session):
        """Switching an account back on puts it under measurement again, which
        is the account holder's decision."""
        account = make(session)

        response = client.post(
            f"/api/v1/risk/challenge-accounts/{account.id}/active",
            json={"active": False},
        )

        assert response.status_code >= 400


PHASE_ONE = next(b.key for b in rulebook_module.RULEBOOKS if b.phase == "phase 1")
PHASE_TWO = next(b.key for b in rulebook_module.RULEBOOKS if b.phase == "phase 2")


class TestATwoPhaseProgramme:
    """Phase one, phase two and the funded account are three documents.

    To the holder they are one account passing through them. Recording each as
    a fresh row would scatter one account's history across three, and the
    platform would have no way to say that a funded account and the challenge
    that earned it are the same thing.
    """

    def test_the_account_keeps_its_identity_across_a_phase(self, session):
        account = make(session, rulebook_key=PHASE_ONE, label="FTMO 100k")
        original = account.id

        challenge_accounts.move_to(
            session,
            tenant_id=account.tenant_id,
            account_id=account.id,
            rulebook_key=PHASE_TWO,
        )

        assert account.id == original
        assert account.label == "FTMO 100k"
        assert account.rulebook_key == PHASE_TWO

    def test_confirmation_does_not_survive_the_move(self, session):
        """The single failure the confirmation mechanism exists to prevent:
        measuring against numbers nobody checked while showing them checked."""
        account = make(session, rulebook_key=PHASE_ONE, rules_confirmed=True)
        assert account.rules_confirmed is True

        challenge_accounts.move_to(
            session,
            tenant_id=account.tenant_id,
            account_id=account.id,
            rulebook_key=PHASE_TWO,
        )

        assert account.rules_confirmed is False
        assert account.confirmed_at is None

    def test_and_so_the_account_stops_being_tracked_until_it_is_confirmed(self, session):
        account = make(session, rulebook_key=PHASE_ONE, rules_confirmed=True)
        challenge_accounts.move_to(
            session,
            tenant_id=account.tenant_id,
            account_id=account.id,
            rulebook_key=PHASE_TWO,
        )

        view = challenge_accounts.AccountView(
            account=account, rulebook=challenge_accounts._resolve(PHASE_TWO)
        ).as_dict()

        assert view["tracking_available"] is False
        assert "confirmed" in view["why_not"]

    def test_the_balance_can_be_reset_for_the_new_phase(self, session):
        """Most programmes reset the balance between phases. A phase two
        measured against phase one's closing balance computes every drawdown
        from the wrong floor."""
        account = make(session, rulebook_key=PHASE_ONE, starting_balance=Decimal("103500"))

        challenge_accounts.move_to(
            session,
            tenant_id=account.tenant_id,
            account_id=account.id,
            rulebook_key=PHASE_TWO,
            starting_balance=Decimal("100000"),
        )

        assert account.starting_balance == Decimal("100000")

    def test_the_balance_is_left_alone_when_it_is_not_given(self, session):
        account = make(session, rulebook_key=PHASE_ONE, starting_balance=Decimal("100000"))

        challenge_accounts.move_to(
            session,
            tenant_id=account.tenant_id,
            account_id=account.id,
            rulebook_key=PHASE_TWO,
        )

        assert account.starting_balance == Decimal("100000")

    def test_passing_the_last_phase_turns_it_into_a_funded_account(self, session):
        account = make(session, rulebook_key=PHASE_ONE)
        funded_key = next(
            b.key for b in rulebook_module.RULEBOOKS if b.phase.startswith("funded")
        )

        challenge_accounts.move_to(
            session,
            tenant_id=account.tenant_id,
            account_id=account.id,
            rulebook_key=funded_key,
            kind="funded",
        )

        assert account.kind == "funded"
        assert account.rulebook_key == funded_key

    def test_the_notes_survive_the_move(self, session):
        account = make(
            session, rulebook_key=PHASE_ONE, notes="the daily limit is measured on equity"
        )

        challenge_accounts.move_to(
            session,
            tenant_id=account.tenant_id,
            account_id=account.id,
            rulebook_key=PHASE_TWO,
        )

        assert account.notes == "the daily limit is measured on equity"


class TestWhatCannotMove:
    def test_a_live_account_is_on_no_programme(self, session):
        account = make(session, kind="live", rulebook_key=None, label="Live")

        with pytest.raises(ValidationFailedError) as caught:
            challenge_accounts.move_to(
                session,
                tenant_id=account.tenant_id,
                account_id=account.id,
                rulebook_key=PHASE_TWO,
            )

        assert "no phase" in str(caught.value).lower()

    def test_a_prop_account_cannot_be_turned_into_a_live_one(self, session):
        """It would keep a programme history against an account on no
        programme."""
        account = make(session, rulebook_key=PHASE_ONE)

        with pytest.raises(ValidationFailedError):
            challenge_accounts.move_to(
                session,
                tenant_id=account.tenant_id,
                account_id=account.id,
                rulebook_key=PHASE_TWO,
                kind="live",
            )

    def test_an_unknown_rulebook_is_refused_and_the_known_ones_are_named(self, session):
        account = make(session, rulebook_key=PHASE_ONE)

        with pytest.raises(ValidationFailedError) as caught:
            challenge_accounts.move_to(
                session,
                tenant_id=account.tenant_id,
                account_id=account.id,
                rulebook_key="no-such-book",
            )

        assert PHASE_ONE in str(caught.value)

    def test_over_the_api_the_response_says_confirmation_was_reset(self, holder, session):
        account = make(session, rulebook_key=PHASE_ONE, rules_confirmed=True)

        response = holder.post(
            f"/api/v1/risk/challenge-accounts/{account.id}/move",
            json={"rulebook_key": PHASE_TWO},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["account"]["rules_confirmed"] is False
        assert "confirmed again" in body["note"]

    def test_a_reader_cannot_move_an_account(self, client, session):
        account = make(session, rulebook_key=PHASE_ONE)

        response = client.post(
            f"/api/v1/risk/challenge-accounts/{account.id}/move",
            json={"rulebook_key": PHASE_TWO},
        )

        assert response.status_code >= 400


class TestRemovingAnAccountThatShouldNotExist:
    """Off is the ordinary answer; this is for the row that is not history."""

    def make(self, session):
        from decimal import Decimal

        from app.services import challenge_accounts

        return challenge_accounts.create(
            session,
            tenant_id=challenge_accounts.default_tenant(session),
            label="typo",
            rulebook_key="fundednext-free-trial",
            starting_balance=Decimal("15000"),
        )

    def test_a_deleted_account_is_gone_not_hidden(self, session):
        from app.services import challenge_accounts

        account = self.make(session)
        tenant = challenge_accounts.default_tenant(session)

        label = challenge_accounts.remove(
            session, tenant_id=tenant, account_id=account.id
        )

        assert label == "typo"
        assert all(
            view.account.id != account.id
            for view in challenge_accounts.listing(session, tenant_id=tenant)
        )

    def test_deleting_an_unknown_account_is_named(self, session):
        import uuid

        import pytest

        from app.core.errors import NotFoundError
        from app.services import challenge_accounts

        with pytest.raises(NotFoundError):
            challenge_accounts.remove(
                session,
                tenant_id=challenge_accounts.default_tenant(session),
                account_id=uuid.uuid4(),
            )


class TestTheFreeTrialRulebook:
    """Transcribed from the account's own objectives panel, because the
    general-rules table has no Free Trial column."""

    def test_it_asks_for_five_percent_over_three_days(self):
        from app.brain import rulebooks

        book = rulebooks.get("fundednext-free-trial")

        assert book is not None
        assert book.rules.profit_target_pct == 0.05
        assert book.rules.min_trading_days == 3

    def test_it_does_not_inherit_the_paid_program_numbers(self):
        """Copying Stellar 2-Step would set a target half again too high and
        a day count that fails this account for being too quick."""
        from app.brain import rulebooks

        trial = rulebooks.get("fundednext-free-trial")
        paid = rulebooks.get("fundednext-stellar-2step-phase1")

        assert trial.rules.profit_target_pct != paid.rules.profit_target_pct
        assert trial.rules.min_trading_days != paid.rules.min_trading_days

    def test_the_loss_limits_match_the_panel(self):
        from app.brain import rulebooks

        book = rulebooks.get("fundednext-free-trial")

        # $750 daily and $1,500 total on a $15,000 account.
        assert book.rules.max_daily_drawdown_pct * 15000 == 750
        assert book.rules.max_total_drawdown_pct * 15000 == 1500
