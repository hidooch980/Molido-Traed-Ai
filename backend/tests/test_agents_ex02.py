"""Stage 20: EX02 slippage control — requested vs filled, stats, cap, no override."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.agents.analyzers.fleet import ex02_slippage
from app.agents.messages import Recommendation as Rec
from app.agents.slippage import (
    DEFAULT_CAP_POINTS,
    MIN_SAMPLES,
    adverse_price,
    decide,
    live_fill_over_cap,
    parse_fill,
    summarize,
)
from app.services import agent_slippage
from tests.test_agents_analyzers import ctx_for, walk


def fill(symbol="EURUSD", side="BUY", requested=1.10000, filled=1.10030, point=0.00001, **kw):
    return {"symbol": symbol, "side": side, "requested_price": requested,
            "filled_price": filled, "point": point, **kw}


class TestMath:
    def test_adverse_cost_is_side_aware(self):
        assert adverse_price("BUY", 1.10, 1.1003) == pytest.approx(0.0003)
        assert adverse_price("SELL", 1.10, 1.0997) == pytest.approx(0.0003)
        assert adverse_price("BUY", 1.10, 1.0999) == pytest.approx(-0.0001)

    def test_incomplete_fills_are_dropped(self):
        assert parse_fill({"symbol": "EURUSD", "side": "BUY", "requested_price": 1.1}) is None
        assert parse_fill({"symbol": "EURUSD", "side": "BUY", "filled_price": 1.1}) is None
        assert parse_fill({"symbol": "EURUSD", "side": "BUY",
                           "requested_price": float("nan"), "filled_price": 1.1}) is None
        assert parse_fill({"symbol": "", "side": "BUY",
                           "requested_price": 1.1, "filled_price": 1.1001}) is None
        parsed = parse_fill(fill())
        assert parsed is not None and parsed["adverse_points"] == pytest.approx(30.0)

    def test_long_and_short_aliases(self):
        assert parse_fill(fill(side="long"))["side"] == "BUY"
        assert parse_fill(fill(side="short"))["side"] == "SELL"


class TestStatsAndGate:
    def test_missing_samples_are_wait_not_zero(self):
        decision = decide([], symbol="EURUSD")
        assert decision.recommendation == "WAIT"
        assert decision.estimate_points is None
        assert "zero" in decision.analysis

    def test_too_few_samples_withhold_the_estimate(self):
        fills = [fill(filled=1.10010 + i * 0.00001) for i in range(MIN_SAMPLES - 1)]
        decision = decide(fills, symbol="EURUSD")
        assert decision.recommendation == "WAIT"
        assert decision.estimate_points is None
        assert decision.sample_count == MIN_SAMPLES - 1

    def test_p90_over_the_cap_blocks(self):
        # Five 10-point fills and enough 80-point fills to pull p90 over 30.
        fills = [fill(filled=1.10010) for _ in range(3)]
        fills += [fill(filled=1.10080) for _ in range(7)]
        stats = summarize(fills, symbol="EURUSD")
        assert stats.sample_count == 10
        assert stats.p90_points is not None and stats.p90_points > DEFAULT_CAP_POINTS
        decision = decide(fills, symbol="EURUSD")
        assert decision.recommendation == "BLOCK"
        assert decision.estimate_points == stats.p90_points

    def test_within_cap_is_wait_not_an_approval(self):
        fills = [fill(filled=1.10005) for _ in range(8)]
        decision = decide(fills, symbol="EURUSD")
        assert decision.recommendation == "WAIT"
        assert "Risk Brain" in decision.analysis
        assert decision.estimate_points is not None
        assert decision.estimate_points <= DEFAULT_CAP_POINTS

    def test_cannot_override_a_risk_brain_block(self):
        fills = [fill(filled=1.10005) for _ in range(8)]  # would be within cap
        decision = decide(fills, symbol="EURUSD", risk_verdict="BLOCK")
        assert decision.recommendation == "BLOCK"
        assert "cannot override" in decision.analysis

    def test_unknown_point_size_is_wait(self):
        fills = [fill(point=None, filled=1.10080) for _ in range(8)]
        for item in fills:
            item.pop("point", None)
        decision = decide(fills, symbol="EURUSD")
        assert decision.recommendation == "WAIT"
        assert "point" in decision.analysis

    def test_live_fill_over_cap(self):
        assert live_fill_over_cap(fill(filled=1.10040)) is True
        assert live_fill_over_cap(fill(filled=1.10005)) is False
        assert live_fill_over_cap({"symbol": "EURUSD", "side": "BUY"}) is None

    def test_other_symbols_are_ignored(self):
        fills = [fill(symbol="GBPUSD", filled=1.10080) for _ in range(8)]
        decision = decide(fills, symbol="EURUSD")
        assert decision.sample_count == 0
        assert decision.recommendation == "WAIT"


class TestAnalyzerAndMemory:
    def test_analyzer_blocks_when_the_estimate_is_over_cap(self):
        fills = [fill(filled=1.10080) for _ in range(8)]
        ctx = ctx_for(walk(80), extras={"slippage_fills": fills})
        msg = ex02_slippage(ctx)
        assert msg.recommendation is Rec.BLOCK
        assert msg.agent_id == "EX02"

    def test_analyzer_waits_without_fills(self):
        msg = ex02_slippage(ctx_for(walk(80)))
        assert msg.recommendation is Rec.WAIT
        assert "zero" in msg.analysis

    def test_analyzer_respects_risk_brain_block(self):
        fills = [fill(filled=1.10005) for _ in range(8)]
        ctx = ctx_for(walk(80), extras={"slippage_fills": fills, "risk_verdict": "BLOCK"})
        assert ex02_slippage(ctx).recommendation is Rec.BLOCK

    def test_memory_stores_only_complete_fills(self, session):
        assert agent_slippage.record_fill(session, {"symbol": "EURUSD", "side": "BUY"}) is None
        stored = agent_slippage.record_fill(session, fill(at=datetime.now(UTC).isoformat()))
        assert stored is not None and stored["adverse_points"] == pytest.approx(30.0)
        found = agent_slippage.fills_for(session, "EURUSD")
        assert len(found) == 1 and found[0]["filled_price"] == 1.10030
        assert agent_slippage.fills_for(session, "XAUUSD") == []
