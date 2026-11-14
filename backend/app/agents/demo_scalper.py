"""Demo-only scalper risk profile for RoboForex MT5 login 68531270.

Sized for a 200_000 USD demo account:

* risk per trade <= 0.5%  (~$1_000 at 200k)
* daily loss cap 2%       (~$4_000 at 200k)
* max lots 2.0, still bounded by the 0.5% stop-based size
* at most 2 open positions
* stop-loss mandatory, spread filter, kill switch
* refuse unless ACCOUNT_TRADE_MODE_DEMO and login 68531270
* missing or invalid inputs => no trade (BLOCK)

The MQL expert ``infra/mql5/MolidoDemoScalper.mqh`` mirrors these numbers.
This module is the testable reference. It does not place orders and is not
wired into the live server execution path.
"""

from __future__ import annotations

import math
from typing import Any

from app.agents.risk_gate import RiskContext, RiskDecision, RiskLimits, Verdict, review_signal

DEMO_LOGIN = 68531270
ACCOUNT_TRADE_MODE_DEMO = 0
ACCOUNT_TRADE_MODE_CONTEST = 1
ACCOUNT_TRADE_MODE_REAL = 2

RISK_PER_TRADE_PCT = 0.5
MAX_DAILY_LOSS_PCT = 2.0
REDUCE_AT_DAILY_LOSS_FRACTION = 0.5
REDUCE_FACTOR = 0.5
MAX_OPEN_POSITIONS = 2
MIN_RR = 1.2
MAX_SPREAD_ATR_FRACTION = 0.15
MAX_LOTS = 2.0
SL_ATR_MULT = 1.0
TP_ATR_MULT = 1.5
MAX_ENTRIES_PER_DAY = 8


def demo_limits() -> RiskLimits:
    """Scalper has no rocket rank, so rank floors are set not to interfere."""
    return RiskLimits(
        risk_per_trade_pct=RISK_PER_TRADE_PCT,
        max_daily_loss_pct=MAX_DAILY_LOSS_PCT,
        reduce_at_daily_loss_fraction=REDUCE_AT_DAILY_LOSS_FRACTION,
        max_open_positions=MAX_OPEN_POSITIONS,
        min_rr=MIN_RR,
        max_spread_atr_fraction=MAX_SPREAD_ATR_FRACTION,
        min_rank_approve="R1",
        min_rank_reduce="R1",
        reduce_factor=REDUCE_FACTOR,
    )


def account_is_allowed(trade_mode: int | None, login: int | None) -> bool:
    """Hard gate: demo mode and this login only. Anything else is a refusal."""
    if trade_mode is None or login is None:
        return False
    try:
        mode = int(trade_mode)
        acc = int(login)
    except (TypeError, ValueError):
        return False
    return mode == ACCOUNT_TRADE_MODE_DEMO and acc == DEMO_LOGIN


def _block(reason: str, checks: dict[str, bool] | None = None) -> RiskDecision:
    return RiskDecision(Verdict.BLOCK, [reason], checks=checks or {},
                        authority="demo-scalper-risk-brain")


def _finite_positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def size_lots(
    *,
    balance: float | None,
    risk_pct: float | None,
    sl_distance: float | None,
    tick_size: float | None,
    tick_value: float | None,
    max_lots: float = MAX_LOTS,
    lot_step: float = 0.01,
    min_lot: float = 0.01,
    symbol_max_lot: float | None = None,
) -> float | None:
    """Lots from 0.5%-of-balance risk and stop distance, then the 2.0 lot cap.

    Returns None (no trade) on missing or invalid inputs, or when even the
    minimum lot would risk more than the budget.
    """
    values = (balance, risk_pct, sl_distance, tick_size, tick_value, max_lots, lot_step, min_lot)
    parsed: list[float] = []
    for value in values:
        number = _finite_positive(value)
        if number is None:
            return None
        parsed.append(number)
    balance_, risk_pct_, sl_distance_, tick_size_, tick_value_, max_lots_, lot_step_, min_lot_ = parsed
    cap = max_lots_
    if symbol_max_lot is not None:
        symbol_cap = _finite_positive(symbol_max_lot)
        if symbol_cap is None:
            return None
        cap = min(cap, symbol_cap)
    risk_money = balance_ * (risk_pct_ / 100.0)
    ticks = sl_distance_ / tick_size_
    if ticks <= 0 or tick_value_ <= 0:
        return None
    raw = risk_money / (ticks * tick_value_)
    raw = min(raw, cap)
    lots = math.floor(raw / lot_step_ + 1e-12) * lot_step_
    lots = round(lots, 8)
    while lots >= min_lot_ - 1e-12:
        actual = lots * ticks * tick_value_
        if actual <= risk_money + 1e-8:
            return round(lots, 8)
        lots = round(lots - lot_step_, 8)
    return None


def review_demo_trade(
    *,
    trade_mode: int | None,
    login: int | None,
    kill_switch: bool,
    signal: dict[str, Any],
    ctx: RiskContext,
    entries_today: int | None = 0,
    limits: RiskLimits | None = None,
) -> RiskDecision:
    """Account gate first, then the Risk Brain. BLOCK wins. Missing data blocks."""
    if not account_is_allowed(trade_mode, login):
        return _block("not demo login 68531270 (ACCOUNT_TRADE_MODE_DEMO required)",
                      {"demo_account": False})
    if kill_switch:
        return _block("kill switch is engaged", {"kill_switch": False})
    if entries_today is None:
        return _block("missing: entries today", {"inputs_complete": False})
    if entries_today >= MAX_ENTRIES_PER_DAY:
        return _block(f"daily entry cap {MAX_ENTRIES_PER_DAY} reached",
                      {"entry_cap": False})
    payload = dict(signal)
    payload.setdefault("rocket_rank", "R5")
    decision = review_signal(payload, ctx, limits or demo_limits())
    return RiskDecision(
        decision.verdict,
        decision.reasons,
        decision.risk_pct,
        decision.risk_amount,
        decision.size_factor,
        decision.checks,
        authority="demo-scalper-risk-brain",
    )


__all__ = [
    "ACCOUNT_TRADE_MODE_CONTEST",
    "ACCOUNT_TRADE_MODE_DEMO",
    "ACCOUNT_TRADE_MODE_REAL",
    "DEMO_LOGIN",
    "MAX_DAILY_LOSS_PCT",
    "MAX_ENTRIES_PER_DAY",
    "MAX_LOTS",
    "MAX_OPEN_POSITIONS",
    "MAX_SPREAD_ATR_FRACTION",
    "MIN_RR",
    "REDUCE_AT_DAILY_LOSS_FRACTION",
    "REDUCE_FACTOR",
    "RISK_PER_TRADE_PCT",
    "SL_ATR_MULT",
    "TP_ATR_MULT",
    "account_is_allowed",
    "demo_limits",
    "review_demo_trade",
    "size_lots",
]
