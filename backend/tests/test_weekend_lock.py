"""The weekend lock for prop accounts."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.workers import autotrade, trailing


def test_the_lock_list_comes_from_the_setting(monkeypatch):
    monkeypatch.setenv("MOLIDO_WEEKEND_LOCK_LOGINS", "1514533027, 42")
    assert autotrade.weekend_lock_logins() == {"1514533027", "42"}
    monkeypatch.delenv("MOLIDO_WEEKEND_LOCK_LOGINS")
    assert autotrade.weekend_lock_logins() == set()


class TestPropRegisteredLogins:
    """The self-service half: an account registered with a rulebook is
    weekend-locked without anyone naming its login in an env var."""

    def register(self, session, label, **over):
        from app.services import challenge_accounts

        return challenge_accounts.create(
            session,
            tenant_id=challenge_accounts.default_tenant(session),
            label=label,
            rulebook_key=over.pop("rulebook_key", "ftmo-challenge-2step-phase1"),
            starting_balance=Decimal("10000"),
            **over,
        )

    def test_a_login_named_in_the_label_is_returned(self, session):
        self.register(session, "FTMO-Demo 1514533027")

        assert autotrade._prop_registered_logins(session) == {"1514533027"}

    def test_a_switched_off_registration_is_not_counted(self, session):
        from app.services import challenge_accounts

        account = self.register(session, "1514533027")
        challenge_accounts.set_active(
            session,
            tenant_id=challenge_accounts.default_tenant(session),
            account_id=account.id,
            active=False,
        )

        assert autotrade._prop_registered_logins(session) == set()

    def test_a_label_naming_no_login_contributes_nothing(self, session):
        """The ambiguous case `_is_prop_account` resolves per login this
        function deliberately does not guess at fleet-wide."""
        self.register(session, "my challenge")

        assert autotrade._prop_registered_logins(session) == set()

    def test_an_unreadable_registry_returns_empty_not_an_error(self, session, monkeypatch):
        from app.services import challenge_accounts

        def explode(*_a, **_k):
            raise RuntimeError("no database")

        monkeypatch.setattr(challenge_accounts, "listing", explode)

        assert autotrade._prop_registered_logins(session) == set()


class TestIsPropAccount:
    """`_is_prop_account` is the per-login question the fleet-wide sweep
    cannot ask without a login already in hand - used by the trading-refusal
    gate itself, where the login is always known."""

    def register(self, session, label):
        from decimal import Decimal as _Decimal

        from app.services import challenge_accounts

        return challenge_accounts.create(
            session,
            tenant_id=challenge_accounts.default_tenant(session),
            label=label,
            rulebook_key="ftmo-challenge-2step-phase1",
            starting_balance=_Decimal("10000"),
        )

    def test_a_registered_login_is_prop(self, session):
        self.register(session, "1514533027")

        assert autotrade._is_prop_account(session, "1514533027") is True

    def test_an_unregistered_login_is_not_prop(self, session):
        self.register(session, "1514533027")

        assert autotrade._is_prop_account(session, "68345601") is False

    def test_an_empty_login_is_never_prop(self, session):
        assert autotrade._is_prop_account(session, "") is False


def test_friday_afternoon_is_weekend_ahead():
    assert autotrade._weekend_ahead(datetime(2026, 9, 18, 16, 0, tzinfo=UTC))
    assert not autotrade._weekend_ahead(datetime(2026, 9, 18, 15, 59, tzinfo=UTC))


def test_a_winner_below_the_trail_start_goes_to_entry():
    stop, why = trailing.proposed_stop(
        side="buy", entry=100.0, stop=99.0, price=100.4, risk=1.0, lock_at_r=0.3
    )
    assert stop == 100.0
    assert "weekend" in why


def test_a_trade_not_far_enough_ahead_is_left_alone():
    stop, _ = trailing.proposed_stop(
        side="buy", entry=100.0, stop=99.0, price=100.2, risk=1.0, lock_at_r=0.3
    )
    assert stop is None


def test_a_short_locks_to_entry_the_other_way():
    stop, _ = trailing.proposed_stop(
        side="sell", entry=100.0, stop=101.0, price=99.5, risk=1.0, lock_at_r=0.3
    )
    assert stop == 100.0


def test_a_stop_already_past_entry_is_not_pulled_back():
    stop, _ = trailing.proposed_stop(
        side="buy", entry=100.0, stop=100.2, price=100.5, risk=1.0, lock_at_r=0.3
    )
    assert stop is None


def test_without_the_lock_nothing_changes_below_the_trail_start():
    stop, _ = trailing.proposed_stop(side="buy", entry=100.0, stop=99.0, price=100.5, risk=1.0)
    assert stop is None
