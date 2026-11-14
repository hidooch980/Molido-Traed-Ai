"""Stage 17: demo scalper risk profile for login 68531270 (200k USD demo)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.demo_scalper import (
    ACCOUNT_TRADE_MODE_CONTEST,
    ACCOUNT_TRADE_MODE_DEMO,
    ACCOUNT_TRADE_MODE_REAL,
    DEMO_LOGIN,
    MAX_DAILY_LOSS_PCT,
    MAX_ENTRIES_PER_DAY,
    MAX_LOTS,
    MAX_OPEN_POSITIONS,
    RISK_PER_TRADE_PCT,
    account_is_allowed,
    review_demo_trade,
    size_lots,
)
from app.agents.risk_gate import RiskContext, Verdict

BALANCE = 200_000.0
OK = RiskContext(equity=BALANCE, daily_pnl_pct=0.0, open_symbols=(), data_fresh=True)


def sig(**kw):
    base = {
        "symbol": "XAUUSD",
        "direction": "BUY",
        "entry_zone": [2650.00, 2650.00],
        "stop_loss": 2645.00,
        "take_profit": 2657.50,
        "spread": 0.20,
        "slippage_estimate": 0.0,
        "volatility_atr": 5.00,
    }
    return {**base, **kw}


def review(**kwargs):
    defaults = dict(
        trade_mode=ACCOUNT_TRADE_MODE_DEMO,
        login=DEMO_LOGIN,
        kill_switch=False,
        signal=sig(),
        ctx=OK,
        entries_today=0,
    )
    defaults.update(kwargs)
    return review_demo_trade(**defaults)


def test_clean_signal_approved_at_half_percent_of_200k():
    decision = review()
    assert decision.verdict is Verdict.APPROVE
    assert decision.risk_pct == RISK_PER_TRADE_PCT
    assert decision.risk_amount == 1000.0


def test_refuses_real_and_contest_and_wrong_login():
    assert review(trade_mode=ACCOUNT_TRADE_MODE_REAL).verdict is Verdict.BLOCK
    assert review(trade_mode=ACCOUNT_TRADE_MODE_CONTEST).verdict is Verdict.BLOCK
    assert review(login=12345678).verdict is Verdict.BLOCK
    assert review(trade_mode=None, login=DEMO_LOGIN).verdict is Verdict.BLOCK
    assert review(login=None).verdict is Verdict.BLOCK
    assert not account_is_allowed(ACCOUNT_TRADE_MODE_REAL, DEMO_LOGIN)
    assert not account_is_allowed(ACCOUNT_TRADE_MODE_DEMO, 0)
    assert account_is_allowed(ACCOUNT_TRADE_MODE_DEMO, DEMO_LOGIN)


def test_kill_switch_and_missing_data_block():
    assert review(kill_switch=True).verdict is Verdict.BLOCK
    assert review(ctx=RiskContext()).verdict is Verdict.BLOCK
    assert review(signal=sig(stop_loss=None)).verdict is Verdict.BLOCK
    assert review(entries_today=None).verdict is Verdict.BLOCK


def test_daily_loss_cap_is_two_percent():
    blocked = review(ctx=RiskContext(equity=BALANCE, daily_pnl_pct=-MAX_DAILY_LOSS_PCT,
                                     open_symbols=(), data_fresh=True))
    assert blocked.verdict is Verdict.BLOCK and "daily loss" in blocked.reasons[0]
    reduced = review(ctx=RiskContext(equity=BALANCE, daily_pnl_pct=-1.0,
                                     open_symbols=(), data_fresh=True))
    assert reduced.verdict is Verdict.REDUCE
    assert reduced.risk_pct == 0.25
    assert reduced.risk_amount == 500.0


def test_max_two_positions_and_no_duplicate_symbol():
    full = review(ctx=RiskContext(equity=BALANCE, daily_pnl_pct=0.0,
                                  open_symbols=("EURUSD", "GBPUSD"), data_fresh=True))
    assert full.verdict is Verdict.BLOCK and "cap" in full.reasons[0]
    assert MAX_OPEN_POSITIONS == 2
    dup = review(ctx=RiskContext(equity=BALANCE, daily_pnl_pct=0.0,
                                 open_symbols=("xauusd",), data_fresh=True))
    assert dup.verdict is Verdict.BLOCK and "already" in dup.reasons[0]


def test_mandatory_stop_and_wide_spread_and_entry_cap():
    assert review(signal=sig(stop_loss=2655.00)).verdict is Verdict.BLOCK
    wide = review(signal=sig(spread=1.00, take_profit=2670.00))
    assert wide.verdict is Verdict.BLOCK and "ATR" in wide.reasons[0]
    assert review(entries_today=MAX_ENTRIES_PER_DAY).verdict is Verdict.BLOCK


def test_size_lots_at_200k_gold_half_percent():
    # $5 stop, $1 per 0.01 tick: 500 ticks, $1000 / 500 = 2.00 lots, at the cap.
    assert size_lots(balance=BALANCE, risk_pct=0.5, sl_distance=5.0,
                     tick_size=0.01, tick_value=1.0) == 2.0
    # Tighter stop would want 5 lots; the 2.0 cap holds, actual risk stays under 0.5%.
    capped = size_lots(balance=BALANCE, risk_pct=0.5, sl_distance=2.0,
                       tick_size=0.01, tick_value=1.0)
    assert capped == 2.0
    assert capped * (2.0 / 0.01) * 1.0 == 400.0
    # Wider $10 stop sizes to 1.00 lot ($1000 risk).
    assert size_lots(balance=BALANCE, risk_pct=0.5, sl_distance=10.0,
                     tick_size=0.01, tick_value=1.0) == 1.0
    # REDUCE (0.25%) on the $5 stop is 1.00 lot.
    assert size_lots(balance=BALANCE, risk_pct=0.25, sl_distance=5.0,
                     tick_size=0.01, tick_value=1.0) == 1.0


def test_size_lots_never_exceeds_risk_budget_or_cap():
    assert size_lots(balance=BALANCE, risk_pct=0.5, sl_distance=0.5,
                     tick_size=0.01, tick_value=1.0) == MAX_LOTS
    # Minimum lot would already overshoot a tiny budget.
    assert size_lots(balance=100.0, risk_pct=0.5, sl_distance=50.0,
                     tick_size=0.01, tick_value=1.0, min_lot=0.01) is None
    assert size_lots(balance=None, risk_pct=0.5, sl_distance=5.0,
                     tick_size=0.01, tick_value=1.0) is None
    assert size_lots(balance=BALANCE, risk_pct=0.5, sl_distance=0.0,
                     tick_size=0.01, tick_value=1.0) is None
    assert size_lots(balance=float("nan"), risk_pct=0.5, sl_distance=5.0,
                     tick_size=0.01, tick_value=1.0) is None


@pytest.mark.parametrize("eur_sl, expected", [
    (0.0010, 2.0),   # 10 pips, $10/pip => 10 lots wanted, cap 2.0, risk $200
    (0.0050, 2.0),   # 50 pips => 2.0 lots exactly at $1000
    (0.0100, 1.0),   # 100 pips => 1.0 lot
])
def test_size_lots_eurusd_200k(eur_sl, expected):
    # 1 pip (0.0001) is $10 per lot; tick 0.00001 is $1.
    assert size_lots(balance=BALANCE, risk_pct=0.5, sl_distance=eur_sl,
                     tick_size=0.00001, tick_value=1.0) == expected


def test_mql_mirrors_python_constants():
    root = Path(__file__).resolve().parents[2] / "infra" / "mql5"
    src = (root / "MolidoDemoScalper.mqh").read_text(encoding="utf-8")
    assert f"#define DEMO_SCALPER_LOGIN      {DEMO_LOGIN}" in src
    assert "#define DEMO_HARD_MAX_LOTS      2.0" in src
    assert "#define DEMO_RISK_PCT           0.5" in src
    assert "#define DEMO_DAILY_LOSS_PCT     2.0" in src
    assert "#define DEMO_MAX_POSITIONS      2" in src
    assert "#define DEMO_MIN_RR             1.2" in src
    assert "#define DEMO_SPREAD_ATR_FRAC    0.15" in src
    assert "#define DEMO_MAX_ENTRIES_DAY    8" in src
    mq5 = (root / "MolidoBridge.mq5").read_text(encoding="utf-8")
    assert "ACCOUNT_TRADE_MODE_DEMO" in src
    assert "ExpectedLogin = 68531270" in mq5
    assert "MaxLots         = 2.00" in mq5
    assert "EnableDemoScalper" in mq5
