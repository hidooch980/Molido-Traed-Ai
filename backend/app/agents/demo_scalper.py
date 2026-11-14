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
FTMO_DAILY_LOSS_PCT = 5.0
FTMO_MAX_DD_PCT = 10.0
HARD_MAX_DAILY_LOSS_PCT = 5.0
HARD_MAX_DD_PCT = 10.0


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


def login_in_allowlist(login: int | None, csv: str) -> bool:
    """True when login appears in a comma/semicolon allowlist."""
    if login is None or not csv:
        return False
    try:
        acc = int(login)
    except (TypeError, ValueError):
        return False
    if acc <= 0:
        return False
    for part in csv.replace(";", ",").split(","):
        token = part.strip()
        if token.lstrip("-").isdigit() and int(token) == acc:
            return True
    return False


def live_real_unlocked(
    *,
    profile: str,
    trade_mode: int | None,
    allow_real: bool,
    real_allowlist: str,
    login: int | None,
) -> bool:
    """LIVE_REAL stays hard-locked unless every unlock is set by the user."""
    if profile != "LIVE_REAL" or not allow_real:
        return False
    if trade_mode is None or int(trade_mode) != ACCOUNT_TRADE_MODE_REAL:
        return False
    return login_in_allowlist(login, real_allowlist)


def account_is_allowed(
    trade_mode: int | None,
    login: int | None,
    allowed_logins: set[int] | None = None,
    *,
    profile: str = "DEMO",
    allowlist: str = "68531270",
    allow_real: bool = False,
    real_allowlist: str = "",
) -> bool:
    """DEMO/PROP need the demo allowlist. LIVE_REAL is hard-locked by default."""
    if trade_mode is None or login is None:
        return False
    try:
        mode = int(trade_mode)
        acc = int(login)
    except (TypeError, ValueError):
        return False
    if profile == "LIVE_REAL":
        return live_real_unlocked(
            profile=profile, trade_mode=mode, allow_real=allow_real,
            real_allowlist=real_allowlist, login=acc,
        )
    if mode == ACCOUNT_TRADE_MODE_REAL:
        return False
    if profile == "DEMO" and mode != ACCOUNT_TRADE_MODE_DEMO:
        return False
    if profile in {"PROP_FTMO", "PROP_GENERIC"} and mode not in {
        ACCOUNT_TRADE_MODE_DEMO, ACCOUNT_TRADE_MODE_CONTEST,
    }:
        return False
    if login_in_allowlist(acc, allowlist):
        return True
    # Backward-compatible extra demo logins (explicit set, still never real).
    return mode == ACCOUNT_TRADE_MODE_DEMO and bool(allowed_logins) and acc in allowed_logins


def in_news_avoid_window(now_ts: float, event_ts: float, avoid_minutes: int) -> bool:
    """True when now is inside [event - X, event + X] minutes."""
    if avoid_minutes <= 0 or event_ts <= 0:
        return False
    pad = avoid_minutes * 60
    return event_ts - pad <= now_ts < event_ts + pad


def news_breakout_side(close: float, pre_high: float, pre_low: float) -> str | None:
    if pre_high <= pre_low or close <= 0:
        return None
    if close > pre_high:
        return "buy"
    if close < pre_low:
        return "sell"
    return None


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

def atr_percentile(current: float, history: list[float]) -> float | None:
    if current <= 0 or len(history) < 30:
        return None
    below = sum(1 for value in history if value <= current)
    return 100.0 * below / len(history)


def regime_allows(atr_pct: float | None, adx: float | None, *, atr_min=20, atr_max=80, adx_min=18) -> bool:
    if atr_pct is None or adx is None:
        return False
    return atr_min <= atr_pct <= atr_max and adx >= adx_min


def session_allows(hour_gmt: int, weekday: int, london=(7, 16), ny=(12, 21)) -> bool:
    """weekday: 0=Sunday ... 6=Saturday, same as MT5."""
    if weekday in {0, 6}:
        return False
    hour = hour_gmt % 24
    return (london[0] <= hour < london[1]) or (ny[0] <= hour < ny[1])


def trend_confirms(side: str, m15_e20: float, m15_e50: float, h1_e20: float, h1_e50: float) -> bool:
    if min(m15_e20, m15_e50, h1_e20, h1_e50) <= 0:
        return False
    side = side.lower()
    if side == "buy":
        return m15_e20 > m15_e50 and h1_e20 > h1_e50
    if side == "sell":
        return m15_e20 < m15_e50 and h1_e20 < h1_e50
    return False


def in_loss_cooldown(now_ts: float, last_loss_ts: float | None, minutes: int) -> bool:
    if minutes <= 0 or last_loss_ts is None:
        return False
    return now_ts - last_loss_ts < minutes * 60


def consensus_allows(local_side: str, server_side: str | None, *, fresh: bool, require: bool) -> bool:
    """Veto only: missing/stale never counts as approval, and never loosens a local block."""
    if server_side is None or not fresh:
        return not require
    side = server_side.lower()
    if side in {"wait", "block", "none", ""}:
        return False
    return side == local_side.lower()


def weekend_hold_window(weekday: int, hour_gmt: int) -> bool:
    if weekday == 6:
        return True
    if weekday == 0 and hour_gmt < 22:
        return True
    if weekday == 5 and hour_gmt >= 21:
        return True
    return False


def correlation_conflict(side: str, candidate: str, open_positions: list[tuple[str, str]]) -> bool:
    """True when an open position already points the same way in a correlated group."""
    groups = (
        {"EURUSD", "GBPUSD", "AUDUSD", "NZDUSD"},
        {"USDJPY", "USDCHF", "USDCAD"},
        {"EURJPY", "GBPJPY", "AUDJPY", "CADJPY"},
        {"XAUUSD", "XAGUSD"},
    )
    core = next((g for g in groups if any(candidate.startswith(s) for s in g)), None)
    if core is None:
        # exact core name
        for g in groups:
            if candidate in g or any(candidate.startswith(s) for s in g):
                core = g
                break
    if core is None:
        return False
    want = side.lower()
    cand = next((s for s in core if candidate.startswith(s)), candidate)
    for symbol, pos_side in open_positions:
        other = next((s for s in core if symbol.startswith(s)), None)
        if other and other != cand and pos_side.lower() == want:
            return True
    return False


def safe_mode_action(consecutive_losses: int, reduce_after: int = 2, stop_after: int = 3) -> str:
    if stop_after > 0 and consecutive_losses >= stop_after:
        return "stop"
    if reduce_after > 0 and consecutive_losses >= reduce_after:
        return "reduce"
    return "off"


def partial_tp_volume(volume: float, close_pct: float, step: float, min_lot: float) -> float | None:
    close = (volume * close_pct / 100.0) // step * step
    if close < min_lot or (volume - close) < min_lot:
        return None
    return float(close)


def auto_symbol_score(*, spread_atr: float, in_session: bool, trend_aligned: bool,
                      weekly_pnl: float | None, rocket: float | None,
                      adx: float, adx_min: float = 18.0) -> float:
    """Higher is better. Rocket is a bonus of at most 10 and never a substitute for local quality."""
    spread_pts = max(0.0, min(25.0, 25.0 * (1.0 - spread_atr / 0.15)))
    adx_pts = 15.0 if adx_min <= adx <= 45 else (8.0 if adx >= adx_min else 0.0)
    trend_pts = 10.0 if trend_aligned else 0.0
    sess_pts = 10.0 if in_session else 2.0
    week_pts = 5.0 if weekly_pnl is None else (10.0 if weekly_pnl > 0 else 0.0)
    rocket_pts = 0.0 if rocket is None else 0.10 * max(0.0, min(100.0, rocket))
    return spread_pts + adx_pts + trend_pts + sess_pts + week_pts + rocket_pts


def pick_top_symbols(scored: list[tuple[str, float]], n: int = 3) -> list[str]:
    ordered = sorted(scored, key=lambda x: x[1], reverse=True)
    return [name for name, _ in ordered[: max(1, n)]]


def prop_daily_stop(daily_limit: float, buffer: float = 0.80) -> float:
    return daily_limit * buffer


def prop_pace_factor(progress: float, start: float = 0.70, tight: float = 0.90) -> float:
    if progress >= 1.0:
        return 0.0
    if progress >= tight:
        return 0.25
    if progress >= start:
        return 0.50
    return 1.0


def prop_consistency_hit(day_profit_pct: float, target_pct: float, share: float = 40.0) -> bool:
    if target_pct <= 0 or share <= 0:
        return False
    return day_profit_pct >= target_pct * share / 100.0


def prop_near_dd(*, dd: float, dd_limit: float, risk: float, buffer: float = 0.80) -> bool:
    stop = dd_limit * buffer
    if dd >= stop:
        return True
    return (stop - dd) <= risk * 1.25
