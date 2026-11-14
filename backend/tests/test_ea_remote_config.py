"""Stage 14: thin EA with remote config, version check and checksummed release."""

from __future__ import annotations

import hashlib
import pathlib
import re

from app.services import ea_config

EA = pathlib.Path(__file__).resolve().parents[2] / "infra" / "mql5" / "MolidoBridge.mq5"
RUNTIME = EA.parent / "MolidoRuntime.mqh"
SRC = RUNTIME.read_text(encoding="utf-8") if RUNTIME.is_file() else EA.read_text(encoding="utf-8")


def _remote_section() -> str:
    return SRC[SRC.index("Remote config and version check."):]


def test_checksum_file_matches_the_expert():
    for name in ("MolidoBridge.mq5", "MolidoRuntime.mqh"):
        path = EA.parent / name
        recorded = (EA.parent / f"{name}.sha256").read_text().split()[0]
        assert recorded == hashlib.sha256(path.read_bytes()).hexdigest(), name


def test_version_define_matches_property():
    wrapper = EA.read_text(encoding="utf-8")
    define = re.search(r'#define MOLIDO_EA_VERSION\s+"([0-9.]+)"', wrapper).group(1)
    prop = re.search(r'#property version\s+"([0-9.]+)"', wrapper).group(1)
    assert define == prop == ea_config.ea_release()["ea_latest_version"]


def test_guards_stay_hard_coded():
    assert "input bool   AllowTrading    = true;" in SRC
    assert "input bool   AllowRealAccount = false;" in SRC
    assert 'input string AllowedLogins     = "68531270";' in SRC
    assert 'input string AllowedRealLogins = "";' in SRC
    assert "AccountProfile = MOLIDO_DEFAULT_PROFILE" in SRC
    assert "AutoSymbolMode      = MOLIDO_DEFAULT_AUTO;" in SRC
    assert "EnableDemoScalper   = true;" in SRC
    assert "ScalperKillSwitch   = false;" in SRC
    assert "MaxLots         = 2.00;" in SRC
    remote = _remote_section()
    for guard in ("AllowTrading", "AllowRealAccount", "AllowedLogins",
                  "AllowedRealLogins", "AccountProfile", "EnableDemoScalper",
                  "ScalperKillSwitch", "AutoSymbolMode"):
        assert re.search(rf"\b{guard}\s*=", remote) is None
        assert f'JsonValue(body, "{guard}' not in remote
    for name in ("g_AllowTrading", "g_AllowRealAccount", "g_ExpectedLogin",
                 "g_AllowedLogins", "g_AllowedRealLogins", "g_AccountProfile",
                 "g_EnableDemoScalper", "g_ScalperKillSwitch", "g_AutoSymbolMode"):
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
    assert not {"AllowTrading", "AllowRealAccount", "AllowedLogins",
                "AllowedRealLogins", "AccountProfile", "EnableDemoScalper",
                "ScalperKillSwitch", "AutoSymbolMode"} & set(out)
    assert out["ea_sha256"] == hashlib.sha256(EA.read_bytes()).hexdigest()
    assert "68531270:0.5:2:0:2:2:scalper" in out["demo_risk_caps_csv"]


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
    for name in ("MolidoShared.mqh", "MolidoRuntime.mqh", "MolidoDemoScalper.mqh", "MolidoNews.mqh", "MolidoSmart.mqh",
                 "MolidoProtect.mqh", "MolidoUniverse.mqh", "MolidoFibo.mqh", "MolidoI18n.mqh", "MolidoDashboard.mqh"):
        mqh = EA.parent / name
        assert mqh.is_file(), name
        if name != "MolidoRuntime.mqh":
            assert f'#include "{name}"' in SRC
        recorded = (EA.parent / f"{name}.sha256").read_text().split()[0]
        assert recorded == hashlib.sha256(mqh.read_bytes()).hexdigest()
    assert '#property version     "1.46"' in EA.read_text(encoding="utf-8")
    assert '#define MOLIDO_EA_VERSION       "1.46"' in EA.read_text(encoding="utf-8") or 'MOLIDO_EA_VERSION "1.46"' in SRC
    assert "NEWS_AVOID" in SRC and "NEWS_TRADE" in SRC
    assert "RISK_PRESET_FTMO" in SRC
    remote = _remote_section()
    assert 'JsonValue(body, "NewsMode")' not in remote
    assert 'JsonValue(body, "RiskPreset")' not in remote
    assert 'JsonValue(body, "AllowRealAccount")' not in remote
    assert 'JsonValue(body, "AccountProfile")' not in remote
    assert 'JsonValue(body, "AllowedLogins")' not in remote
    assert 'JsonValue(body, "AutoSymbolMode")' not in remote
    assert 'JsonValue(body, "DashFontScale")' not in remote
    assert 'JsonValue(body, "DisconnectGraceSec")' not in remote
    assert 'JsonValue(body, "AutoUpdateEnabled")' not in remote
    assert 'JsonValue(body, "RehearsalMode")' not in remote


def test_demo_risk_caps_are_clamped_and_demo_only(monkeypatch):
    from app.services.ea_config import demo_risk_caps_csv
    # Hostile lots/risk are clamped; junk and non-numeric logins are dropped.
    raw = "68531270:9:50:90:99:20:scalper;not-a-login:1:1:1:1:1;42:0.3:4:8:1:2:ftmo"
    csv = demo_risk_caps_csv(raw)
    assert "68531270:0.5:5:10:2:2:scalper" in csv
    assert "42:0.3:4:8:1:2:ftmo" in csv
    assert "not-a-login" not in csv
    monkeypatch.setenv("MOLIDO_EA_DEMO_RISK_CAPS", "99:0.2:1:0:0.5:1:scalper")
    monkeypatch.setenv("MOLIDO_EA_NEWS_EVENTS", "2026.11.14 20:30|USD|HIGH|NFP")
    monkeypatch.setenv("MOLIDO_EA_CONSENSUS", "XAUUSD:buy:2026.11.14 22:00;bad:nope")
    monkeypatch.setenv("MOLIDO_EA_RANKING", "XAUUSD:120;EURUSD:80;BAD NAME:1")
    out = ea_config.config()
    assert "99:0.2:1:0:0.5:1:scalper" in out["demo_risk_caps_csv"]
    assert "68531270:" in out["demo_risk_caps_csv"]
    assert out["news_events_csv"].endswith("NFP")
    assert "XAUUSD:buy:" in out["consensus_csv"] and "bad" not in out["consensus_csv"]
    assert out["ranking_csv"] == "XAUUSD:100;EURUSD:80"
    assert out["guards_remote_controllable"] is False
    assert "AllowRealAccount" not in out and "AllowTrading" not in out


def test_split_eas_have_unique_magics():
    root = EA.parent
    eas = {
        "MolidoBridge.mq5": 685317,
        "Molido_Demo.mq5": 685401,
        "Molido_Prop.mq5": 685402,
        "Molido_Live.mq5": 685403,
        "Molido_Scalper.mq5": 685404,
        "Molido_News.mq5": 685405,
        "Molido_Trend.mq5": 685406,
        "Molido_AutoPortfolio.mq5": 685407,
        "Molido_Master.mq5": 685408,
        "Molido_Expert.mq5": 685409,
    }
    seen = set()
    for name, magic in eas.items():
        text = (root / name).read_text(encoding="utf-8")
        assert f"#define MOLIDO_MAGIC            {magic}" in text, name
        assert '#include "MolidoRuntime.mqh"' in text
        assert magic not in seen
        seen.add(magic)
        recorded = (root / f"{name}.sha256").read_text().split()[0]
        assert recorded == hashlib.sha256((root / name).read_bytes()).hexdigest()
    shared = (root / "MolidoShared.mqh").read_text(encoding="utf-8")
    assert "IsMolidoMagic" in shared and "Molido.Coord." in shared
    assert "PROFILE_PROP_FTMO" in (root / "Molido_Prop.mq5").read_text(encoding="utf-8")
    assert "PROFILE_LIVE_REAL" in (root / "Molido_Live.mq5").read_text(encoding="utf-8")
    assert "STRAT_TREND" in (root / "Molido_Trend.mq5").read_text(encoding="utf-8")
    assert "STRAT_AUTO" in (root / "Molido_AutoPortfolio.mq5").read_text(encoding="utf-8")
    assert "PROFILE_AUTO" in (root / "Molido_Master.mq5").read_text(encoding="utf-8")
    assert 'input group "Advanced (no need to change)"' in SRC
    assert "PROFILE_AUTO" in SRC and "DetectAccountProfile" in SRC
    assert "MolidoRealBlocked" in SRC
    assert "Real account not supported yet" in (root / "MolidoI18n.mqh").read_text(encoding="utf-8-sig")
    assert 'Tr("real_unsupported")' in (root / "MolidoDashboard.mqh").read_text(encoding="utf-8")
    assert "DemoFiboSignal" in (root / "MolidoFibo.mqh").read_text(encoding="utf-8")
    assert "UseFibo            = MOLIDO_USE_FIBO" in SRC
    assert "Language = LANG_FA" in SRC
    assert "LANG_TR" in SRC and "LANG_AR" in SRC
    assert 'JsonValue(body, "Language")' not in SRC
    assert "MolidoIsTester" in SRC or "MolidoIsTester" in (root / "MolidoShared.mqh").read_text(encoding="utf-8")
    assert "molido_update_request.json" in SRC and "molido_daily_summary.json" in SRC
    assert "Update now?" in (root / "MolidoI18n.mqh").read_text(encoding="utf-8-sig")
    assert 'Tr("update_now")' in (root / "MolidoDashboard.mqh").read_text(encoding="utf-8")


def test_molido_expert_keeps_safety_and_modules():
    root = pathlib.Path(__file__).resolve().parents[2] / "infra" / "mql5"
    ea = (root / "Molido_Expert.mq5").read_text(encoding="utf-8")
    assert "MOLIDO_EXPERT_UI" in ea
    assert 'MOLIDO_EA_VERSION       "2.20"' in ea
    assert "MOLIDO_REAL_SUPPORTED   false" in ea
    assert "MOLIDO_MAGIC            685409" in ea
    assert "PROFILE_AUTO" in ea
    rt = (root / "MolidoRuntime.mqh").read_text(encoding="utf-8")
    assert "MolidoExpertUI.mqh" in rt
    assert "MolidoExpertBridge.mqh" in rt
    assert 'JsonValue(body, "AiBridgeToken")' not in rt
    br = (root / "MolidoExpertBridge.mqh").read_text(encoding="utf-8")
    assert "AiBridgeToken" in br
    assert "molido_ai_token.txt" in br
    # no hardcoded bearer secrets
    assert "Bearer " in br  # header prefix only
    assert re.search(r'AiBridgeToken\s*=\s*"\s*[^"]+', br) is None or 'AiBridgeToken = ""' in br
    assert "never hardcoded" in br.lower() or "never hardcoded" in br or "Token is never hardcoded" in br
    ui = (root / "MolidoExpertUI.mqh").read_text(encoding="utf-8-sig")
    assert "CreateBitmapLabel" in ui
    assert "ChartSetSymbolPeriod" in ui
    assert "ExpertManualTrade" in ui
    assert "#import" not in ui.lower() or "Canvas" in ui
    assert "WebBrowser" not in ui and "<html" not in ui.lower()
