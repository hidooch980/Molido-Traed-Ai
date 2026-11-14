"""Stage 15: TA02/TA03/RK02, tick-based SC02, AI02 ML, council versions, agent run."""

from __future__ import annotations

import os
import random
import time
from datetime import UTC, datetime, timedelta

import pytest

from app.agents.analyzers import ai02, extra, ml, scalping
from app.agents.analyzers.bars import Candle
from app.agents.analyzers.runner import ANALYZERS, run_timed
from app.agents.council.credibility import CredibilityBook, Record
from app.agents.council.versions import compare, long_r, propose, replay
from app.agents.council.weights import WeightStore
from app.agents.messages import Recommendation as Rec
from app.models.agent_memory import CouncilDecisionRecord
from app.services import agent_council, agent_run
from tests.conftest import insert_bar
from tests.test_agents_analyzers import T0, H, ctx_for, walk


def ar_bars(n: int, phi: float = 0.5, seed: int = 1) -> list[Candle]:
    rnd, price, prev, out = random.Random(seed), 1.1, 0.0, []
    for i in range(n):
        r = phi * prev + rnd.gauss(0, 0.001)
        o, c = price, price + r
        hi = max(o, c) + abs(rnd.gauss(0, 0.0003))
        lo = min(o, c) - abs(rnd.gauss(0, 0.0003))
        out.append(Candle(T0 + i * H, o, hi, lo, c, volume=100))
        price, prev = c, r
    return out


class TestExtraAnalyzers:
    def test_fold_uses_only_complete_groups(self):
        bars = walk(10)
        folded = extra.fold(tuple(bars), H, 4)
        assert all(f.open_time.hour % 4 == 0 for f in folded)
        assert all(f.high >= max(f.open, f.close) and f.low <= min(f.open, f.close)
                   for f in folded)

    def test_patterns(self):
        prev = Candle(T0, 1.10, 1.101, 1.094, 1.095)
        engulf = Candle(T0 + H, 1.094, 1.103, 1.093, 1.102)
        assert extra.candle_pattern(prev, engulf) == ("bullish engulfing", 1)
        pin = Candle(T0 + H, 1.1000, 1.1002, 1.0950, 1.1001)
        assert extra.candle_pattern(Candle(T0, 1.1, 1.104, 1.094, 1.1), pin)[1] == 1
        inside = Candle(T0 + H, 1.098, 1.100, 1.097, 1.0995)
        assert extra.candle_pattern(prev, inside) == ("inside bar", 0)

    def test_sl_tp_is_on_the_right_side_and_bounded(self):
        ctx = ctx_for(walk(200))
        for side, sign in (("BUY", 1), ("SELL", -1)):
            plan = extra.sl_tp(ctx, side)
            assert plan is not None
            risk = sign * (plan["entry"] - plan["stop_loss"])
            assert plan["atr"] * 0.999 <= risk <= 3 * plan["atr"] * 1.001
            assert sign * (plan["take_profit"] - plan["entry"]) >= 1.5 * risk * 0.999
        assert extra.rk02_sl_tp(ctx).recommendation is Rec.WAIT

    @pytest.mark.parametrize("agent", ["TA02", "TA03", "RK02"])
    def test_no_lookahead(self, agent):
        bars = walk(300)
        cut = bars[200].open_time
        a = ANALYZERS[agent](ctx_for(bars[:200], as_of=cut))
        b = ANALYZERS[agent](ctx_for(bars, as_of=cut))
        assert (a.recommendation, a.evidence) == (b.recommendation, b.evidence)


class TestSc02Ticks:
    def ticks(self, n=120, spread=0.0001, last_spread=None, up=True):
        out, mid = [], 1.1
        for i in range(n):
            mid += 0.00001 if (up or i % 2) else -0.00001
            s = last_spread if (last_spread and i == n - 1) else spread
            out.append({"time": T0 + timedelta(seconds=i), "bid": mid - s / 2,
                        "ask": mid + s / 2})
        return out

    def test_uses_ticks_and_ignores_future_ones(self):
        bars = walk(50)
        as_of = bars[-1].open_time + H
        ticks = [{**t, "time": as_of - timedelta(minutes=5) + (t["time"] - T0)}
                 for t in self.ticks()]
        future = [{"time": as_of + timedelta(seconds=i + 1), "bid": 2.0, "ask": 2.0001}
                  for i in range(500)]
        msg = scalping.sc02_microstructure(ctx_for(bars, as_of=as_of,
                                                   extras={"ticks": ticks + future}))
        assert "tick-level" in msg.analysis and msg.recommendation is Rec.BUY
        assert any("120 ticks" in e for e in msg.evidence)

    def test_wide_spread_waits(self):
        bars = walk(50)
        as_of = bars[-1].open_time + H
        ticks = [{**t, "time": as_of - timedelta(minutes=5) + (t["time"] - T0)}
                 for t in self.ticks(last_spread=0.001)]
        msg = scalping.sc02_microstructure(ctx_for(bars, as_of=as_of, extras={"ticks": ticks}))
        assert msg.recommendation is Rec.WAIT and msg.risk_assessment == "WIDE_SPREAD"

    def test_falls_back_to_bars_with_low_confidence(self):
        msg = scalping.sc02_microstructure(ctx_for(walk(50)))
        assert "bar-level" in msg.analysis and msg.confidence <= 0.4


class TestAi02Ml:
    def test_learns_autocorrelation_out_of_sample(self):
        res = ml.train_eval(ar_bars(600))
        assert res is not None and res["n_test"] > 100
        assert res["brier_oos"] < res["brier_base_oos"]

    def test_random_walk_has_no_edge_and_waits_mostly(self):
        res = ml.train_eval(walk(600, seed=11))
        assert res is not None and res["brier_oos"] > res["brier_base_oos"] - 0.01

    def test_is_fast_and_point_in_time(self):
        bars = ar_bars(500)
        started = time.perf_counter()
        a = ai02.ai02_forecast(ctx_for(bars[:400], as_of=bars[400].open_time))
        assert time.perf_counter() - started < 5
        b = ai02.ai02_forecast(ctx_for(bars, as_of=bars[400].open_time))
        assert (a.recommendation, a.evidence) == (b.recommendation, b.evidence)
        assert any("OOS" in e or "Brier" in e for e in a.evidence)


class TestCouncilVersions:
    def decisions(self, n=60):
        rnd, out = random.Random(5), []
        for _ in range(n):
            up = rnd.random() < 0.5
            good = 0.6 if up else -0.6
            ops = [{"member": "technical", "abstained": False, "score": good},
                   {"member": "trend", "abstained": False, "score": good * 0.8},
                   {"member": "sentiment", "abstained": False, "score": -good}]
            recorded = rnd.choice(["BUY", "SELL"])
            r = 1.0 if up else -1.0
            out.append({"opinions": ops, "direction": recorded,
                        "outcome_r": r if recorded == "BUY" else -r})
        return out

    def test_long_r_resigns_and_skips_wait(self):
        assert long_r({"direction": "SELL", "outcome_r": 1.0}) == -1.0
        assert long_r({"direction": "WAIT", "outcome_r": 1.0}) is None

    def test_replay_and_compare_are_in_memory(self):
        store = WeightStore()
        cur = store.current()
        res = replay(self.decisions(), cur)
        assert res["trades"] >= 0
        out = compare(self.decisions(), cur, cur)
        assert out["deployed"] is False and out["a"] == out["b"]
        assert len(store.history) == 1

    def test_propose_moves_toward_credibility_with_enough_data(self):
        cur = WeightStore().current()
        member = next(m for m, w in cur.weights.items() if w > 0)
        book = CredibilityBook()
        for i in range(40):
            book.add(Record(member, "BUY", 1.0 if i % 10 else -1.0, True))
        prop = propose(cur, book)
        assert prop is not None and member in prop["changes"]
        assert "human" in prop["requires"]
        thin = CredibilityBook([Record(member, "BUY", 1.0, True)])
        assert propose(cur, thin) is None

    def test_service_reads_resolved_records(self, session):
        for d in self.decisions(10):
            session.add(CouncilDecisionRecord(symbol="EURUSD", timeframe="H1",
                                              direction=d["direction"], verdict={},
                                              opinions=d["opinions"], outcome_r=d["outcome_r"],
                                              resolved_at=datetime.now(UTC)))
        session.flush()
        rep = agent_council.versions(session)
        assert rep["resolved_decisions"] == 10 and rep["mode"] == "shadow_only"


class TestRunAndHealth:
    def test_one_failing_agent_is_isolated(self, monkeypatch):
        def boom(ctx):
            raise RuntimeError("bad input")
        monkeypatch.setitem(ANALYZERS, "TA02", boom)
        messages, health = run_timed(ctx_for(walk(100)))
        assert health["TA02"]["ok"] is False and "bad input" in health["TA02"]["error"]
        assert sum(h["ok"] for h in health.values()) == len(ANALYZERS) - 1
        assert messages[-1].agent_id == "BRAIN-01"

    def test_read_ticks_converts_server_time(self, tmp_path):
        now = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
        server = now + timedelta(hours=3)
        lines = ["time_msc,bid,ask"] + [
            f"{int((server - timedelta(seconds=60 - i)).timestamp() * 1000)},1.1,1.1002"
            for i in range(60)]
        f = tmp_path / "molido_ticks_EURUSD.csv"
        f.write_text("\n".join(lines), encoding="utf-8")
        os.utime(f, (now.timestamp(), now.timestamp()))
        ticks = agent_run.read_ticks(tmp_path, "EURUSD", now)
        assert ticks and max(t["time"] for t in ticks) <= now
        assert agent_run.read_ticks(tmp_path, "EURUSD", now + timedelta(hours=1)) is None

    def test_cot_is_off_by_default(self, monkeypatch):
        monkeypatch.delenv(agent_run.COT_FLAG, raising=False)
        assert agent_run.cot_share("EURUSD", datetime.now(UTC)) is None

    def test_cot_tilt_maps_to_share(self, monkeypatch):
        from app.services import positioning
        monkeypatch.setenv(agent_run.COT_FLAG, "1")
        monkeypatch.setattr(positioning, "pair_tilt", lambda *a, **k: {"tilt": 0.4})
        assert agent_run.cot_share("EURUSD", datetime.now(UTC)) == pytest.approx(0.7)

    def test_run_symbol_records_health(self, session, instrument, provider):
        from app.agents import memory
        now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        rnd, price = random.Random(3), 1.10
        for i in range(120, 0, -1):
            t = now - timedelta(hours=i)
            nxt = price + rnd.gauss(0, 0.0005)
            insert_bar(session, instrument.id, provider.id, event_time=t,
                       ingested_at=t + timedelta(hours=1), close=nxt, open_=price)
            price = nxt
        from app.core.enums import Timeframe
        out = agent_run.run_symbol(session, "EURUSD", Timeframe.H1, as_of=now, record=True)
        assert out["status"] == "ran" and out["inputs"]["bars"] > 100
        assert set(out["health"]) == set(ANALYZERS)
        assert memory.recall(session, kind="agent")[0].content["event"] == "run"
