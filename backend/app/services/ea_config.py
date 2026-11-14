"""Remote config the MT5 bridge EA polls, so the EA file rarely has to change.

Only tunables are served: symbol list, refresh period, bar counts, and the
latest EA version with its checksum and download URL. The EA's safety inputs
(AllowTrading, AllowRealAccount, AllowedLogins, AllowedRealLogins,
AccountProfile, EnableDemoScalper, ScalperKillSwitch) are not part of this payload
and the EA has no code path that would read them from it.

Everything is environment-driven; an unset value is omitted so the EA keeps its
own setting:
    MOLIDO_EA_SYMBOLS            comma list; else the agents' dynamic universe
    MOLIDO_EA_REFRESH_SECONDS    5..300
    MOLIDO_EA_BAR_COUNT          50..5000
    MOLIDO_EA_INTRADAY_BAR_COUNT 50..2000
    MOLIDO_EA_TICK_COUNT         0..1000 (0 = no tick files; SC02 falls back to bars)
    MOLIDO_EA_DOWNLOAD_URL       where the updater fetches the .mq5
    MOLIDO_EA_DEMO_RISK_CAPS     per-demo-login caps (login:risk:daily:dd:lots:pos:preset)
    MOLIDO_EA_NEWS_EVENTS        optional calendar rows (time|CCY|HIGH|name;...)
    MOLIDO_EA_CONSENSUS          optional veto rows (SYMBOL:buy|sell|wait|block:until)
    MOLIDO_EA_RANKING            optional rocket/agent ranks (SYMBOL:0-100;...)
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import re
from typing import Any

from sqlalchemy.orm import Session

EA_FILE = pathlib.Path(__file__).resolve().parents[3] / "infra" / "mql5" / "MolidoBridge.mq5"
_VERSION = re.compile(r'#define MOLIDO_EA_VERSION\s+"([0-9.]+)"')
_SYMBOL = re.compile(r"^[A-Za-z0-9._#-]{1,32}$")
LIMITS = {"refresh_seconds": (5, 300), "bar_count": (50, 5000), "intraday_bar_count": (50, 2000),
          "tick_count": (0, 1000)}
ENV = {"refresh_seconds": "MOLIDO_EA_REFRESH_SECONDS", "bar_count": "MOLIDO_EA_BAR_COUNT",
       "intraday_bar_count": "MOLIDO_EA_INTRADAY_BAR_COUNT", "tick_count": "MOLIDO_EA_TICK_COUNT"}


def ea_release(path: pathlib.Path = EA_FILE) -> dict[str, Any]:
    if not path.exists():
        return {"ea_latest_version": os.environ.get("MOLIDO_EA_LATEST_VERSION") or None,
                "ea_sha256": os.environ.get("MOLIDO_EA_SHA256") or None}
    raw = path.read_bytes()
    match = _VERSION.search(raw.decode("utf-8", errors="ignore"))
    return {"ea_latest_version": match.group(1) if match else None,
            "ea_sha256": hashlib.sha256(raw).hexdigest()}


def _symbols(session: Session | None) -> list[str]:
    raw = os.environ.get("MOLIDO_EA_SYMBOLS", "").strip()
    if raw:
        names = [s.strip() for s in raw.split(",")]
    elif session is not None:
        from app.services.agent_symbols import universe

        names = universe(session)["symbols"]
    else:
        names = []
    return [n for n in names if _SYMBOL.match(n)][:100]


# login:risk:daily:dd:lots:pos:preset  — demo accounts only. Values are clamped
# to the hard ceilings the expert also enforces. Real-account fields are ignored.
_HARD_CAPS = {"risk_pct": 0.5, "daily_loss_pct": 5.0, "max_dd_pct": 10.0,
              "max_lots": 2.0, "max_positions": 2}
_DEFAULT_DEMO_CAPS = "68531270:0.5:2:0:2:2:scalper"


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _parse_demo_caps_row(row: str) -> str | None:
    parts = [p.strip() for p in row.split(":")]
    if len(parts) < 6:
        return None
    try:
        login = int(parts[0])
    except ValueError:
        return None
    if login <= 0:
        return None
    try:
        risk = _clamp(float(parts[1]), 0.01, _HARD_CAPS["risk_pct"])
        daily = _clamp(float(parts[2]), 0.1, _HARD_CAPS["daily_loss_pct"])
        dd = _clamp(float(parts[3]), 0.0, _HARD_CAPS["max_dd_pct"])
        lots = _clamp(float(parts[4]), 0.01, _HARD_CAPS["max_lots"])
        pos = int(_clamp(float(parts[5]), 1, _HARD_CAPS["max_positions"]))
    except ValueError:
        return None
    preset = "ftmo" if len(parts) > 6 and parts[6].lower() in {"ftmo", "1"} else "scalper"
    return f"{login}:{risk:g}:{daily:g}:{dd:g}:{lots:g}:{pos}:{preset}"


def demo_risk_caps_csv(raw: str | None = None) -> str:
    """Build the per-login demo cap string the EA reads. Always includes 68531270."""
    text = raw if raw is not None else os.environ.get("MOLIDO_EA_DEMO_RISK_CAPS", "")
    rows = [r.strip() for r in text.replace(",", ";").split(";") if r.strip()]
    parsed = [c for r in rows if (c := _parse_demo_caps_row(r))]
    logins = {int(c.split(":", 1)[0]) for c in parsed}
    if 68531270 not in logins:
        parsed.insert(0, _DEFAULT_DEMO_CAPS)
    return ";".join(parsed)



_CONSENSUS_SIDE = {"buy", "sell", "wait", "block"}


def consensus_csv(raw: str | None = None) -> str:
    """Sanitize server consensus rows. This is a veto only; it cannot loosen filters."""
    text = raw if raw is not None else os.environ.get("MOLIDO_EA_CONSENSUS", "")
    rows: list[str] = []
    for row in text.replace(",", ";").split(";"):
        row = row.strip()
        if not row:
            continue
        parts = row.split(":", 2)
        if len(parts) < 2:
            continue
        symbol, side = parts[0].strip().upper(), parts[1].strip().lower()
        until = parts[2].strip() if len(parts) > 2 else ""
        if not _SYMBOL.match(symbol) or side not in _CONSENSUS_SIDE:
            continue
        rows.append(f"{symbol}:{side}:{until}" if until else f"{symbol}:{side}")
    return ";".join(rows)


def ranking_csv(raw: str | None = None) -> str:
    """Sanitize optional agent/Rocket ranks. Bonus only; cannot loosen EA filters."""
    text = raw if raw is not None else os.environ.get("MOLIDO_EA_RANKING", "")
    rows: list[str] = []
    for row in text.replace(",", ";").split(";"):
        row = row.strip()
        if not row or ":" not in row:
            continue
        name, _, val = row.partition(":")
        symbol = name.strip().upper()
        if not _SYMBOL.match(symbol):
            continue
        try:
            score = float(val.strip())
        except ValueError:
            continue
        score = max(0.0, min(100.0, score))
        rows.append(f"{symbol}:{score:g}")
    return ";".join(rows)


def config(session: Session | None = None, *, running_version: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"schema": 1}
    symbols = _symbols(session)
    if symbols:
        out["symbols_csv"] = ",".join(symbols)
    for key, env in ENV.items():
        value = os.environ.get(env, "").strip()
        if value.isdigit():
            lo, hi = LIMITS[key]
            out[key] = max(lo, min(hi, int(value)))
    out.update(ea_release())
    out["ea_download_url"] = os.environ.get("MOLIDO_EA_DOWNLOAD_URL") or None
    caps = demo_risk_caps_csv()
    if caps:
        out["demo_risk_caps_csv"] = caps
    news = os.environ.get("MOLIDO_EA_NEWS_EVENTS", "").strip()
    if news:
        out["news_events_csv"] = news
    consensus = consensus_csv()
    if consensus:
        out["consensus_csv"] = consensus
    ranks = ranking_csv()
    if ranks:
        out["ranking_csv"] = ranks
    out["config_version"] = hashlib.sha256(
        repr(sorted((k, v) for k, v in out.items())).encode()).hexdigest()[:16]
    out["guards_remote_controllable"] = False
    if running_version:
        out["running_version"] = running_version
    return out
