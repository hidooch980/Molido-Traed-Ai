"""The autopilot view reads every terminal, not the default bridge folder.

Virtual-tester pilot, 2026-09-14: a working demo account under key `main`
showed on its own page, while the autopilot page called it undescribable.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from app.execution import autopilot


def _terminal(directory, login, trade_mode=0):
    directory.mkdir()
    stamp = datetime.now(UTC).strftime("%Y.%m.%d %H:%M:%S")
    (directory / "molido_heartbeat.json").write_text(json.dumps({"published_at": stamp}))
    (directory / "molido_account.json").write_text(
        json.dumps({"login": login, "connected": True, "trade_mode": trade_mode})
    )


def test_a_fleet_of_demo_accounts_is_open(tmp_path, monkeypatch):
    _terminal(tmp_path / "a", 1)
    _terminal(tmp_path / "b", 2)
    monkeypatch.setenv("MOLIDO_MT5_BRIDGE_DIRS", f"a={tmp_path / 'a'},b={tmp_path / 'b'}")

    ok, why = autopilot.fleet_account_gate()

    assert ok is True
    assert "a:" in why and "b:" in why


def test_one_terminal_answers_as_itself(tmp_path, monkeypatch):
    _terminal(tmp_path / "main", 90000001)
    monkeypatch.setenv("MOLIDO_MT5_BRIDGE_DIRS", f"main={tmp_path / 'main'}")

    ok, why = autopilot.fleet_account_gate()

    assert ok is True
    assert "cannot describe" not in why


def test_a_silent_terminal_is_still_refused(tmp_path, monkeypatch):
    (tmp_path / "dead").mkdir()
    monkeypatch.setenv("MOLIDO_MT5_BRIDGE_DIRS", f"dead={tmp_path / 'dead'}")

    ok, why = autopilot.fleet_account_gate()

    assert ok is False
    assert "cannot describe" in why
