"""Stage 4: council v2 - abstain-first, credibility from results, conflict -> WAIT."""

from __future__ import annotations

import pytest

from app.agents.council import analysts
from app.agents.council.analysts import Opinion, adversary, convene
from app.agents.council.credibility import CredibilityBook, Record
from app.agents.council.meta import aggregate
from app.agents.council.shadow import evaluate, live_flag
from app.agents.council.weights import WeightStore


def world(**blocks):
    return {"symbol": "EURUSD", "timeframe": "H1", **blocks}


class TestAbstainFirst:
    def test_empty_world_every_member_abstains(self):
        ops = convene(world())
        assert all(o.abstained for o in ops)

    @pytest.mark.parametrize("name", list(analysts.MEMBERS))
    def test_malformed_blocks_abstain(self, name):
        bad = {"macro": {"rate_differential": "x"}, "news": {"minutes_to_high_impact": None},
               "sentiment": {"speculative_net_long_share": 3.0}, "quant": {"zscore": True},
               "execution": {"spread_to_atr": -1}}
        assert analysts.MEMBERS[name](world(**bad)).abstained

    def test_directions(self):
        assert analysts.macro(world(macro={"rate_differential": 3})).direction == "BUY"
        assert analysts.quant(world(quant={"zscore": 2.5})).direction == "SELL"
        assert analysts.sentiment(
            world(sentiment={"speculative_net_long_share": 0.9})).direction == "SELL"

    def test_news_and_execution_are_directionless_objectors(self):
        n = analysts.news(world(news={"minutes_to_high_impact": 10}))
        e = analysts.execution(world(execution={"spread_to_atr": 0.3}))
        assert n.score == 0 and n.objection and e.score == 0 and e.objection


def op(member, score):
    return Opinion(member, False, score, 0.9, ("x",))


class TestMeta:
    def test_quorum_required(self):
        v = aggregate([op("macro", 0.9)], WeightStore().current())
        assert v.direction == "WAIT" and "insufficient" in v.reasons[0]

    def test_agreement_gives_direction(self):
        v = aggregate([op("macro", 0.6), op("quant", 0.4)], WeightStore().current())
        assert v.direction == "BUY"

    def test_strong_conflict_forces_wait(self):
        v = aggregate([op("macro", 0.9), op("quant", -0.9)], WeightStore().current())
        assert v.direction == "WAIT" and v.conflicts == (("macro", "quant"),)

    def test_objection_downgrades_weak_case(self):
        ops = [op("macro", 0.3), op("quant", 0.3),
               Opinion("news", False, 0.0, 0.8, ("event",), objection=True)]
        assert aggregate(ops, WeightStore().current()).direction == "WAIT"

    def test_confidence_does_not_change_weights(self):
        hi = [Opinion("macro", False, 0.6, 1.0), Opinion("quant", False, -0.2, 1.0)]
        lo = [Opinion("macro", False, 0.6, 0.0), Opinion("quant", False, -0.2, 0.0)]
        a, b = aggregate(hi, WeightStore().current()), aggregate(lo, WeightStore().current())
        assert a.score == b.score and a.weights_used == b.weights_used


class TestCredibility:
    def test_only_out_of_sample_counts(self):
        book = CredibilityBook()
        for _ in range(50):
            book.add(Record("quant", "BUY", 1.0, out_of_sample=False))
        assert book.credibility("quant") == 0.5 and book.factor("quant") == 1.0

    def test_shrinkage_and_effect_on_weight(self):
        book = CredibilityBook()
        book.add(Record("macro", "BUY", 1.0, True))
        assert 0.5 < book.credibility("macro") < 0.56  # one win earns little
        for _ in range(60):
            book.add(Record("quant", "SELL", -1.0, True))
        v = aggregate([op("macro", 0.6), op("quant", 0.6)], WeightStore().current(), book)
        assert v.weights_used["quant"] < 0.6 * 0.5

    def test_stats(self):
        book = CredibilityBook([Record("macro", "BUY", 2.0, True), Record("macro", "SELL", -1, True)])
        s = book.stats()["macro"]
        assert s["n"] == 2 and s["wins"] == 1 and s["avg_r"] == 0.5


class TestWeights:
    def test_versioning_and_rollback(self, tmp_path):
        path = tmp_path / "w.json"
        store = WeightStore(path)
        v2 = store.propose({"macro": 1.0}, reason="test", author="owner")
        back = store.rollback(1, reason="worse", author="owner")
        assert v2.version == 2 and back.version == 3
        assert back.weights == store.history[0].weights
        assert WeightStore(path).current().version == 3  # survives restart

    def test_changes_need_reason_and_no_negatives(self):
        store = WeightStore()
        with pytest.raises(ValueError):
            store.propose({"macro": 1.0}, reason="", author="x")
        with pytest.raises(ValueError):
            store.propose({"macro": -1.0}, reason="r", author="x")


class TestShadow:
    def test_flag_defaults_off_and_never_wired(self, monkeypatch):
        monkeypatch.delenv("MOLIDO_AGENT_COUNCIL_LIVE", raising=False)
        logged = []
        rec = evaluate(world(macro={"rate_differential": 3}, quant={"zscore": -2}),
                       sink=logged.append)
        assert live_flag() is False and rec["mode"] == "shadow"
        assert rec["wired_into_decisions"] is False and logged == [rec]
        assert rec["verdict"]["authority"].startswith("advisory")

    def test_adversary_attacks_majority(self):
        a = adversary([op("macro", 0.6), op("quant", -0.6), op("sentiment", 0.6)])
        assert a.objection and a.score < 0
