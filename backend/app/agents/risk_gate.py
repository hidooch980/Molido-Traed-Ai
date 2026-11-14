"""Independent agent Risk Brain: APPROVE / REDUCE / BLOCK, deterministic.

This gate reviews what agents *propose* (RT10 rocket signals, council
recommendations). It is final for the agent layer: no agent field, flag or
confidence can raise its verdict, and nothing it receives is read except the
plain numbers it needs. Missing or stale inputs are a BLOCK, never a guess.

It does not replace `app/brain/risk.py`, which remains the authority for the
existing execution path; this module is shadow only and sends nothing anywhere.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Verdict(StrEnum):
    APPROVE = "APPROVE"
    REDUCE = "REDUCE"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class RiskLimits:
    risk_per_trade_pct: float = 0.5
    max_daily_loss_pct: float = 4.0
    reduce_at_daily_loss_fraction: float = 0.5
    max_open_positions: int = 3
    min_rr: float = 1.2
    max_spread_atr_fraction: float = 0.25
    min_rank_approve: str = "R4"
    min_rank_reduce: str = "R3"
    reduce_factor: float = 0.5


@dataclass(frozen=True)
class RiskContext:
    """What the account looks like right now. None means 'not known'."""

    equity: float | None = None
    daily_pnl_pct: float | None = None
    open_symbols: tuple[str, ...] | None = None
    data_fresh: bool | None = None
    kill_switch: bool = False
    high_impact_news_soon: bool = False
    source: str = "unknown"


@dataclass(frozen=True)
class RiskDecision:
    verdict: Verdict
    reasons: list[str]
    risk_pct: float = 0.0
    risk_amount: float | None = None
    size_factor: float = 0.0
    checks: dict[str, bool] = field(default_factory=dict)
    authority: str = "agent-risk-gate (shadow; app/brain/risk.py stays final for execution)"

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["verdict"] = self.verdict.value
        return out


def _num(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _block(reasons: list[str], checks: dict[str, bool]) -> RiskDecision:
    return RiskDecision(Verdict.BLOCK, reasons, checks=checks)


def review_signal(
    signal: dict[str, Any], ctx: RiskContext, limits: RiskLimits = RiskLimits()
) -> RiskDecision:
    """Review one RocketSignal (as dict). Only numeric fields are read."""
    checks: dict[str, bool] = {}
    if ctx.kill_switch:
        return _block(["kill switch is engaged"], {"kill_switch": False})
    direction = signal.get("direction")
    entry_zone = signal.get("entry_zone") or ()
    entry = _num(sum(entry_zone) / len(entry_zone)) if entry_zone else None
    stop, target = _num(signal.get("stop_loss")), _num(signal.get("take_profit"))
    missing = [name for name, v in (("entry", entry), ("stop_loss", stop),
                                    ("take_profit", target)) if v is None]
    if direction not in ("BUY", "SELL"):
        missing.append("direction")
    if ctx.equity is None or ctx.equity <= 0:
        missing.append("account equity")
    if ctx.daily_pnl_pct is None:
        missing.append("daily P&L")
    if ctx.open_symbols is None:
        missing.append("open positions")
    if ctx.data_fresh is not True:
        missing.append("fresh market data")
    checks["inputs_complete"] = not missing
    if missing:
        return _block([f"missing: {', '.join(missing)}"], checks)
    assert entry is not None and stop is not None and target is not None
    assert ctx.equity is not None and ctx.daily_pnl_pct is not None
    assert ctx.open_symbols is not None

    sign = 1 if direction == "BUY" else -1
    risk_dist, reward_dist = sign * (entry - stop), sign * (target - entry)
    checks["stop_on_correct_side"] = risk_dist > 0 and reward_dist > 0
    if not checks["stop_on_correct_side"]:
        return _block(["stop or target on the wrong side of entry"], checks)

    reasons: list[str] = []
    factor = 1.0
    spread = _num(signal.get("spread")) or 0.0
    slip = _num(signal.get("slippage_estimate")) or 0.0
    rr = (reward_dist - spread - slip) / (risk_dist + spread + slip)
    checks["rr"] = rr >= limits.min_rr
    if not checks["rr"]:
        return _block([f"net R:R {rr:.2f} < {limits.min_rr}"], checks)

    atr = _num(signal.get("volatility_atr"))
    if atr and spread:
        checks["spread"] = spread <= limits.max_spread_atr_fraction * atr
        if not checks["spread"]:
            return _block([f"spread {spread:g} > {limits.max_spread_atr_fraction:.0%} ATR"],
                          checks)

    loss = -min(0.0, ctx.daily_pnl_pct)
    checks["daily_loss"] = loss < limits.max_daily_loss_pct
    if not checks["daily_loss"]:
        return _block([f"daily loss {loss:.2f}% reached limit {limits.max_daily_loss_pct}%"],
                      checks)
    if loss >= limits.reduce_at_daily_loss_fraction * limits.max_daily_loss_pct:
        factor *= limits.reduce_factor
        reasons.append(f"daily loss {loss:.2f}% past reduce threshold")

    symbol = str(signal.get("symbol", "")).upper()
    open_syms = {s.upper() for s in ctx.open_symbols}
    checks["no_duplicate"] = symbol not in open_syms
    if not checks["no_duplicate"]:
        return _block([f"{symbol} already has an open position"], checks)
    checks["position_cap"] = len(open_syms) < limits.max_open_positions
    if not checks["position_cap"]:
        return _block([f"{len(open_syms)} positions open (cap {limits.max_open_positions})"],
                      checks)

    rank = str(signal.get("rocket_rank", "R1"))
    if rank < limits.min_rank_reduce:
        return _block([f"rank {rank} below {limits.min_rank_reduce}"], checks)
    if rank < limits.min_rank_approve:
        factor *= limits.reduce_factor
        reasons.append(f"rank {rank} below {limits.min_rank_approve}")
    if ctx.high_impact_news_soon:
        factor *= limits.reduce_factor
        reasons.append("high-impact news inside the window")

    risk_pct = round(limits.risk_per_trade_pct * factor, 4)
    verdict = Verdict.APPROVE if factor == 1.0 else Verdict.REDUCE
    return RiskDecision(verdict, reasons or ["all checks passed"], risk_pct,
                        round(ctx.equity * risk_pct / 100, 2), factor, checks)


def review_council(
    result: dict[str, Any], ctx: RiskContext, limits: RiskLimits = RiskLimits()
) -> RiskDecision:
    """A council recommendation carries no stop or target, so it can never be approved
    on its own; directional output is BLOCKed until it arrives as a full signal."""
    verdict = result.get("verdict")
    raw = verdict.get("direction") if isinstance(verdict, dict) else result.get("recommendation")
    rec = str(raw or "").upper()
    if ctx.kill_switch:
        return _block(["kill switch is engaged"], {"kill_switch": False})
    if rec in ("BUY", "SELL"):
        return _block(["council output has no entry/stop/target; needs a full signal"],
                      {"inputs_complete": False})
    return _block([f"nothing to approve: council said {rec or 'nothing'}"], {})


__all__ = ["RiskContext", "RiskDecision", "RiskLimits", "Verdict", "review_council",
           "review_signal"]
