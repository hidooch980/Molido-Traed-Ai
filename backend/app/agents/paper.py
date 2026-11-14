"""Paper trades for agent signals: opened only on a risk-gate APPROVE/REDUCE, never sent.

Pure functions; persistence lives in `app/services/agent_paper.py`. A paper trade
fills at the middle of the entry zone at the signal's bar close and is resolved
on later closed bars only, with a bar touching both levels counted as a stop.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any

from app.agents.analyzers.bars import Candle

PAPER_ONLY = True


@dataclass(frozen=True)
class PaperTrade:
    trade_id: str
    symbol: str
    direction: str
    timeframe: str
    opened_at: str
    entry: float
    stop_loss: float
    take_profit: float
    risk_pct: float
    risk_amount: float | None
    verdict: str
    rank: str
    mode: str = "paper"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def open_trade(signal: dict[str, Any], decision: dict[str, Any]) -> PaperTrade | None:
    if decision.get("verdict") not in ("APPROVE", "REDUCE"):
        return None
    zone = signal["entry_zone"]
    key = f"{signal['symbol']}|{signal['timeframe']}|{signal['signal_timestamp']}"
    return PaperTrade(
        trade_id=hashlib.sha256(key.encode()).hexdigest()[:24],
        symbol=signal["symbol"], direction=signal["direction"],
        timeframe=signal["timeframe"], opened_at=signal["signal_timestamp"],
        entry=(zone[0] + zone[1]) / 2, stop_loss=signal["stop_loss"],
        take_profit=signal["take_profit"], risk_pct=decision.get("risk_pct", 0.0),
        risk_amount=decision.get("risk_amount"), verdict=decision["verdict"],
        rank=signal.get("rocket_rank", ""),
    )


def resolve(trade: dict[str, Any], later: list[Candle]) -> dict[str, Any]:
    """Outcome in R from bars that opened after the trade did."""
    entry, stop, target = trade["entry"], trade["stop_loss"], trade["take_profit"]
    risk = abs(entry - stop)
    if risk == 0:
        return {"result": "invalid"}
    sign = 1 if trade["direction"] == "BUY" else -1
    for b in later:
        hit_stop = b.low <= stop if sign > 0 else b.high >= stop
        hit_tp = b.high >= target if sign > 0 else b.low <= target
        if hit_stop:
            return {"result": "stop", "r": -1.0, "closed_bar": b.open_time.isoformat()}
        if hit_tp:
            return {"result": "target", "r": round(abs(target - entry) / risk, 4),
                    "closed_bar": b.open_time.isoformat()}
    if not later:
        return {"result": "open"}
    last = later[-1].close
    return {"result": "open", "open_r": round(sign * (last - entry) / risk, 4)}
