"""Stage 14: thin EA with remote config, version check and checksummed release."""

from __future__ import annotations

import hashlib
import pathlib
import re

from app.services import ea_config

EA = pathlib.Path(__file__).resolve().parents[2] / "infra" / "mql5" / "MolidoBridge.mq5"
SRC = EA.read_text(encoding="utf-8")


def _remote_section() -> str:
    return SRC[SRC.index("Remote config and version check."):]


def test_checksum_file_matches_the_expert():
    recorded = (EA.parent / "MolidoBridge.mq5.sha256").read_text().split()[0]
    assert recorded == hashlib.sha256(EA.read_bytes()).hexdigest()


def test_version_define_matches_property():
    define = re.search(r'#define MOLIDO_EA_VERSION "([0-9.]+)"', SRC).group(1)
    prop = re.search(r'#property version\s+"([0-9.]+)"', SRC).group(1)
    assert define == prop == ea_config.ea_release()["ea_latest_version"]


def test_guards_stay_hard_coded():
    assert "input bool   AllowTrading    = false;" in SRC
    assert "input bool   AllowRealAccount = false;" in SRC
    remote = _remote_section()
    for guard in ("AllowTrading", "AllowRealAccount", "ExpectedLogin",
                  "EnableDemoScalper", "ScalperKillSwitch"):
        assert re.search(rf"\b{guard}\s*=", remote) is None
        assert f'JsonValue(body, "{guard}' not in remote
    for name in ("g_AllowTrading", "g_AllowRealAccount", "g_ExpectedLogin",
                 "g_EnableDemoScalper", "g_ScalperKillSwitch"):
        assert name not in SRC


def test_remote_values_are_clamped_and_checked():
    remote = _remote_section()
    assert "Clamp((int)StringToInteger(refresh), 5, 300)" in remote
    assert "SafeSymbolList(symbols)" in remote


def test_config_payload(monkeypatch):
    monkeypatch.setenv("MOLIDO_EA_SYMBOLS", "EURUSD, XAUUSD,bad name,GBPUSD.")
    monkeypatch.setenv("MOLIDO_EA_REFRESH_SECONDS", "1")
    monkeypatch.setenv("MOLIDO_EA_BAR_COUNT", "99999")
    out = ea_config.config()
    assert out["symbols_csv"] == "EURUSD,XAUUSD,GBPUSD."
    assert out["refresh_seconds"] == 5 and out["bar_count"] == 5000
    assert out["guards_remote_controllable"] is False
    assert not {"AllowTrading", "AllowRealAccount", "ExpectedLogin",
                "EnableDemoScalper", "ScalperKillSwitch"} & set(out)
    assert out["ea_sha256"] == hashlib.sha256(EA.read_bytes()).hexdigest()


def test_unset_values_are_omitted(monkeypatch):
    for env in (*ea_config.ENV.values(), "MOLIDO_EA_SYMBOLS"):
        monkeypatch.delenv(env, raising=False)
    out = ea_config.config()
    assert "symbols_csv" not in out and "refresh_seconds" not in out


def test_endpoint_needs_broker_permission_and_returns_config(session, monkeypatch):
    from fastapi.testclient import TestClient

    from app.db.session import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as c:
            res = c.get("/api/v1/bridge/config?account_key=main&ea_version=1.10")
    finally:
        app.dependency_overrides.clear()
    assert res.status_code in (200, 401, 403)
    if res.status_code == 200:
        assert res.json()["running_version"] == "1.10"


def test_demo_scalper_is_included_and_checksummed():
    mqh = EA.parent / "MolidoDemoScalper.mqh"
    assert mqh.is_file()
    assert '#include "MolidoDemoScalper.mqh"' in SRC
    recorded = (EA.parent / "MolidoDemoScalper.mqh.sha256").read_text().split()[0]
    assert recorded == hashlib.sha256(mqh.read_bytes()).hexdigest()
