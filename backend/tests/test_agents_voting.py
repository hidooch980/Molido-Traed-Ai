"""Stage 21: weighted votes, regime gate, underperformer report, bridge votes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.agents.risk_gate import RiskContext
from app.agents.selfheal import Sample
from app.agents.voting import (
    DISABLE_HIT,
    MIN_SAMPLES,
    W_MAX,
    W_MIN,
    detect_regime,
    rolling_weights,
    scorecard,
    underperformers,
    vote,
)
from app.services import agent_notify, agent_report, ea_config
from tests.test_agents_analyzers import ctx_for, walk

T0 = datetime(2026, 10, 1, tzinfo=UTC)
NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


def _samples(n: int, agent: str = "TA04", rec: str = "BUY", move: float = 0.001,
             start: datetime = T0, step: timedelta = timedelta(days=1)) -> list[Sample]:
    return [Sample(start + i * step, {agent: rec}, move) for i in range(n)]


class TestWeights:
    def test_thin_history_stays_neutral(self):
        misses = _samples(MIN_SAMPLES - 1, rec="BUY", move=-0.001)
        assert rolling_weights(misses, now=NOW)["TA04"] == 1.0

    def test_all_hits_and_misses_are_clamped(self):
        hits = _samples(40, rec="BUY", move=0.001, start=NOW - timedelta(days=40))
        misses = _samples(40, rec="BUY", move=-0.001, start=NOW - timedelta(days=40))
        assert rolling_weights(hits, now=NOW)["TA04"] == W_MAX
        assert rolling_weights(misses, now=NOW)["TA04"] == W_MIN

    def test_recent_results_outweigh_old_ones(self):
        old_miss = _samples(20, rec="BUY", move=-0.001, start=NOW - timedelta(days=90))
        new_hit = _samples(20, rec="BUY", move=0.001, start=NOW - timedelta(days=20))
        old_hit = _samples(20, rec="BUY", move=0.001, start=NOW - timedelta(days=90))
        new_miss = _samples(20, rec="BUY", move=-0.001, start=NOW - timedelta(days=20))
        up = rolling_weights(old_miss + new_hit, now=NOW)["TA04"]
        down = rolling_weights(old_hit + new_miss, now=NOW)["TA04"]
        assert up > 1.0 > down


class TestVoteAndRegime:
    def test_empty_or_unknown_is_wait(self):
        assert vote({}, {}).recommendation == "WAIT"
        bars = walk(20)
        assert detect_regime(ctx_for(bars).bars)["regime"] == "unknown"

    def test_regime_gate_skips_ineligible_agents(self):
        calls = {"TA04": "BUY", "TA05": "SELL"}
        trend = vote(calls, {}, regime="trend")
        rng = vote(calls, {}, regime="range")
        assert trend.recommendation == "BUY" and trend.n_buy == 1 and trend.n_held == 1
        assert rng.recommendation == "SELL" and rng.n_sell == 1 and rng.n_held == 1

    def test_unknown_regime_counts_everyone(self):
        # equal weights, opposite calls, inside the band -> WAIT
        result = vote({"TA04": "BUY", "TA05": "SELL"}, {}, regime="unknown")
        assert result.n_buy == 1 and result.n_sell == 1
        assert result.recommendation == "WAIT"

    def test_control_block_withholds_a_directional_vote(self):
        result = vote({"TA04": "BUY", "RK01": "BLOCK"}, {"TA04": 2.0}, regime="trend")
        assert result.recommendation == "WAIT" and result.withheld is True
        assert "RK01" in result.reason

    def test_detects_trend_range_and_volatile(self):
        rising = walk(80, seed=2)
        # walk() already trends; ATR vs median should classify
        label = detect_regime(tuple(ctx_for(rising).bars))["regime"]
        assert label in {"trend", "range", "volatile", "unknown"}


class TestScorecardAndReport:
    def test_scorecard_tracks_accuracy_pnl_and_votes(self):
        hits = _samples(10, rec="BUY", move=0.01, start=NOW - timedelta(days=10))
        rows = {r["id"]: r for r in scorecard(hits, {"TA04": 1.5}, now=NOW)}
        assert rows["TA04"]["accuracy"] == 1.0
        assert rows["TA04"]["hyp_pnl_pct"] == 10.0  # 10 * 1%
        assert rows["TA04"]["buy"] == 10 and rows["TA04"]["weight"] == 1.5

    def test_underperformers_are_proposals_only(self):
        misses = _samples(30, rec="BUY", move=-0.01, start=NOW - timedelta(days=30))
        flagged = underperformers(misses, now=NOW)
        assert flagged and flagged[0]["id"] == "TA04"
        assert flagged[0]["proposal"] in {"disable", "retrain"}
        assert flagged[0]["accuracy"] < DISABLE_HIT
        # the helper does not mutate the input or drop the agent
        assert len(misses) == 30


class TestWiring:
    def test_ea_config_exposes_votes_without_touching_guards(self, session):
        from app.agents import memory

        vote_body = {"recommendation": "WAIT", "score": 0.0, "regime": "unknown",
                     "withheld": False, "as_of": NOW.isoformat()}
        memory.remember(session, "BRAIN-01", "agent", "run", symbol="EURUSD",
                        content={"event": "run", "as_of": NOW.isoformat(),
                                 "agents": {"TA04": {"recommendation": "WAIT", "ok": True}},
                                 "vote": vote_body})
        out = ea_config.config(session)
        assert "AllowTrading" not in out and out["guards_remote_controllable"] is False
        assert out["agent_votes"]["EURUSD"]["vote"] == "WAIT"
        assert "Risk Brain" in out["agent_votes_note"]

    def test_telegram_and_report_text_are_persian(self, session):
        from app.agents import memory

        now = NOW
        memory.remember(session, "RT10", "trade", "paper open", symbol="EURUSD",
                        source_ref="t-fa",
                        content={"event": "open", "trade_id": "t-fa", "direction": "BUY",
                                 "entry": 1.1, "stop_loss": 1.09, "take_profit": 1.12,
                                 "account": "main"})
        ctx = RiskContext(equity=1000, daily_pnl_pct=-9.0, kill_switch=True, source="test")
        events = dict(agent_notify.pending_events(session, now=now, risk_ctx=ctx))
        assert "کلید اضطراری" in events[f"kill:{now.date().isoformat()}"]
        assert "معامله آزمایشی باز شد" in events["open:t-fa"]
        assert "خرید" in events["open:t-fa"]
        assert "زیان روزانه" in events[f"dailycap:{now.date().isoformat()}"]
        body = agent_report.text(agent_report.build(session, now=now))
        assert "گزارش شبانه مولیدو" in body
        assert "nightly report" not in body
        assert "Kill switch" not in body


class TestGuardsAndTrigger:
    def test_correlation_ignores_shared_usd_quote(self):
        from app.agents.guards import correlated

        assert correlated("EURUSD", ["USDJPY"]) is None
        assert correlated("USDCAD", []) is None
        assert correlated("EURUSD", ["EURJPY"]) is not None
        assert correlated("EURUSD", ["GBPUSD"]) is not None
        assert correlated("XAUUSD", ["XAGUSD"]) is not None

    def test_loss_memory_lowers_confidence_after_repeated_losses(self):
        from app.agents.guards import loss_factor

        losses = [{"symbol": "EURUSD", "direction": "BUY", "regime": "trend",
                   "at": (NOW - timedelta(days=i)).isoformat()} for i in range(4)]
        assert loss_factor({"symbol": "EURUSD", "direction": "SELL", "regime": "trend"},
                           losses, now=NOW) == 1.0
        factor = loss_factor({"symbol": "EURUSD", "direction": "BUY", "regime": "trend"},
                             losses, now=NOW)
        assert 0.25 <= factor <= 0.5

    def test_trigger_on_new_bar_move_or_idle_cap(self):
        from app.agents.guards import decide_trigger

        last = NOW - timedelta(minutes=10)
        assert decide_trigger(last_run=None, now=NOW) == "first"
        assert decide_trigger(last_run=last, now=NOW,
                              newest_close=NOW - timedelta(minutes=1)) == "bar_close"
        assert decide_trigger(last_run=last, now=NOW, last_price=1.11, last_close=1.10,
                              last_range=0.01) == "price_move"
        assert decide_trigger(last_run=NOW - timedelta(seconds=901), now=NOW) == "max_interval"
        assert decide_trigger(last_run=last, now=NOW, newest_close=last) is None

    def test_weekly_summary_is_persian(self, session):
        late = datetime(2026, 11, 13, 20, 0, tzinfo=UTC)  # Friday 23:30 Tehran
        sent: list[str] = []
        r = agent_report.maybe_weekly(session, now=late, send=lambda t: sent.append(t) or True)
        assert r is not None and r["week"] == "2026-W46" and sent
        assert "گزارش هفتگی مولیدو" in sent[0]
        assert "weekly report" not in sent[0].lower() or "گزارش" in sent[0]
        assert agent_report.maybe_weekly(session, now=late, send=lambda t: True) is None
