"""Stage 5: traceable memory; learning never promotes itself."""

from __future__ import annotations

import importlib

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from app.agents import memory
from app.agents.council.shadow import evaluate
from app.models.agent_memory import (
    AgentMemoryEntry,
    CouncilDecisionRecord,
    FailureRecord,
    LearningRecord,
)

WORLD = {"symbol": "EURUSD", "timeframe": "H1", "macro": {"rate_differential": 3},
         "quant": {"zscore": -2.5}}


class TestAgentMemory:
    def test_remember_and_recall(self, session):
        memory.remember(session, "RT01", "rocket", "burst on EURUSD", symbol="eurusd",
                        content={"atr_x": 3.1}, source_ref="bar:EURUSD:M5:2026-11-14T10:00Z")
        memory.remember(session, "TA04", "regime", "trend up")
        rows = memory.recall(session, agent_id="RT01")
        assert len(rows) == 1 and rows[0].symbol == "EURUSD" and rows[0].source_ref
        assert len(memory.recall(session, kind="regime")) == 1

    def test_unknown_agent_or_kind_refused(self, session):
        with pytest.raises(ValueError):
            memory.remember(session, "ZZ01", "rocket", "x")
        with pytest.raises(ValueError):
            memory.remember(session, "RT01", "gossip", "x")


class TestCouncilMemory:
    def test_shadow_record_roundtrip_and_resolution_once(self, session):
        record = evaluate(WORLD)
        row = memory.record_council(session, record)
        assert row.mode == "shadow" and row.opinions
        memory.resolve_council(session, row.id, 1.0)
        with pytest.raises(ValueError):
            memory.resolve_council(session, row.id, -1.0)

    def test_credibility_comes_from_resolved_outcomes(self, session):
        shadow = {"symbol": "EURUSD", "mode": "shadow",
                  "verdict": {"direction": "BUY", "score": 0.5, "weights_version": 1},
                  "opinions": [{"member": "macro", "direction": "BUY", "abstained": False},
                               {"member": "quant", "direction": "SELL", "abstained": False}]}
        for _ in range(5):
            row = memory.record_council(session, shadow)
            memory.resolve_council(session, row.id, 1.0)
        book = memory.credibility_from_decisions(session)
        assert book.credibility("macro") > 0.5 > book.credibility("quant")


class TestFailuresAndLearning:
    def test_failure_categories(self, session):
        memory.record_failure(session, "false_breakout", "broke and returned", agent_id="RT03")
        with pytest.raises(ValueError):
            memory.record_failure(session, "bad_luck", "x")

    def test_no_auto_promotion(self, session):
        rec = memory.propose_learning(session, "AI03", {"weights": {"macro": 0.6}})
        with pytest.raises(ValueError):
            memory.decide_learning(session, rec.id, approve=True, decided_by="owner")
        with pytest.raises(ValueError):
            memory.validate_learning(session, rec.id, {"method": "wf", "result": 1})
        memory.validate_learning(session, rec.id,
                                 {"method": "walk_forward", "out_of_sample": True, "result": {}})
        with pytest.raises(ValueError):
            memory.decide_learning(session, rec.id, approve=True, decided_by=" ")
        done = memory.decide_learning(session, rec.id, approve=True, decided_by="owner")
        assert done.status == "APPROVED" and done.decided_by == "owner"
        with pytest.raises(ValueError):
            memory.decide_learning(session, rec.id, approve=False, decided_by="owner")

    def test_nothing_in_app_approves_automatically(self):
        import pathlib

        root = pathlib.Path(memory.__file__).resolve().parents[1]
        callers = [p for p in root.rglob("*.py")
                   if "decide_learning(" in p.read_text(encoding="utf-8")
                   and p.name != "memory.py"]
        assert callers == []


def test_migration_matches_models():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    mod = importlib.import_module("app.db.alembic.versions.0031_agent_memory")
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            mod.upgrade()
        insp = inspect(conn)
        for model in (AgentMemoryEntry, CouncilDecisionRecord, FailureRecord, LearningRecord):
            cols = {c["name"] for c in insp.get_columns(model.__tablename__)}
            assert cols == {c.name for c in model.__table__.columns}, model.__tablename__
        with Operations.context(MigrationContext.configure(conn)):
            mod.downgrade()
        assert not {"agent_memory", "agent_failures"} & set(inspect(conn).get_table_names())


@pytest.fixture()
def client(session):
    from app.db.session import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_read_endpoints(client, session):
    memory.remember(session, "SM03", "pattern", "order block H1")
    memory.record_council(session, evaluate(WORLD))
    session.flush()
    assert client.get("/api/v1/agents/memory?agent_id=SM03").json()["entries"][0]["kind"] == \
        "pattern"
    assert client.get("/api/v1/agents/council/decisions").json()["decisions"]
    assert client.get("/api/v1/agents/failures").json() == {"failures": []}
    assert client.get("/api/v1/agents/learning").json() == {"records": []}
