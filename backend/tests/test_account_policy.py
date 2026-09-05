"""Set an account's brain and risk from the site, not over SSH.

Both settings lived in environment variables, so changing either was an SSH
session, an edit to `.env.prod`, and a container recreate - the env file is
read when the process starts. Twice in one day an operator had to ask an
engineer to change a number, and both times the recreate killed the trading
cycle in flight.
"""

from __future__ import annotations

import pytest

from app.services import account_policy
from app.workers import autotrade


@pytest.fixture(autouse=True)
def _clean_cache():
    account_policy.invalidate()
    yield
    account_policy.invalidate()


@pytest.fixture()
def stored(monkeypatch):
    """Pretend the table holds these rows, without touching a database."""

    def _set(rows):
        monkeypatch.setattr(account_policy, "_load", lambda: rows)
        account_policy.invalidate()

    return _set


class TestAbsentIsNotZero:
    def test_an_empty_table_changes_nothing(self, stored, monkeypatch):
        """This is the whole safety of the migration: every account keeps
        behaving exactly as it did before the table existed."""
        from app.core.config import get_settings

        monkeypatch.setattr(get_settings(), "autotrade_risk_percent", 0.75, raising=False)
        monkeypatch.setattr(get_settings(), "account_risk_percent", "", raising=False)
        stored({})

        assert autotrade._risk_percent("10012494823") == 0.75

    def test_a_database_that_cannot_be_read_falls_back(self, monkeypatch):
        """A settings lookup must never be the reason an account stops
        trading."""

        def explode():
            raise RuntimeError("no database")

        monkeypatch.setattr(account_policy, "_load", explode)
        account_policy.invalidate()

        assert account_policy.risk_percent("10012494823") is None

    def test_a_row_with_no_risk_set_falls_back(self, stored):
        stored({"111": {"login": "111", "strategies": [], "risk_percent": None}})

        assert account_policy.risk_percent("111") is None

    def test_an_empty_strategy_list_means_not_set_rather_than_trade_nothing(self, stored):
        """A deliberate stop is the kill switch. A settings row that quietly
        meant the same would be a second halt nobody can find."""
        stored({"111": {"login": "111", "strategies": [], "risk_percent": 2.0}})

        assert account_policy.strategies("111") is None


class TestPrecedence:
    def test_the_stored_policy_beats_the_environment(self, stored, monkeypatch):
        from app.core.config import get_settings

        monkeypatch.setattr(get_settings(), "autotrade_risk_percent", 0.75, raising=False)
        monkeypatch.setattr(get_settings(), "account_risk_percent", "111=2.0", raising=False)
        stored({"111": {"login": "111", "strategies": [], "risk_percent": 3.0}})

        assert autotrade._risk_percent("111") == 3.0

    def test_the_environment_still_applies_where_nothing_is_stored(self, stored, monkeypatch):
        from app.core.config import get_settings

        monkeypatch.setattr(get_settings(), "autotrade_risk_percent", 0.75, raising=False)
        monkeypatch.setattr(get_settings(), "account_risk_percent", "111=2.0", raising=False)
        stored({})

        assert autotrade._risk_percent("111") == 2.0

    def test_a_stored_figure_is_capped_like_any_other(self, stored, monkeypatch):
        """A page is easier to typo into than a file, not harder."""
        from app.core.config import get_settings

        monkeypatch.setattr(get_settings(), "autotrade_risk_percent", 0.75, raising=False)
        stored({"111": {"login": "111", "strategies": [], "risk_percent": 50.0}})

        assert autotrade._risk_percent("111") == autotrade.MAX_ACCOUNT_RISK_PERCENT

    def test_zero_is_ignored_rather_than_halting_the_account(self, stored):
        """Zero makes R undefined and stops the account by a route that is
        not the kill switch, which is where stopping belongs."""
        stored({"111": {"login": "111", "strategies": [], "risk_percent": 0.0}})

        assert account_policy.risk_percent("111") is None


class TestTheCacheServesBothMasters:
    def test_it_does_not_query_on_every_call(self, monkeypatch):
        """It is consulted dozens of times a cycle."""
        calls = {"n": 0}

        def counted():
            calls["n"] += 1
            return {}

        monkeypatch.setattr(account_policy, "_load", counted)
        account_policy.invalidate()

        for _ in range(20):
            account_policy.all_policies(now=100.0)

        assert calls["n"] == 1

    def test_it_re_reads_once_the_ttl_passes(self, monkeypatch):
        calls = {"n": 0}

        def counted():
            calls["n"] += 1
            return {"111": {"login": "111", "strategies": [], "risk_percent": 1.0}}

        monkeypatch.setattr(account_policy, "_load", counted)
        account_policy.invalidate()

        account_policy.all_policies(now=100.0)
        account_policy.all_policies(now=100.0 + account_policy.CACHE_SECONDS + 1)

        assert calls["n"] == 2

    def test_a_write_makes_the_change_visible_at_once(self, monkeypatch):
        """Otherwise the operator saves, watches the page show the old figure
        for twenty seconds, and reasonably concludes it did not save."""
        rows = {"111": {"login": "111", "strategies": [], "risk_percent": 1.0}}
        monkeypatch.setattr(account_policy, "_load", lambda: dict(rows))
        account_policy.invalidate()

        assert account_policy.risk_percent("111") == 1.0
        rows["111"]["risk_percent"] = 4.0
        account_policy.invalidate()

        assert account_policy.risk_percent("111") == 4.0


class TestTheWriteRouteIsGatedCorrectly:
    def test_it_is_not_behind_execute(self):
        """A key that can place orders must not be able to raise its own risk
        limit. That is privilege escalation with extra steps."""
        import inspect

        from app.api.v1 import execution
        from app.core.enums import Permission

        source = inspect.getsource(execution.write_account_policy)
        # The parameter list, not the decorator above it and not the prose
        # below - the docstring mentions EXECUTE precisely to say it is the
        # wrong answer, and a test that searched the whole function would
        # fail on its own explanation.
        params = source[source.index("def write_account_policy(") : source.index('"""')]

        assert "POLICY_MANAGE" in params
        assert "EXECUTE" not in params
        # And the dependency it names really is the broker-management one.
        closed_over = [c.cell_contents for c in (execution.POLICY_MANAGE.dependency.__closure__ or ())]
        assert Permission.BROKER_MANAGE in closed_over
