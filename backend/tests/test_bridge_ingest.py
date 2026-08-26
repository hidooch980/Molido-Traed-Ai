"""Publishing into the bridge from a terminal that is not on this machine.

The test that matters most here is the round trip: what this route writes, the
provider must be able to read. Two halves of one contract written in two files
drift, and the way that drift presents is a terminal that publishes happily
into a directory the platform reports as empty.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.providers.metatrader import MetaTraderBridge


@pytest.fixture()
def bridge_dir(tmp_path, monkeypatch):
    directory = tmp_path / "main"
    directory.mkdir()
    monkeypatch.setenv("MOLIDO_MT5_BRIDGE_DIRS", f"main={directory}")
    return directory


@pytest.fixture()
def client(session, bridge_dir):
    """A caller holding `broker.manage`, which publishing requires.

    An expert authenticates with an API key in production; the permission it
    resolves to is the same one either way, so overriding the principal tests
    the route rather than the key store.
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


@pytest.fixture()
def anonymous(session, bridge_dir):
    """No credential at all. Publishing must refuse it."""
    from app.db.session import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def payload(**overrides):
    body = {
        "account_key": "main",
        "account": {
            "login": 34729037,
            "server": "FundedNext-Server",
            "currency": "USD",
            "balance": 6000.0,
            "equity": 5980.5,
            "margin": 120.0,
            "free_margin": 5860.5,
            "trade_mode": 0,
        },
        "symbols": [{"name": "EURUSD", "digits": 5}],
        "positions": [{"symbol": "EURUSD", "volume": 0.1, "profit": -19.5}],
        "connected": True,
        "login": 34729037,
    }
    body.update(overrides)
    return body


class TestTheRoundTrip:
    """What the route writes, the reader must read. That is the whole point."""

    def test_the_provider_reads_the_account_this_route_published(
        self, client, bridge_dir
    ):
        assert client.post("/api/v1/bridge/publish", json=payload()).status_code == 200

        account = MetaTraderBridge(directory=bridge_dir).account()

        assert account["available"] is True
        assert account["login"] == 34729037
        assert account["balance"] == pytest.approx(6000.0)
        # Equity below balance is the open book. Publishing only balance would
        # hide the drawdown that ends a challenge.
        assert account["equity"] == pytest.approx(5980.5)

    def test_the_provider_reads_the_positions(self, client, bridge_dir):
        client.post("/api/v1/bridge/publish", json=payload())

        positions = MetaTraderBridge(directory=bridge_dir).positions()

        assert positions["available"] is True
        assert [p["symbol"] for p in positions["positions"]] == ["EURUSD"]

    def test_a_terminal_with_nobody_logged_in_is_not_reported_as_usable(
        self, client, bridge_dir
    ):
        """The state this deployment sat in for hours looking healthy.

        The expert is running and the heartbeat is fresh, but no account is
        logged in. `connected: true` alone did not catch it; a login of zero
        did, and this route has to preserve that distinction rather than
        flatten it into "the bridge is up".
        """
        client.post(
            "/api/v1/bridge/publish",
            json=payload(connected=False, login=0, account={}),
        )

        state = MetaTraderBridge(directory=bridge_dir).state()
        assert state.login == 0


class TestTheAccountKey:
    def test_an_unconfigured_account_is_refused(self, client):
        """The directory is the account.

        The files carry no account identity, so a publish filed under the
        wrong key is a publish attributed to the wrong money - and the next
        order sized against it goes to the wrong money too.
        """
        response = client.post(
            "/api/v1/bridge/publish", json=payload(account_key="not-configured")
        )
        assert response.status_code >= 400

    def test_the_refusal_names_the_accounts_that_do_exist(self, client):
        """The usual cause is a typo in one expert's inputs.

        Without the list, the symptom is a terminal publishing into silence
        and no way to tell which of eleven is misconfigured.
        """
        body = client.post(
            "/api/v1/bridge/publish", json=payload(account_key="typo")
        ).json()
        assert "main" in json.dumps(body)


class TestWriteOrderAndAtomicity:
    def test_the_heartbeat_is_not_older_than_the_data_it_vouches_for(
        self, client, bridge_dir
    ):
        """Every reader gates on the heartbeat.

        Written first, it would vouch for data that had not landed yet, and a
        reader would believe half-written positions because the timestamp
        beside them looked current.
        """
        client.post("/api/v1/bridge/publish", json=payload())

        beat = (bridge_dir / "molido_heartbeat.json").stat().st_mtime
        for name in ("molido_account.json", "molido_symbols.json", "molido_positions.json"):
            assert (bridge_dir / name).stat().st_mtime <= beat

    def test_no_temporary_files_are_left_behind(self, client, bridge_dir):
        """A reader scanning this directory should see four files, not eight."""
        client.post("/api/v1/bridge/publish", json=payload())

        leftovers = [p.name for p in bridge_dir.iterdir() if p.name.startswith(".")]
        assert leftovers == []

    def test_a_second_publish_replaces_rather_than_appends(self, client, bridge_dir):
        client.post("/api/v1/bridge/publish", json=payload())
        client.post(
            "/api/v1/bridge/publish",
            json=payload(positions=[{"symbol": "GBPUSD", "volume": 0.2}]),
        )

        stored = json.loads((bridge_dir / "molido_positions.json").read_text())
        assert [p["symbol"] for p in stored["positions"]] == ["GBPUSD"]


class TestItDoesNotTrade:
    def test_the_response_says_it_sends_no_orders(self, client):
        """The expert is read-only by design and this is its other half.

        An order path that exists is an order path that can fire.
        """
        body = client.post("/api/v1/bridge/publish", json=payload()).json()
        assert "no orders" in body["note"] or "sends no" in body["note"]

    def test_nothing_is_written_outside_the_configured_directory(
        self, client, bridge_dir, tmp_path
    ):
        client.post("/api/v1/bridge/publish", json=payload())
        siblings = [p.name for p in tmp_path.iterdir()]
        assert siblings == ["main"]


class TestItIsGated:
    def test_publishing_without_a_credential_is_refused(self, anonymous):
        """This route writes files that decisions are sized against.

        An unauthenticated caller who can publish an account balance can
        choose what every position size is computed from.
        """
        response = anonymous.post("/api/v1/bridge/publish", json=payload())
        assert response.status_code == 401

    def test_nothing_is_written_when_the_caller_is_refused(
        self, anonymous, bridge_dir
    ):
        anonymous.post("/api/v1/bridge/publish", json=payload())
        assert list(bridge_dir.iterdir()) == []
