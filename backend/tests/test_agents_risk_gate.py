"""Stage 9: independent agent risk gate - deterministic, fail-safe, not overridable."""

from __future__ import annotations

import pytest

from app.agents.council.shadow import evaluate
from app.agents.risk_gate import RiskContext, RiskLimits, Verdict, review_council, review_signal

OK = RiskContext(equity=10_000, daily_pnl_pct=0.0, open_symbols=(), data_fresh=True)


def sig(**kw):
    base = {"symbol": "EURUSD", "direction": "BUY", "entry_zone": [1.1000, 1.1000],
            "stop_loss": 1.0950, "take_profit": 1.1150, "rocket_rank": "R5",
            "spread": 0.0001, "slippage_estimate": 0.0, "volatility_atr": 0.003}
    return {**base, **kw}


def test_clean_signal_is_approved_with_sized_risk():
    d = review_signal(sig(), OK)
    assert d.verdict is Verdict.APPROVE and d.risk_pct == 0.5 and d.risk_amount == 50.0


@pytest.mark.parametrize("ctx", [
    RiskContext(), RiskContext(equity=10_000, daily_pnl_pct=0, open_symbols=()),
    RiskContext(equity=None, daily_pnl_pct=0, open_symbols=(), data_fresh=True),
    RiskContext(equity=10_000, daily_pnl_pct=None, open_symbols=(), data_fresh=True),
    RiskContext(equity=10_000, daily_pnl_pct=0, open_symbols=None, data_fresh=True),
])
def test_missing_context_blocks(ctx):
    d = review_signal(sig(), ctx)
    assert d.verdict is Verdict.BLOCK and "missing" in d.reasons[0]


@pytest.mark.parametrize("field", ["stop_loss", "take_profit", "entry_zone", "direction"])
def test_missing_signal_fields_block(field):
    assert review_signal(sig(**{field: None}), OK).verdict is Verdict.BLOCK


def test_nan_is_missing():
    assert review_signal(sig(stop_loss=float("nan")), OK).verdict is Verdict.BLOCK


@pytest.mark.parametrize(("kw", "ctx_kw", "word"), [
    ({"stop_loss": 1.1050}, {}, "wrong side"),
    ({"take_profit": 1.1040}, {}, "R:R"),
    ({"spread": 0.005, "volatility_atr": None}, {}, "R:R"),
    ({"rocket_rank": "R2"}, {}, "rank"),
    ({}, {"daily_pnl_pct": -4.0}, "daily loss"),
    ({}, {"open_symbols": ("eurusd",)}, "already"),
    ({}, {"open_symbols": ("A", "B", "C")}, "cap"),
    ({}, {"kill_switch": True}, "kill"),
])
def test_blocks(kw, ctx_kw, word):
    ctx = RiskContext(**{**OK.__dict__, **ctx_kw})
    d = review_signal(sig(**kw), ctx)
    assert d.verdict is Verdict.BLOCK and word in " ".join(d.reasons)


def test_spread_against_atr_blocks():
    d = review_signal(sig(spread=0.001, take_profit=1.13), OK)
    assert d.verdict is Verdict.BLOCK and "ATR" in d.reasons[0]


@pytest.mark.parametrize(("kw", "ctx_kw", "factor"), [
    ({"rocket_rank": "R3"}, {}, 0.5),
    ({}, {"daily_pnl_pct": -2.5}, 0.5),
    ({}, {"high_impact_news_soon": True}, 0.5),
    ({"rocket_rank": "R3"}, {"high_impact_news_soon": True}, 0.25),
])
def test_reduce(kw, ctx_kw, factor):
    d = review_signal(sig(**kw), RiskContext(**{**OK.__dict__, **ctx_kw}))
    assert d.verdict is Verdict.REDUCE and d.size_factor == factor


def test_agent_fields_cannot_override():
    hostile = sig(rocket_rank="R1", verdict="APPROVE", override_risk=True, confidence=1.0,
                  risk_approval_status="APPROVED")
    assert review_signal(hostile, OK).verdict is Verdict.BLOCK


def test_deterministic():
    assert review_signal(sig(), OK) == review_signal(sig(), OK)


def test_limits_are_configurable_but_safe_default():
    assert review_signal(sig(rocket_rank="R3"), OK, RiskLimits(min_rank_approve="R3")) \
        .verdict is Verdict.APPROVE


def test_council_can_never_be_approved_alone():
    for rec in ("BUY", "SELL", "WAIT", None):
        r = review_council({"verdict": {"direction": rec}}, OK)
        assert r.verdict is Verdict.BLOCK


def test_council_shadow_carries_a_risk_review():
    out = evaluate({"symbol": "EURUSD", "timeframe": "H1"})
    assert out["risk_review"]["verdict"] == "BLOCK"
    assert out["wired_into_decisions"] is False
