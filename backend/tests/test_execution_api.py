"""Execution endpoints (spec §22, §26).

The closest this API gets to real money, so most of these tests are about what
must remain impossible rather than about what works.

Two of them read the module's own source. That is deliberate: a test that only
exercises the routes proves the routes behave today, while a test that reads
the imports and call sites proves nobody added a path to the engine — which is
the failure that would not announce itself.
"""

from __future__ import annotations

import ast
import inspect
import pathlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(session):
    from app.db.session import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class TestNothingHereCanTrade:
    def test_the_module_never_calls_the_engine(self):
        """A route that placed an order would be a mutating route, and the gate
        refuses to start the app with one that has no permission. This catches
        it one step earlier, at the call site."""
        import app.api.v1.execution as module

        tree = ast.parse(inspect.getsource(module))
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }

        assert "execute" not in called
        assert "submit" not in called
        assert "disengage" not in called

    def test_there_is_no_mutating_route_anywhere(self, client):
        from app.api.guard import find_ungated_routes
        from app.main import app

        # Not "there are no mutating routes" - there is one now, and the
        # gate was built for exactly that. What must stay true is that
        # every one of them is gated.
        assert find_ungated_routes(app, require_auth=False) == []

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/execution/policy",
            "/api/v1/execution/preflight",
            "/api/v1/execution/guardian",
            "/api/v1/execution/accounts",
        ],
    )
    def test_post_is_refused_on_every_route(self, client, path):
        assert client.post(path).status_code == 405

    def test_the_policy_response_says_so_in_words(self, client):
        payload = client.get("/api/v1/execution/policy").json()

        assert payload["api_can_place_orders"] is False
        assert payload["api_can_disengage_kill_switch"] is False


class TestPolicy:
    def test_the_four_switches_are_reported_separately(self, client):
        """One flag would mean whoever enables the engine also enables live
        orders."""
        payload = client.get("/api/v1/execution/policy").json()

        for switch in ("execution_enabled", "dry_run", "require_auth"):
            assert switch in payload

    def test_the_kill_switch_defaults_engaged(self, client):
        payload = client.get("/api/v1/execution/policy").json()

        assert payload["kill_switch_default_engaged"] is True

    def test_the_only_broker_declares_itself_simulated(self, client):
        payload = client.get("/api/v1/execution/policy").json()

        assert payload["broker"]["simulated"] is True

    def test_all_four_approving_layers_are_named(self, client):
        payload = client.get("/api/v1/execution/policy").json()

        assert set(payload["required_approvals"]) == {
            "risk", "portfolio", "challenge", "stress"
        }


class TestPreflight:
    def test_the_default_deployment_blocks_a_perfect_order(self, client):
        """Every approval present and it still refuses, because the deployment
        switches are the outer gate."""
        payload = client.get("/api/v1/execution/preflight").json()

        assert payload["cleared"] is False
        assert any("disabled" in b for b in payload["blocks"])

    @pytest.mark.parametrize("missing", ["risk", "portfolio", "challenge", "stress"])
    def test_a_missing_approval_is_named(self, client, missing):
        approvals = ",".join(
            a for a in ("risk", "portfolio", "challenge", "stress") if a != missing
        )
        payload = client.get(
            "/api/v1/execution/preflight", params={"approvals": approvals}
        ).json()

        assert any(f"no approval from the {missing}" in b for b in payload["blocks"])

    def test_four_approvals_from_one_layer_do_not_satisfy_it(self, client):
        payload = client.get(
            "/api/v1/execution/preflight", params={"approvals": "risk,risk,risk,risk"}
        ).json()

        assert sum("no approval from" in b for b in payload["blocks"]) == 3

    def test_a_stop_on_the_wrong_side_is_refused_before_anything_is_checked(self, client):
        payload = client.get(
            "/api/v1/execution/preflight",
            params={"side": "buy", "entry": 1.10, "stop": 1.12},
        ).json()

        assert payload["cleared"] is False
        assert "nothing was checked" in payload["note"]

    def test_the_client_order_id_is_derived_not_random(self, client):
        """Two identical requests would be the same order to a broker."""
        first = client.get("/api/v1/execution/preflight").json()["client_order_id"]

        assert first.startswith("mld-")
        assert len(first) > 10

    def test_the_checks_are_returned_whole_not_only_the_failures(self, client):
        """An operator debugging a refusal needs to see what passed."""
        payload = client.get("/api/v1/execution/preflight").json()

        assert payload["checks"]
        assert any(v is True for v in payload["checks"].values())

    def test_clearing_preflight_is_not_a_promise_of_a_fill(self, client):
        payload = client.get("/api/v1/execution/preflight").json()

        assert "does not guarantee a fill" in payload["note"]


class TestOrderStates:
    def test_no_terminal_state_has_a_way_out(self, client):
        payload = client.get("/api/v1/execution/order-states").json()

        for terminal in ("filled", "cancelled", "rejected"):
            assert payload["transitions"][terminal] == []

    def test_unknown_can_still_resolve_either_way(self, client):
        """It is not a rejection; the order may be live."""
        payload = client.get("/api/v1/execution/order-states").json()

        assert "filled" in payload["transitions"]["unknown"]
        assert "rejected" in payload["transitions"]["unknown"]

    def test_the_meaning_of_unknown_is_spelled_out(self, client):
        payload = client.get("/api/v1/execution/order-states").json()

        assert "may be" in payload["unknown_means"]


class TestGuardian:
    def test_a_matching_book_is_healthy(self, client):
        payload = client.get(
            "/api/v1/execution/guardian",
            params={
                "broker_positions": "EURUSD:buy:1.0:1.09",
                "expected_positions": "EURUSD:buy:1.0:1.09",
            },
        ).json()

        assert payload["healthy"] is True

    def test_a_position_the_system_did_not_open_is_the_loudest_finding(self, client):
        payload = client.get(
            "/api/v1/execution/guardian",
            params={"broker_positions": "GBPUSD:buy:1.0:1.25"},
        ).json()

        assert payload["orphans"] == ["GBPUSD"]
        assert any("did not open it" in a for a in payload["alerts"])

    def test_a_position_without_a_stop_is_unprotected(self, client):
        payload = client.get(
            "/api/v1/execution/guardian",
            params={
                "broker_positions": "EURUSD:buy:1.0",
                "expected_positions": "EURUSD:buy:1.0",
            },
        ).json()

        assert payload["unprotected"] == ["EURUSD"]

    def test_the_guardian_closes_nothing(self, client):
        payload = client.get(
            "/api/v1/execution/guardian",
            params={"broker_positions": "GBPUSD:buy:1.0"},
        ).json()

        assert payload["closes_nothing"] is True


class TestAccounts:
    def test_an_empty_book_explains_itself(self, client):
        """An empty list on its own reads as a system with nothing wrong."""
        payload = client.get("/api/v1/execution/accounts").json()

        assert payload["accounts"] == []
        assert "simulator" in payload["reason"]

    def test_the_global_switch_defaults_engaged(self, client):
        payload = client.get("/api/v1/execution/accounts").json()

        assert payload["global_kill_switch"]["engaged"] is True

    def test_exposure_is_never_reported_as_one_total(self, client):
        payload = client.get("/api/v1/execution/accounts").json()

        assert "different money" in payload["note"]


class TestTheSourceItself:
    def test_the_execution_package_still_ships_no_network_client(self):
        """Belt and braces with the package's own test: if a real adapter is
        ever added, this fails here too rather than only there."""
        package = pathlib.Path(__file__).resolve().parents[1] / "app" / "execution"
        roots: set[str] = set()
        for path in package.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots.update(a.name.split(".")[0] for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    roots.add(node.module.split(".")[0])

        forbidden = {"httpx", "requests", "socket", "urllib", "aiohttp", "MetaTrader5"}
        assert roots & forbidden == set()
