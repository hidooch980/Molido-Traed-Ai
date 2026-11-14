"""Backtest gate (t57u): a new strategy/EA version is backtested on stored
candles before it is promoted.

The strategy version is a hash of the Rocket rules + walk-forward code. On a
new hash, the fixed rules are walked forward over stored candles of a few liquid
symbols (`agents.walkforward`, out-of-sample folds, nothing fitted). Verdicts:

* PASS        - >= MIN_TRADES resolved trades and average R > 0.
* FAIL        - >= MIN_TRADES and average R below -FAIL_MARGIN: paper opens stop
                (when MOLIDO_AGENT_BACKTEST_GATE is on) and nothing promotes.
* INSUFFICIENT - too few trades to judge: paper may run (paper is where evidence
                is gathered) but nothing beyond paper is promoted.

EA releases: the EA is a data bridge with no trading logic, so its gate is
integrity (sha256 of the release file) plus the strategy it feeds not failing;
the remote config advertises a new EA version only after that record exists.
Results are agent memory (kind "strategy", source_ref "backtest_gate:<kind>:<v>").
"""

from __future__ import annotations

import hashlib
import os
import pathlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import memory
from app.core.enums import Timeframe
from app.models.agent_memory import AgentMemoryEntry

FLAG = "MOLIDO_AGENT_BACKTEST_GATE"
MIN_TRADES = 30
FAIL_MARGIN = 0.05
SYMBOLS = ("XAUUSD", "EURUSD", "GBPUSD")
_ROOT = pathlib.Path(__file__).resolve().parents[1]
STRATEGY_FILES = ("agents/analyzers/rocket.py", "agents/walkforward.py", "services/agent_scan.py")


def enabled() -> bool:
    return os.getenv(FLAG, "").strip().lower() in {"1", "true", "yes", "on"}


def strategy_version(root: pathlib.Path = _ROOT) -> str:
    h = hashlib.sha256()
    for rel in STRATEGY_FILES:
        p = root / rel
        h.update(rel.encode())
        h.update(p.read_bytes().replace(b"\r\n", b"\n") if p.exists() else b"-")
    return h.hexdigest()[:16]


def _ref(kind: str, version: str) -> str:
    return f"backtest_gate:{kind}:{version}"[:128]


def result(session: Session, kind: str, version: str) -> dict[str, Any] | None:
    row = session.scalar(select(AgentMemoryEntry)
                         .where(AgentMemoryEntry.kind == "strategy",
                                AgentMemoryEntry.source_ref == _ref(kind, version))
                         .order_by(AgentMemoryEntry.created_at.desc()).limit(1))
    return row.content if row else None


def verdict(trades: int, avg_r: float | None) -> str:
    if trades < MIN_TRADES or avg_r is None:
        return "INSUFFICIENT"
    if avg_r > 0:
        return "PASS"
    return "FAIL" if avg_r < -FAIL_MARGIN else "INSUFFICIENT"


def run_strategy_gate(session: Session, *, version: str | None = None, backtest: Any = None,
                      symbols: tuple[str, ...] = SYMBOLS, lookback: int = 1500,
                      now: datetime | None = None) -> dict[str, Any]:
    version = version or strategy_version()
    done = result(session, "strategy", version)
    if done is not None:
        return done
    if backtest is None:
        from app.services.agent_walkforward import historical as backtest
    per = []
    rs_n = 0
    total = 0.0
    for sym in symbols:
        out = backtest(session, sym, Timeframe.H1, folds=4, lookback=lookback)
        o = out.get("overall") or {}
        per.append({"symbol": sym, "bars": out.get("bars"), "error": out.get("error"),
                    "n": o.get("n", 0), "avg_r": o.get("avg_r"), "folds": out.get("folds")})
        rs_n += int(o.get("n") or 0)
        total += float(o.get("total_r") or 0.0)
    avg = total / rs_n if rs_n else None
    content = {"kind": "strategy", "version": version, "verdict": verdict(rs_n, avg),
               "trades": rs_n, "avg_r": round(avg, 4) if avg is not None else None,
               "symbols": per, "as_of": (now or datetime.now(UTC)).isoformat(),
               "rules": {"min_trades": MIN_TRADES, "fail_below_avg_r": -FAIL_MARGIN},
               "costs": "spread not included", "data": "stored candles, out-of-sample folds"}
    memory.remember(session, "BRAIN-01", "strategy",
                    f"backtest gate strategy {version}: {content['verdict']}",
                    content=content, source_ref=_ref("strategy", version))
    return content


def paper_allowed(session: Session) -> tuple[bool, str]:
    if not enabled():
        return True, "gate off"
    r = result(session, "strategy", strategy_version())
    if r is None:
        return True, "strategy version not backtested yet"
    return r["verdict"] != "FAIL", f"strategy {r['version']}: {r['verdict']}"


def run_ea_gate(session: Session, release: dict[str, Any]) -> dict[str, Any] | None:
    version, sha = release.get("ea_latest_version"), release.get("ea_sha256")
    if not version or not sha:
        return None
    key = f"{version}:{sha[:16]}"
    done = result(session, "ea", key)
    if done is not None:
        return done
    strat = result(session, "strategy", strategy_version())
    v = "FAIL" if strat and strat["verdict"] == "FAIL" else ("PASS" if strat else None)
    if v is None:
        return None
    content = {"kind": "ea", "version": version, "sha256": sha, "verdict": v,
               "strategy": strat["version"] if strat else None,
               "note": "EA is a data bridge; gate = integrity + its strategy backtest"}
    memory.remember(session, "BRAIN-01", "strategy", f"backtest gate EA {version}: {v}",
                    content=content, source_ref=_ref("ea", key))
    return content


def ea_advertise(session: Session | None, release: dict[str, Any]) -> dict[str, Any]:
    """Release fields for the EA remote config; withheld until the EA gate passed."""
    if session is None or not enabled() or not release.get("ea_latest_version"):
        return release
    sha = release.get("ea_sha256") or ""
    r = result(session, "ea", f"{release['ea_latest_version']}:{sha[:16]}")
    if r and r.get("verdict") == "PASS":
        return release
    return {"ea_latest_version": None, "ea_sha256": None,
            "ea_gate": r.get("verdict") if r else "PENDING"}


def status(session: Session) -> dict[str, Any]:
    rows = session.scalars(select(AgentMemoryEntry)
                           .where(AgentMemoryEntry.kind == "strategy",
                                  AgentMemoryEntry.source_ref.like("backtest_gate:%"))
                           .order_by(AgentMemoryEntry.created_at.desc()).limit(20))
    return {"enabled": enabled(), "strategy_version": strategy_version(),
            "current": result(session, "strategy", strategy_version()),
            "history": [r.content for r in rows]}
