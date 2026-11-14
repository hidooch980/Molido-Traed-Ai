"""Stage 6: deterministic analyzers - point-in-time, honest, shadow only."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from app.agents import registry
from app.agents.analyzers import ai02, brain01, rocket, scalping, smc
from app.agents.analyzers.bars import Candle, make_context, swings
from app.agents.analyzers.runner import ANALYZERS, run_all
from app.agents.messages import AgentMessage, Market, Recommendation

H = timedelta(hours=1)
T0 = datetime(2026, 11, 2, 0, 0, tzinfo=UTC)


def walk(n: int, seed: int = 7, start: float = 1.10, vol: float = 0.001) -> list[Candle]:
    rnd = random.Random(seed)
    out, price = [], start
    for i in range(n):
        o = price
        c = o + rnd.gauss(0, vol)
        hi, lo = max(o, c) + abs(rnd.gauss(0, vol / 2)), min(o, c) - abs(rnd.gauss(0, vol / 2))
        out.append(Candle(T0 + i * H, o, hi, lo, c, volume=100 + rnd.randint(0, 20)))
        price = c
    return out


def ctx_for(bars, as_of=None, **kw):
    as_of = as_of or bars[-1].open_time + H
    return make_context("EURUSD", Market.FOREX, "H1", H, bars, as_of, **kw)


class TestPointInTime:
    def test_unclosed_bars_are_invisible(self):
        bars = walk(10)
        ctx = make_context("EURUSD", Market.FOREX, "H1", H, bars, bars[5].open_time + H / 2)
        assert len(ctx.bars) == 5

    def test_naive_as_of_refused(self):
        with pytest.raises(ValueError):
            make_context("EURUSD", Market.FOREX, "H1", H, walk(3), datetime(2026, 1, 1))

    @pytest.mark.parametrize("seed", [1, 2, 3])
    def test_future_bars_change_nothing(self, seed):
        bars = walk(400, seed)
        as_of = bars[299].open_time + H
        past_only = run_all(make_context("EURUSD", Market.FOREX, "H1", H, bars[:300], as_of,
                                         spread=0.0001))
        with_future = run_all(make_context("EURUSD", Market.FOREX, "H1", H, bars, as_of,
                                           spread=0.0001))
        strip = [(m.agent_id, m.recommendation, tuple(m.evidence), m.confidence)
                 for m in past_only]
        assert strip == [(m.agent_id, m.recommendation, tuple(m.evidence), m.confidence)
                         for m in with_future]

    def test_swings_need_bars_on_both_sides(self):
        bars = walk(30)
        hi, lo = swings(tuple(bars), 2)
        assert all(2 <= i <= len(bars) - 3 for i in hi + lo)


class TestCoverage:
    def test_analyzers_cover_the_target_roles(self):
        expected = {f"SC{i:02d}" for i in range(1, 11)} | {f"SM{i:02d}" for i in range(1, 11)} \
            | {f"RT{i:02d}" for i in range(1, 11)} | {"AI02"}
        assert set(ANALYZERS) == expected
        assert all(registry.get(k) for k in ANALYZERS)

    def test_empty_history_abstains_or_waits_never_directional(self):
        ctx = ctx_for(walk(3))
        for msg in run_all(ctx):
            assert isinstance(msg, AgentMessage)
            assert msg.recommendation in (Recommendation.ABSTAIN, Recommendation.WAIT)

    def test_no_analyzer_blocks(self):
        for msg in run_all(ctx_for(walk(300), spread=0.0001)):
            assert msg.recommendation is not Recommendation.BLOCK


def spike(bars, up=True, size=0.01):
    last = bars[-1]
    o = last.close
    c = o + size if up else o - size
    return [*bars, Candle(last.open_time + H, o, max(o, c), min(o, c), c, volume=1000)]


class TestPatterns:
    def test_rt01_explosion_and_rt05_volume(self):
        bars = spike(walk(200))
        ctx = ctx_for(bars)
        assert rocket.rt01_explosion(ctx).recommendation is Recommendation.BUY
        assert rocket.rt05_abnormal_volume(ctx).recommendation is Recommendation.BUY

    def test_rt03_breakdown(self):
        assert rocket.rt03_breakout(ctx_for(spike(walk(200), up=False))).recommendation \
            is Recommendation.SELL

    def test_sm04_fvg_detection(self):
        b = [Candle(T0 + i * H, 1.0, 1.001, 0.999, 1.0) for i in range(3)]
        b[2] = Candle(T0 + 2 * H, 1.002, 1.004, 1.002, 1.003)
        assert smc.fair_value_gaps(tuple(b))[0][0] == "bull"

    def test_sm02_sweep_rejection(self):
        bars = walk(60, seed=11)
        hi, _ = swings(tuple(bars), 2)
        level = bars[hi[-1]].high
        last = bars[-1]
        bars.append(Candle(last.open_time + H, level - 0.0002, level + 0.0010, level - 0.0005,
                           level - 0.0003))
        assert smc.sm02_sweep(ctx_for(bars)).recommendation is Recommendation.SELL

    def test_sm10_needs_public_data(self):
        assert smc.sm10_institutional(ctx_for(walk(40))).recommendation is Recommendation.ABSTAIN
        m = smc.sm10_institutional(ctx_for(walk(40), extras={"cot_speculative_net_long_share":
                                                             0.95}))
        assert m.recommendation is Recommendation.SELL and "CFTC" in " ".join(m.evidence)

    def test_sc09_break_even_and_trail(self):
        bars = walk(30)
        price = bars[-1].close
        be = scalping.sc09_position_manager(ctx_for(bars, extras={"position": {
            "side": "BUY", "entry": price - 0.0015, "stop": price - 0.0025}}))
        trail = scalping.sc09_position_manager(ctx_for(bars, extras={"position": {
            "side": "BUY", "entry": price - 0.0025, "stop": price - 0.0035}}))
        assert "break-even" in be.analysis and "trail" in trail.analysis

    def test_sc05_needs_spread(self):
        assert scalping.sc05_spread(ctx_for(walk(40))).recommendation is Recommendation.ABSTAIN
        costly = scalping.sc05_spread(ctx_for(walk(40), spread=0.01))
        assert costly.risk_assessment == "COSTLY"

    def test_sc10_performance(self):
        m = scalping.sc10_performance(ctx_for(walk(5), extras={"outcomes_r": [1, -1] * 6}))
        assert "expectancy +0.00R" in m.evidence


class TestRocketSignal:
    def test_signal_record_is_complete_and_proposed(self):
        bars = spike(walk(300, seed=5), size=0.012)
        msg, sig = rocket.rt10_evaluate(ctx_for(bars, spread=0.0001))
        assert sig is not None and sig.status == "PROPOSED"
        assert sig.risk_approval_status == "NOT_SUBMITTED"
        d = sig.as_dict()
        for key in ("symbol", "direction", "timeframe", "signal_timestamp", "market_regime",
                    "rocket_rank", "entry_zone", "stop_loss", "take_profit", "expected_rr",
                    "spread", "slippage_estimate", "volatility_atr", "supporting_evidence",
                    "conflicting_evidence", "confidence_calibration", "invalidation"):
            assert key in d
        assert sig.direction == "BUY" and sig.stop_loss < bars[-1].close < sig.take_profit
        assert "not win probability" in sig.confidence_calibration

    def test_over_extension_is_penalised(self):
        bars = spike(walk(300, seed=5), size=0.03)
        _, sig = rocket.rt10_evaluate(ctx_for(bars))
        assert sig is not None and any("chasing" in c for c in sig.conflicting_evidence)

    def test_news_window_downgrades(self):
        bars = spike(walk(300, seed=5), size=0.012)
        as_of = bars[-1].open_time + H
        events = [{"time": as_of + timedelta(minutes=10), "impact": "high", "currency": "USD"}]
        _, base = rocket.rt10_evaluate(ctx_for(bars))
        _, news = rocket.rt10_evaluate(ctx_for(bars, extras={"events": events}))
        assert base and news and news.score < base.score

    def test_rank_bands(self):
        assert [rocket.rank(s) for s in (0, 1.5, 2.5, 3.5, 4.5)] == ["R1", "R2", "R3", "R4",
                                                                       "R5"]

    def test_outcome_is_conservative(self):
        sig = rocket.RocketSignal("EURUSD", "BUY", "H1", "t", "u", "R3", (1.0, 1.0), 0.99, 1.02,
                                  2.0, None, 0.0, 0.01, [], [], "u", "x")
        both = [Candle(T0, 1.0, 1.03, 0.98, 1.0)]
        assert rocket.evaluate_outcome(sig, both)["result"] == "stop"
        win = [Candle(T0, 1.0, 1.021, 0.995, 1.02)]
        assert rocket.evaluate_outcome(sig, win)["result"] == "target"


class TestAI02AndBrain:
    def test_ai02_abstains_on_short_history(self):
        assert ai02.ai02_forecast(ctx_for(walk(50))).recommendation is Recommendation.ABSTAIN

    def test_ai02_reports_its_calibration(self):
        m = ai02.ai02_forecast(ctx_for(walk(500)))
        assert any("Brier" in e for e in m.evidence)

    def test_ai02_finds_persistence_when_it_exists(self):
        closes = [1.0 + 0.001 * i for i in range(300)]
        f = ai02.forecast(closes)
        assert f is not None and f["p_up"] > 0.9

    def test_brain01_findings(self):
        ctx = ctx_for(walk(40))
        a = scalping.message("SC03", ctx, Recommendation.BUY, 0.95, "x", ["one"])
        b = scalping.message("SM06", ctx, Recommendation.SELL, 0.4, "y", ["e1", "e2"])
        report = brain01.evaluate([a, b, a])
        text = " ".join(report["findings"])
        assert "conflict" in text and "overconfident" in text and "duplicate" in text
        assert brain01.brain01_message([a, b], a).recommendation is Recommendation.WAIT
