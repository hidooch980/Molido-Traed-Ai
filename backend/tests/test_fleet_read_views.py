"""Read-only views answer per terminal, from the configured fleet.

The pilot on 2026-09-14 had a working demo under `main` while
/execution/autopilot said the bridge could not describe the account: the view
read the single default directory, which no fleet terminal writes to.
"""

from __future__ import annotations

import json
import pathlib
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.execution import autopilot
from app.integrations import mcp


def _terminal(root: pathlib.Path, name: str, *, login: int | None) -> pathlib.Path:
    directory = root / name
    directory.mkdir()
    (directory / "molido_heartbeat.json").write_text(
        json.dumps({"published_at": datetime.now(UTC).strftime("%Y.%m.%d %H:%M:%S")}),
        encoding="utf-8",
    )
    if login is not None:
        (directory / "molido_account.json").write_text(
            json.dumps({"login": login, "connected": True, "trade_mode": 0}),
            encoding="utf-8",
        )
    (directory / "molido_positions.json").write_text(
        json.dumps({"positions": [{"symbol": "EURUSD"}] if login else []}),
        encoding="utf-8",
    )
    return directory


@pytest.fixture()
def fleet(tmp_path, monkeypatch):
    main = _terminal(tmp_path, "main", login=5001)
    idle = _terminal(tmp_path, "idle", login=None)
    monkeypatch.setenv("MOLIDO_MT5_BRIDGE_DIRS", f"main={main},idle={idle}")
    monkeypatch.setattr(autopilot, "mode_now", lambda: (autopilot.LIVE, "test", False))


@pytest.fixture()
def client(session):
    from app.db.session import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class TestAutopilotView:
    def test_the_account_gate_is_read_per_terminal(self, fleet, client):
        body = client.get("/api/v1/execution/autopilot").json()
        gate = body["gates"]["account"]

        assert gate["terminals"]["main"]["open"] is True
        assert "demo" in gate["terminals"]["main"]["detail"]
        assert gate["terminals"]["idle"]["open"] is False
        assert gate["open"] is True
        assert body["would_send_live_orders"] is True
        assert body["mode"] == autopilot.LIVE

    def test_no_passing_terminal_sends_nothing(self, tmp_path, monkeypatch, client):
        idle = _terminal(tmp_path, "idle", login=None)
        monkeypatch.setenv("MOLIDO_MT5_BRIDGE_DIRS", f"idle={idle}")
        monkeypatch.setattr(autopilot, "mode_now", lambda: (autopilot.LIVE, "test", False))

        body = client.get("/api/v1/execution/autopilot").json()

        assert body["gates"]["account"]["open"] is False
        assert body["would_send_live_orders"] is False


class TestPositionsView:
    def test_positions_are_gathered_from_every_terminal(self, fleet, client):
        body = client.get("/api/v1/execution/positions").json()

        assert body["available"] is True
        assert body["positions"] == [{"symbol": "EURUSD", "terminal": "main"}]
        assert body["account"]["login"] == 5001
        assert set(body["terminals"]) == {"main", "idle"}
        assert body["terminals"]["idle"]["account"] is None


class TestSingleAccountViews:
    def test_accounts_live_account_is_the_connected_terminal(self, fleet, client):
        body = client.get("/api/v1/execution/accounts").json()

        assert body["live_account"]["login"] == "5001"
        assert body["live_account"]["is_demo"] is True

    def test_equity_reads_the_connected_terminal(self, fleet, client):
        body = client.get("/api/v1/execution/equity").json()

        assert body.get("account") == "5001"

    def test_metatrader_summary_is_a_usable_terminal(self, fleet, client):
        body = client.get("/api/v1/brokers/metatrader").json()

        assert body["account"]["available"] is True
        assert body["account"]["login"] == 5001


class TestMcpTools:
    def test_account_tool_names_its_terminal(self, fleet, session):
        result = mcp.call(session, "account")["result"]

        assert result["available"] is True
        assert result["terminal"] == "main"

    def test_positions_tool_reads_the_fleet(self, fleet, session):
        result = mcp.call(session, "positions")["result"]

        assert result["positions"] == [{"symbol": "EURUSD", "terminal": "main"}]

    def test_autopilot_tool_reads_the_fleet(self, fleet, session):
        result = mcp.call(session, "autopilot")["result"]

        assert result["account_gate"]["terminals"]["main"]["open"] is True
        assert result["would_send_live_orders"] is True

    def test_equity_tool_names_the_connected_terminal(self, fleet, session):
        result = mcp.call(session, "equity_series")["result"]

        assert result["available"] is True
        assert result["terminals"]["main"]["login"] == "5001"
        assert "idle" not in result["terminals"]
