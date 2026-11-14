"""Stage 17: per-account paper books, self-healing and shadow ensemble learning."""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta

from app.agents import memory, selfheal
from app.agents.analyzers.runner import ANALYZERS, run_timed
from app.agents.selfheal import Sample
from app.services import agent_learning, agent_paper
from tests.test_agents_analyzers import ctx_for, walk

T = datetime(2026, 9, 1, tzinfo=UTC)


def samples(n, good="SC03", bad="SC04", seed=1):
    rnd, out = random.Random(seed), []
    for i in range(n):
        move = rnd.choice([1.0, -1.0]) * 0.001
        right = "BUY" if move > 0 else "SELL"
        wrong = "SELL" if move > 0 else "BUY"
        calls = {good: right if rnd.random() < 0.75 else wrong,
                 bad: wrong if rnd.random() < 0.75 else right}
        out.append(Sample(T + timedelta(hours=i), calls, move))
    return out


def test_finite_output():
    assert selfheal.finite_output(0.5)
    assert not selfheal.finite_output(math.nan) and not selfheal.finite_output(1.5)


def test_quarantine_and_retry():
    err = {"ok": False, "error": "x"}
    ok = {"ok": True}
    skip = {"ok": True, "skipped": True}
    assert selfheal.quarantined([{"A": err}] * 3, ["A"]) == {"A"}
    assert selfheal.quarantined([{"A": err}, {"A": err}, {"A": ok}], ["A"]) == set()
    assert selfheal.quarantined([{"A": skip}] * 2 + [{"A": err}] * 3, ["A"]) == {"A"}
    assert selfheal.quarantined([{"A": skip}] * 4 + [{"A": err}] * 3, ["A"]) == set()


def test_runner_skips_quarantined_and_flags_nan(monkeypatch):
    from app.agents.analyzers.common import message
    from app.agents.messages import Recommendation

    def nan_agent(ctx):
        return message("TA02", ctx, Recommendation.WAIT, 0.5, "x", ["e"]).model_copy(
            update={"confidence": math.nan})
    monkeypatch.setitem(ANALYZERS, "TA02", nan_agent)
    _, health = run_timed(ctx_for(walk(100)), {"TA03"})
    assert health["TA03"]["skipped"] and health["TA02"]["error"] == "non-finite output"


def test_fit_and_validate_prefer_the_reliable_agent():
    s = samples(300)
    w = selfheal.fit(s)
    assert w["SC03"] > 1.0 > w["SC04"]
    v = selfheal.validate(s, {})
    assert v["accept"] and v["candidate_hit"] > (v["current_hit"] or 0)


def test_no_auto_apply_without_a_clear_win():
    s = samples(300)
    best = selfheal.fit(s)
    assert not selfheal.validate(s, best)["accept"]


def test_rollback_rule():
    s = samples(100)
    bad = {"SC03": 0.25, "SC04": 2.0}
    back, hit, n = selfheal.should_roll_back(s, bad, previous_hit=0.7)
    assert back and n >= 30 and hit < 0.5
    assert selfheal.should_roll_back(s[:10], bad, 0.7)[0] is False


def test_weight_versions_are_logged_and_roll_back(session):
    assert agent_learning.current(session)["version"] == 0
    agent_learning._write(session, 1, {"SC03": 1.5}, "test", {"current_hit": 0.5}, 0, 0.6)
    agent_learning._write(session, 2, {"SC03": 0.3}, "test", {"current_hit": 0.6}, 1, 0.62)
    assert agent_learning.current(session)["version"] == 2
    cur = agent_learning.rollback_to(session, 1, "manual")
    assert cur["version"] == 3 and cur["weights"] == {"SC03": 1.5}
    st = agent_learning.status(session)
    assert [h["version"] for h in st["history"]][:3] == [3, 2, 1]
    assert "execution are not changed" in st["scope"]


def test_learning_cycle_runs_on_empty_history(session):
    rep = agent_learning.learning_cycle(session)
    assert rep["validation"]["accepted"] is False and rep["actions"] == []


def test_paper_books_are_per_account(session):
    sig = {"symbol": "EURUSD", "direction": "BUY", "timeframe": "H1", "mode": "paper",
           "trade_id": "t1", "event": "open"}
    memory.remember(session, "RT10", "trade", "a", content={**sig, "account": "a"})
    memory.remember(session, "RT10", "trade", "b", content={**sig, "trade_id": "t2",
                                                            "account": "b"})
    assert agent_paper.book(session, account="a")["open"] == 1
    assert agent_paper.book(session)["open"] == 2
    assert agent_paper.book(session)["accounts"] == ["a", "b"]


def test_all_accounts_isolates_failures(session, monkeypatch):
    from app.services import agent_paper as ap
    monkeypatch.setattr(ap, "bridge_dirs", lambda session=None: {"a": "/x", "b": "/y"})
    calls = []

    def fake(session, tf, *, account_key, now, record):
        calls.append((account_key, record))
        if account_key == "b":
            raise RuntimeError("bridge gone")
        return {"opened": 0}
    monkeypatch.setattr(ap, "run_cycle", fake)
    out = ap.run_all_accounts(session)
    assert calls == [("a", True), ("b", False)]
    assert "bridge gone" in out["accounts"]["b"]["error"]
