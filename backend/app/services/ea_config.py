"""Remote config the MT5 bridge EA polls, so the EA file rarely has to change.

Only tunables are served: symbol list, refresh period, bar counts, and the
latest EA version with its checksum and download URL. The EA's safety inputs
(AllowTrading, AllowRealAccount, ExpectedLogin) are not part of this payload
and the EA has no code path that would read them from it.

Everything is environment-driven; an unset value is omitted so the EA keeps its
own setting:
    MOLIDO_EA_SYMBOLS            comma list; else the agents' dynamic universe
    MOLIDO_EA_REFRESH_SECONDS    5..300
    MOLIDO_EA_BAR_COUNT          50..5000
    MOLIDO_EA_INTRADAY_BAR_COUNT 50..2000
    MOLIDO_EA_TICK_COUNT         0..1000 (0 = no tick files; SC02 falls back to bars)
    MOLIDO_EA_DOWNLOAD_URL       where the updater fetches the .mq5
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import re
from typing import Any

from sqlalchemy.orm import Session

EA_FILE = pathlib.Path(__file__).resolve().parents[3] / "infra" / "mql5" / "MolidoBridge.mq5"
_VERSION = re.compile(r'#define MOLIDO_EA_VERSION "([0-9.]+)"')
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
    out["config_version"] = hashlib.sha256(
        repr(sorted((k, v) for k, v in out.items())).encode()).hexdigest()[:16]
    out["guards_remote_controllable"] = False
    if running_version:
        out["running_version"] = running_version
    return out
