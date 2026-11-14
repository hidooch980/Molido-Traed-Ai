"""Grok Gateway with a fake transport. No network, no key in any output."""

from __future__ import annotations

import asyncio
import importlib
import json
from datetime import UTC, date, datetime

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from app.agents.gateway.advisor import advise, to_message
from app.agents.gateway.breaker import CircuitBreaker
from app.agents.gateway.budget import Budget, BudgetMode
from app.agents.gateway.config import (
    Complexity,
    GatewayConfig,
    ModelPrice,
    Priority,
    parse_pricing,
)
from app.agents.gateway.gateway import AgentRequest, GrokGateway, Status, parse_response
from app.agents.gateway.ledger import row_for, usage_summary
from app.agents.gateway.limiter import PriorityLimiter, QueueFullError
from app.agents.gateway.prompts import system_prompt
from app.agents.messages import Market, Recommendation
from app.models.agent_usage import AgentLlmUsage

KEY = "test-key-not-real"
AS_OF = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


def ok_payload(text: str, inp: int = 100, out: int = 20, cached: int = 0) -> dict:
    return {
        "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
        "usage": {"input_tokens": inp, "input_tokens_details": {"cached_tokens": cached},
                  "output_tokens": out, "output_tokens_details": {"reasoning_tokens": 5}},
    }


ANSWER = json.dumps({"recommendation": "BUY", "confidence": 0.9, "analysis": "up",
                     "evidence": ["higher highs"], "risk": "normal"})


class FakeTransport:
    def __init__(self, responses=None, delay: float = 0.0):
        self.responses = list(responses or [])
        self.calls: list[dict] = []
        self.delay = delay

    async def post(self, url, headers, body, timeout):
        self.calls.append({"url": url, "headers": headers, "body": body})
        if self.delay:
            await asyncio.sleep(self.delay)
        item = self.responses.pop(0) if self.responses else (200, ok_payload(ANSWER))
        if isinstance(item, BaseException):
            raise item
        return item


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


async def no_sleep(_):
    return None


def make(transport=None, *, key=KEY, ledger=None, clock=None, **cfg):
    sleeps: list[float] = []

    async def sleep(d):
        sleeps.append(d)

    gw = GrokGateway(
        config=GatewayConfig(**cfg), transport=transport or FakeTransport(), ledger=ledger,
        clock=clock or Clock(), sleep=sleep, key_source=lambda: key,
    )
    gw.sleeps = sleeps  # type: ignore[attr-defined]
    return gw


def req(prompt="facts", agent="TA04", **kw):
    return AgentRequest(agent, system_prompt(agent), prompt, **kw)


def run(coro):
    return asyncio.run(coro)


class TestDisabledWithoutKey:
    def test_no_key_means_disabled_and_no_call(self):
        t = FakeTransport()
        result = run(make(t, key="").ask(req()))
        assert result.status is Status.DISABLED and t.calls == []

    def test_disabled_becomes_abstain(self):
        gw = make(key="")
        msg = run(advise(gw, "TA04", "x", market=Market.FOREX, symbol="EURUSD", as_of=AS_OF))
        assert msg.recommendation is Recommendation.ABSTAIN and msg.confidence == 0.0


class TestRequestShape:
    def test_endpoint_model_and_body(self):
        t = FakeTransport()
        result = run(make(t).ask(req(complexity=Complexity.DEEP)))
        call = t.calls[0]
        assert call["url"] == "https://api.x.ai/v1/responses"
        assert call["body"]["model"] == "grok-4.7"
        assert call["body"]["store"] is False
        assert call["body"]["prompt_cache_key"] == "TA04"
        assert call["headers"]["Authorization"] == f"Bearer {KEY}"
        assert result.ok and result.input_tokens == 100 and result.output_tokens == 20

    def test_key_is_not_in_result_or_public_config(self):
        gw = make()
        result = run(gw.ask(req()))
        assert KEY not in repr(result) and KEY not in json.dumps(gw.status(), default=str)

    def test_output_tokens_are_capped(self):
        t = FakeTransport()
        run(make(t, max_output_tokens=100).ask(req(max_output_tokens=5000)))
        assert t.calls[0]["body"]["max_output_tokens"] == 100

    def test_oversized_prompt_refused_without_call(self):
        t = FakeTransport()
        result = run(make(t, max_prompt_tokens=64).ask(req("x" * 5000)))
        assert result.status is Status.TOO_LARGE and t.calls == []

    def test_parse_response(self):
        text, usage = parse_response(ok_payload("hi", 10, 3, 4))
        assert text == "hi" and usage == {"input": 10, "cached": 4, "output": 3, "reasoning": 5}


class TestCacheAndDedup:
    def test_ttl_cache_hit_then_expiry(self):
        clock = Clock()
        t = FakeTransport()
        gw = make(t, clock=clock, cache_ttl_seconds=10)
        first = run(gw.ask(req()))
        second = run(gw.ask(req()))
        assert first.ok and second.cache_hit and len(t.calls) == 1
        clock.t = 11
        run(gw.ask(req()))
        assert len(t.calls) == 2

    def test_concurrent_identical_requests_share_one_call(self):
        t = FakeTransport(delay=0.01)
        gw = make(t)

        async def both():
            return await asyncio.gather(gw.ask(req()), gw.ask(req()), gw.ask(req()))

        results = run(both())
        assert len(t.calls) == 1 and all(r.ok for r in results)
        assert sum(r.cache_hit for r in results) == 2


class TestRetryBackoffBreaker:
    def test_retries_retryable_status_with_exponential_backoff(self):
        t = FakeTransport([(503, {}), (429, {}), (200, ok_payload(ANSWER))])
        gw = make(t, max_retries=2, backoff_base_seconds=1.0)
        assert run(gw.ask(req())).ok
        assert gw.sleeps == [1.0, 2.0]

    def test_non_retryable_status_stops_at_once(self):
        t = FakeTransport([(401, {})])
        result = run(make(t, max_retries=3).ask(req()))
        assert result.status is Status.ERROR and len(t.calls) == 1

    def test_timeout_is_bounded(self):
        t = FakeTransport([TimeoutError(), TimeoutError()])
        result = run(make(t, max_retries=1).ask(req()))
        assert result.status is Status.TIMEOUT and len(t.calls) == 2

    def test_breaker_opens_then_half_opens(self):
        clock = Clock()
        t = FakeTransport([(500, {})] * 10)
        gw = make(t, clock=clock, max_retries=0, breaker_threshold=2,
                  breaker_cooldown_seconds=30)
        run(gw.ask(req("a")))
        run(gw.ask(req("b")))
        blocked = run(gw.ask(req("c")))
        assert blocked.status is Status.CIRCUIT_OPEN and len(t.calls) == 2
        clock.t = 31
        t.responses = [(200, ok_payload(ANSWER))]
        assert run(gw.ask(req("d"))).ok
        assert gw.breaker.state == "closed"

    def test_breaker_unit(self):
        clock = Clock()
        b = CircuitBreaker(threshold=1, cooldown=5, clock=clock)
        b.failure()
        assert not b.allow()
        clock.t = 6
        assert b.allow() and not b.allow()  # one probe only


class TestLimiter:
    def test_priority_order_and_bounded_queue(self):
        async def scenario():
            lim = PriorityLimiter(limit=1, max_queue=2)
            await lim.acquire(2)
            order: list[int] = []

            async def waiter(p):
                await lim.acquire(p)
                order.append(p)
                lim.release()

            tasks = [asyncio.create_task(waiter(3)), asyncio.create_task(waiter(0))]
            await asyncio.sleep(0)
            with pytest.raises(QueueFullError):
                await lim.acquire(1)
            lim.release()
            await asyncio.gather(*tasks)
            return order, lim.active

        order, active = run(scenario())
        assert order == [0, 3] and active == 0

    def test_queue_full_is_reported_not_raised(self):
        t = FakeTransport(delay=0.05)
        gw = make(t, max_concurrency=1, max_queue=0)

        async def two():
            return await asyncio.gather(gw.ask(req("a")), gw.ask(req("b")))

        statuses = {r.status for r in run(two())}
        assert statuses == {Status.OK, Status.QUEUE_FULL}


class TestBudget:
    def test_modes(self):
        b = Budget(daily_token_limit=1000, economy_at=0.7, today=lambda: date(2026, 1, 1))
        assert b.mode() is BudgetMode.NORMAL and b.allows(Priority.LOW)
        b.charge(700, None)
        assert b.mode() is BudgetMode.ECONOMY
        assert not b.allows(Priority.NORMAL) and b.allows(Priority.HIGH)
        assert b.complexity(Complexity.DEEP) is Complexity.STANDARD
        b.charge(300, None)
        assert b.mode() is BudgetMode.EMERGENCY and not b.allows(Priority.CRITICAL)

    def test_day_rollover_resets(self):
        day = {"d": date(2026, 1, 1)}
        b = Budget(daily_token_limit=10, today=lambda: day["d"])
        b.charge(10, None)
        assert b.mode() is BudgetMode.EMERGENCY
        day["d"] = date(2026, 1, 2)
        assert b.mode() is BudgetMode.NORMAL

    def test_usd_limit_binds_only_when_priced(self):
        b = Budget(daily_token_limit=10**9, daily_usd_limit=1.0, today=lambda: date(2026, 1, 1))
        b.charge(10, 1.0)
        assert b.mode() is BudgetMode.EMERGENCY

    def test_gateway_refuses_when_budget_exhausted(self):
        t = FakeTransport()
        gw = make(t, daily_token_limit=50)
        assert run(gw.ask(req("a"))).ok  # 120 tokens -> over limit
        assert run(gw.ask(req("b"))).status is Status.BUDGET and len(t.calls) == 1


class TestPricing:
    def test_no_pricing_means_unknown_cost(self):
        assert run(make().ask(req())).cost_usd is None

    def test_configured_pricing(self):
        price = ModelPrice(input=2.0, cached_input=0.5, output=6.0)
        gw = make(FakeTransport([(200, ok_payload(ANSWER, 1_000_000, 1_000_000, 0))]),
                  pricing={"grok-4.3": price})
        assert run(gw.ask(req())).cost_usd == pytest.approx(8.0)

    def test_long_context_rates(self):
        p = ModelPrice(1, 0, 1, long_context_threshold=100, long_input=2, long_output=2)
        assert p.cost(100, 0, 0) == pytest.approx(200 / 1e6)

    def test_bad_pricing_json_is_ignored(self):
        assert parse_pricing("{nope") == {} and parse_pricing("") == {}


class TestAdvisor:
    def test_valid_answer_becomes_message(self):
        result = run(make().ask(req()))
        msg = to_message(result, market=Market.FOREX, symbol="EURUSD", timeframe=None,
                         as_of=AS_OF)
        assert msg.recommendation is Recommendation.BUY and msg.data_source == "grok-gateway"

    def test_llm_block_is_read_as_wait(self):
        text = json.dumps({"recommendation": "BLOCK", "evidence": ["x"]})
        gw = make(FakeTransport([(200, ok_payload(text))]))
        msg = run(advise(gw, "TA04", "f", market=Market.FOREX, symbol="EURUSD", as_of=AS_OF))
        assert msg.recommendation is Recommendation.WAIT

    def test_garbage_and_direction_without_evidence(self):
        gw = make(FakeTransport([(200, ok_payload("not json"))]))
        msg = run(advise(gw, "TA04", "f", market=Market.FOREX, symbol="EURUSD", as_of=AS_OF))
        assert msg.recommendation is Recommendation.ABSTAIN
        text = json.dumps({"recommendation": "SELL", "evidence": []})
        gw = make(FakeTransport([(200, ok_payload(text))]))
        msg = run(advise(gw, "TA04", "g", market=Market.FOREX, symbol="EURUSD", as_of=AS_OF))
        assert msg.recommendation is Recommendation.WAIT

    def test_prompt_carries_identity_and_restrictions(self):
        prompt = system_prompt("RT01")
        assert "RT01" in prompt and "Risk Brain" in prompt and "ABSTAIN" in prompt


class TestLedger:
    def test_rows_and_summary(self, session):
        gw = make(ledger=lambda r, res, p: session.add(row_for(res, p)))
        run(gw.ask(req("a")))
        run(gw.ask(req("a")))  # cache hit, still ledgered
        run(make(key="", ledger=lambda r, res, p: session.add(row_for(res, p))).ask(req()))
        session.flush()
        summary = usage_summary(session)
        ta = summary["agents"][0]
        assert ta["requests"] == 3 and ta["ok"] == 2 and ta["total_tokens"] == 120
        assert summary["cost_usd"] is None

    def test_ledger_failure_does_not_break_advice(self):
        def broken(*_):
            raise RuntimeError("db down")

        assert run(make(ledger=broken).ask(req())).ok

    def test_migration_matches_model(self):
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        mod = importlib.import_module("app.db.alembic.versions.0030_agent_llm_usage")
        with engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                mod.upgrade()
            cols = {c["name"] for c in inspect(conn).get_columns("agent_llm_usage")}
            assert cols == {c.name for c in AgentLlmUsage.__table__.columns}
            with Operations.context(MigrationContext.configure(conn)):
                mod.downgrade()
            assert "agent_llm_usage" not in inspect(conn).get_table_names()
        assert sa  # imported for parity with other migration tests


@pytest.fixture()
def client(session):
    from app.db.session import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestEndpoints:
    def test_gateway_status_without_key(self, client, monkeypatch):
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        body = client.get("/api/v1/agents/gateway").json()
        assert body["enabled"] is False and body["budget"]["mode"] == "NORMAL"

    def test_gateway_status_never_shows_key(self, client, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", KEY)
        response = client.get("/api/v1/agents/gateway")
        assert response.json()["enabled"] is True and KEY not in response.text

    def test_usage_endpoint_empty(self, client):
        body = client.get("/api/v1/agents/gateway/usage").json()
        assert body["requests"] == 0 and body["agents"] == [] and body["cost_usd"] is None
