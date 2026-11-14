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
    FTMO_DAILY_LOSS_PCT,
    FTMO_MAX_DD_PCT,
    account_is_allowed,
    atr_percentile,
    auto_symbol_score,
    consensus_allows,
    correlation_conflict,
    in_loss_cooldown,
    in_news_avoid_window,
    live_real_unlocked,
    login_in_allowlist,
    news_breakout_side,
    partial_tp_volume,
    pick_top_symbols,
    prop_consistency_hit,
    prop_daily_stop,
    prop_near_dd,
    prop_pace_factor,
    regime_allows,
    review_demo_trade,
    safe_mode_action,
    session_allows,
    size_lots,
    trend_confirms,
    weekend_hold_window,
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
    mq5 = (root / "MolidoRuntime.mqh").read_text(encoding="utf-8")
    assert "ACCOUNT_TRADE_MODE_DEMO" in src
    assert 'AllowedLogins     = "68531270"' in mq5
    assert "AutoSymbolMode      = MOLIDO_DEFAULT_AUTO" in mq5
    assert "AccountProfile = MOLIDO_DEFAULT_PROFILE" in mq5
    assert (root / "MolidoSmart.mqh").is_file()
    assert (root / "MolidoProtect.mqh").is_file()
    assert (root / "MolidoUniverse.mqh").is_file()
    assert "ChartScreenShot" in (root / "MolidoProtect.mqh").read_text(encoding="utf-8")
    assert "MaxLots         = 2.00" in mq5
    assert "EnableDemoScalper" in mq5
    news = (root / "MolidoNews.mqh").read_text(encoding="utf-8")
    assert "NEWS_AVOID" in mq5 and "NEWS_TRADE" in mq5
    assert "CalendarValueHistory" in news
    assert "FTMO_DAILY_LOSS_PCT   5.0" in src
    assert "FTMO_MAX_DD_PCT       10.0" in src
    assert "ApplyDemoRiskCaps" in src


def test_other_demo_logins_need_server_caps():
    assert account_is_allowed(ACCOUNT_TRADE_MODE_DEMO, 42) is False
    assert account_is_allowed(ACCOUNT_TRADE_MODE_DEMO, 42, {42}) is True
    assert account_is_allowed(ACCOUNT_TRADE_MODE_REAL, 42, {42}) is False
    assert account_is_allowed(ACCOUNT_TRADE_MODE_DEMO, DEMO_LOGIN, set()) is True


def test_ftmo_preset_numbers():
    assert FTMO_DAILY_LOSS_PCT == 5.0 and FTMO_MAX_DD_PCT == 10.0
    # A 200k FTMO-style book: 5% daily = $10k, 10% max DD = $20k.
    assert BALANCE * FTMO_DAILY_LOSS_PCT / 100 == 10_000
    assert BALANCE * FTMO_MAX_DD_PCT / 100 == 20_000


def test_news_avoid_window_and_breakout():
    event = 1_000_000.0
    assert in_news_avoid_window(event - 15 * 60, event, 15)
    assert not in_news_avoid_window(event - 15 * 60 - 1, event, 15)
    assert in_news_avoid_window(event + 14 * 60, event, 15)
    assert not in_news_avoid_window(event + 15 * 60, event, 15)
    assert news_breakout_side(1.11, 1.10, 1.09) == "buy"
    assert news_breakout_side(1.08, 1.10, 1.09) == "sell"
    assert news_breakout_side(1.095, 1.10, 1.09) is None
    # A news-sized trade still cannot exceed the 0.5% / 2.00 lot caps.
    lots = size_lots(balance=BALANCE, risk_pct=0.25, sl_distance=5.0,
                     tick_size=0.01, tick_value=1.0)
    assert lots == 1.0

def test_allowlist_and_live_real_hard_lock():
    assert login_in_allowlist(DEMO_LOGIN, "68531270")
    assert login_in_allowlist(42, "68531270, 42")
    assert not login_in_allowlist(99, "68531270")
    assert not live_real_unlocked(profile="LIVE_REAL", trade_mode=ACCOUNT_TRADE_MODE_REAL,
                                  allow_real=False, real_allowlist="", login=DEMO_LOGIN)
    assert not live_real_unlocked(profile="LIVE_REAL", trade_mode=ACCOUNT_TRADE_MODE_REAL,
                                  allow_real=True, real_allowlist="", login=111)
    assert live_real_unlocked(profile="LIVE_REAL", trade_mode=ACCOUNT_TRADE_MODE_REAL,
                              allow_real=True, real_allowlist="111", login=111)
    assert not account_is_allowed(ACCOUNT_TRADE_MODE_REAL, 111, profile="LIVE_REAL",
                                  allow_real=True, real_allowlist="")
    assert account_is_allowed(ACCOUNT_TRADE_MODE_CONTEST, DEMO_LOGIN,
                              profile="PROP_FTMO", allowlist="68531270")
    assert not account_is_allowed(ACCOUNT_TRADE_MODE_REAL, DEMO_LOGIN, profile="DEMO")


def test_smart_filters_and_consensus_never_loosen():
    hist = [1.0] * 20 + [2.0] * 20
    assert 40 <= atr_percentile(1.5, hist) <= 70
    assert regime_allows(40, 22)
    assert not regime_allows(None, 22)
    assert session_allows(13, 2)  # London+NY overlap, Tuesday
    assert not session_allows(3, 2)
    assert not session_allows(13, 0)
    assert trend_confirms("buy", 2, 1, 2, 1)
    assert not trend_confirms("buy", 2, 1, 1, 2)
    assert in_loss_cooldown(1000, 1000 - 10 * 60, 30)
    assert not in_loss_cooldown(1000, 1000 - 31 * 60, 30)
    assert consensus_allows("buy", "buy", fresh=True, require=False)
    assert not consensus_allows("buy", "sell", fresh=True, require=False)
    assert not consensus_allows("buy", None, fresh=False, require=True)
    assert consensus_allows("buy", None, fresh=False, require=False)
    assert weekend_hold_window(5, 21) and not weekend_hold_window(3, 12)


def test_protect_features_and_auto_symbol_score():
    assert safe_mode_action(2) == "reduce"
    assert safe_mode_action(3) == "stop"
    assert safe_mode_action(1) == "off"
    assert partial_tp_volume(0.20, 50, 0.01, 0.01) == 0.10
    assert partial_tp_volume(0.01, 50, 0.01, 0.01) is None
    assert correlation_conflict("buy", "GBPUSD", [("EURUSD", "buy")])
    assert not correlation_conflict("buy", "GBPUSD", [("EURUSD", "sell")])
    assert not correlation_conflict("buy", "USDJPY", [("EURUSD", "buy")])
    tight = auto_symbol_score(spread_atr=0.03, in_session=True, trend_aligned=True,
                              weekly_pnl=10.0, rocket=80.0, adx=25)
    loose = auto_symbol_score(spread_atr=0.20, in_session=False, trend_aligned=False,
                              weekly_pnl=-5.0, rocket=100.0, adx=8)
    assert tight > loose
    # A perfect rocket rank cannot lift a poor local symbol above a healthy one.
    assert tight > auto_symbol_score(spread_atr=0.20, in_session=False, trend_aligned=False,
                                     weekly_pnl=None, rocket=100.0, adx=8)
    assert pick_top_symbols([("EURUSD.r", 50), ("XAUUSD", 90), ("GBPUSD", 70)], 2) == ["XAUUSD", "GBPUSD"]


def test_prop_challenge_pacing_and_buffers():
    assert prop_daily_stop(5.0) == 4.0
    assert prop_pace_factor(0.5) == 1.0
    assert prop_pace_factor(0.7) == 0.5
    assert prop_pace_factor(0.9) == 0.25
    assert prop_pace_factor(1.0) == 0.0
    assert prop_consistency_hit(4.0, 10.0, 40)
    assert not prop_consistency_hit(3.9, 10.0, 40)
    assert prop_near_dd(dd=8.1, dd_limit=10.0, risk=0.25)
    assert prop_near_dd(dd=7.8, dd_limit=10.0, risk=0.25)  # remaining 0.2 < 1.25*0.25
    assert not prop_near_dd(dd=1.0, dd_limit=10.0, risk=0.25)
