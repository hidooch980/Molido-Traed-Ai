"""The gateway itself: one async entry point, `ask`.

Order of checks, cheapest and safest first: enabled -> prompt size -> budget
-> cache -> in-flight dedup -> circuit breaker -> queue/concurrency -> call
with timeout and bounded exponential backoff -> ledger. Every outcome is a
`GatewayResult` with a status; nothing raises to the caller, because the
caller's correct reaction to any failure is the same: abstain.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.agents.gateway import config as cfg
from app.agents.gateway.breaker import CircuitBreaker
from app.agents.gateway.budget import Budget
from app.agents.gateway.config import Complexity, GatewayConfig, Priority
from app.agents.gateway.limiter import PriorityLimiter, QueueFullError
from app.agents.gateway.transport import HttpxTransport, Transport

RETRY_STATUSES = frozenset({408, 409, 429, 500, 502, 503, 504})


class Status(StrEnum):
    OK = "ok"
    DISABLED = "disabled"
    BUDGET = "budget_refused"
    TOO_LARGE = "prompt_too_large"
    CIRCUIT_OPEN = "circuit_open"
    QUEUE_FULL = "queue_full"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass(frozen=True)
class AgentRequest:
    agent_id: str
    system: str
    prompt: str
    priority: Priority = Priority.NORMAL
    complexity: Complexity = Complexity.STANDARD
    max_output_tokens: int | None = None


@dataclass(frozen=True)
class GatewayResult:
    status: Status
    agent_id: str
    model: str = ""
    text: str = ""
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float | None = None
    latency_ms: int = 0
    cache_hit: bool = False
    detail: str = ""
    request_hash: str = ""

    @property
    def ok(self) -> bool:
        return self.status is Status.OK

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


Ledger = Callable[[AgentRequest, GatewayResult, Priority], None]


def approx_tokens(text: str) -> int:
    """Conservative pre-flight estimate (~4 chars/token, rounded up)."""
    return (len(text) + 3) // 4


def parse_response(payload: dict[str, Any]) -> tuple[str, dict[str, int]]:
    parts: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and content.get("type") == "output_text":
                parts.append(str(content.get("text") or ""))
    usage = payload.get("usage") or {}
    details_in = usage.get("input_tokens_details") or {}
    details_out = usage.get("output_tokens_details") or {}
    return "".join(parts), {
        "input": int(usage.get("input_tokens") or 0),
        "cached": int(details_in.get("cached_tokens") or 0),
        "output": int(usage.get("output_tokens") or 0),
        "reasoning": int(details_out.get("reasoning_tokens") or 0),
    }


@dataclass
class GrokGateway:
    config: GatewayConfig = field(default_factory=GatewayConfig.from_env)
    transport: Transport = field(default_factory=HttpxTransport)
    ledger: Ledger | None = None
    clock: Callable[[], float] = field(default=time.monotonic)
    sleep: Callable[[float], Awaitable[None]] = field(default=asyncio.sleep)
    key_source: Callable[[], str] = field(default=cfg.api_key)
    budget: Budget | None = None
    breaker: CircuitBreaker | None = None

    def __post_init__(self) -> None:
        c = self.config
        self.budget = self.budget or Budget(c.daily_token_limit, c.daily_usd_limit, c.economy_at)
        self.breaker = self.breaker or CircuitBreaker(
            c.breaker_threshold, c.breaker_cooldown_seconds, self.clock
        )
        self.limiter = PriorityLimiter(c.max_concurrency, c.max_queue)
        self._cache: OrderedDict[str, tuple[float, GatewayResult]] = OrderedDict()
        self._inflight: dict[str, asyncio.Future[GatewayResult]] = {}
        self.calls = 0  # network attempts actually made

    # ------------------------------------------------------------ public
    def status(self) -> dict[str, Any]:
        assert self.budget is not None and self.breaker is not None
        return {
            "enabled": bool(self.key_source()),
            "budget": self.budget.snapshot(),
            "circuit": self.breaker.state,
            "active": self.limiter.active,
            "waiting": self.limiter.waiting,
            "cache_entries": len(self._cache),
            "config": self.config.public(),
        }

    async def ask(self, request: AgentRequest) -> GatewayResult:
        assert self.budget is not None and self.breaker is not None
        key = self.key_source()
        if not key:
            return self._done(request, GatewayResult(Status.DISABLED, request.agent_id,
                                                     detail="XAI_API_KEY is not set"))
        if approx_tokens(request.system + request.prompt) > self.config.max_prompt_tokens:
            return self._done(request, GatewayResult(Status.TOO_LARGE, request.agent_id,
                                                     detail="prompt exceeds max_prompt_tokens"))
        if not self.budget.allows(request.priority):
            return self._done(request, GatewayResult(
                Status.BUDGET, request.agent_id,
                detail=f"budget mode {self.budget.mode().value} refuses {request.priority.name}",
            ))

        complexity = self.budget.complexity(request.complexity)
        model = self.config.models[complexity]
        max_out = min(request.max_output_tokens or self.config.max_output_tokens,
                      self.config.max_output_tokens)
        digest = self._hash(request, model, max_out)

        cached = self._cache_get(digest)
        if cached is not None:
            return self._done(request, self._as_hit(cached), charge=False)

        pending = self._inflight.get(digest)
        if pending is not None:
            shared = await asyncio.shield(pending)
            return self._done(request, self._as_hit(shared), charge=False)

        future: asyncio.Future[GatewayResult] = asyncio.get_running_loop().create_future()
        self._inflight[digest] = future
        try:
            result = await self._call(request, key, model, max_out, digest)
            if result.ok:
                self._cache_put(digest, result)
            future.set_result(result)
            return self._done(request, result)
        except BaseException as exc:  # never leave dedup waiters hanging
            if not future.done():
                future.set_result(GatewayResult(Status.ERROR, request.agent_id, model=model,
                                                detail=type(exc).__name__))
            raise
        finally:
            self._inflight.pop(digest, None)

    # ----------------------------------------------------------- private
    @staticmethod
    def _as_hit(source: GatewayResult) -> GatewayResult:
        """A reuse spends nothing: zero tokens, zero cost (unknown stays unknown)."""
        return GatewayResult(**{
            **source.__dict__, "cache_hit": True, "latency_ms": 0, "input_tokens": 0,
            "cached_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0,
            "cost_usd": 0.0 if source.cost_usd is not None else None,
        })

    def _hash(self, request: AgentRequest, model: str, max_out: int) -> str:
        raw = json.dumps([request.agent_id, model, request.system, request.prompt, max_out])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _cache_get(self, digest: str) -> GatewayResult | None:
        entry = self._cache.get(digest)
        if entry is None:
            return None
        expires, result = entry
        if self.clock() >= expires:
            self._cache.pop(digest, None)
            return None
        self._cache.move_to_end(digest)
        return result

    def _cache_put(self, digest: str, result: GatewayResult) -> None:
        self._cache[digest] = (self.clock() + self.config.cache_ttl_seconds, result)
        self._cache.move_to_end(digest)
        while len(self._cache) > self.config.cache_max_entries:
            self._cache.popitem(last=False)

    def _done(self, request: AgentRequest, result: GatewayResult, *,
              charge: bool = True) -> GatewayResult:
        assert self.budget is not None
        if charge and result.ok:
            self.budget.charge(result.total_tokens, result.cost_usd)
        if self.ledger is not None:
            try:
                self.ledger(request, result, request.priority)
            except Exception:  # noqa: BLE001,S110 - a ledger fault must not break advice
                pass
        return result

    async def _call(self, request: AgentRequest, key: str, model: str, max_out: int,
                    digest: str) -> GatewayResult:
        assert self.breaker is not None
        if not self.breaker.allow():
            return GatewayResult(Status.CIRCUIT_OPEN, request.agent_id, model=model,
                                 detail="circuit breaker open", request_hash=digest)
        try:
            await self.limiter.acquire(int(request.priority))
        except QueueFullError:
            return GatewayResult(Status.QUEUE_FULL, request.agent_id, model=model,
                                 detail="queue full", request_hash=digest)
        try:
            return await self._attempts(request, key, model, max_out, digest)
        finally:
            self.limiter.release()

    async def _attempts(self, request: AgentRequest, key: str, model: str, max_out: int,
                        digest: str) -> GatewayResult:
        assert self.breaker is not None
        body = {
            "model": model,
            "instructions": request.system,
            "input": request.prompt,
            "max_output_tokens": max_out,
            "temperature": self.config.temperature,
            "store": False,
            "prompt_cache_key": request.agent_id,
        }
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        url = self.config.base_url.rstrip("/") + "/responses"
        last = GatewayResult(Status.ERROR, request.agent_id, model=model, request_hash=digest)
        started = self.clock()
        for attempt in range(self.config.max_retries + 1):
            if attempt:
                delay = min(self.config.backoff_max_seconds,
                            self.config.backoff_base_seconds * (2 ** (attempt - 1)))
                await self.sleep(delay)
            self.calls += 1
            try:
                code, payload = await asyncio.wait_for(
                    self.transport.post(url, headers, body, self.config.timeout_seconds),
                    timeout=self.config.timeout_seconds,
                )
            except TimeoutError:
                last = GatewayResult(Status.TIMEOUT, request.agent_id, model=model,
                                     detail="timed out", request_hash=digest)
                continue
            except Exception as exc:  # noqa: BLE001 - transport faults are retryable
                last = GatewayResult(Status.ERROR, request.agent_id, model=model,
                                     detail=f"transport: {type(exc).__name__}",
                                     request_hash=digest)
                continue
            if code == 200:
                text, usage = parse_response(payload)
                price = self.config.pricing.get(model)
                cost = (price.cost(usage["input"], usage["cached"], usage["output"])
                        if price else None)
                self.breaker.success()
                return GatewayResult(
                    Status.OK, request.agent_id, model=model, text=text,
                    input_tokens=usage["input"], cached_tokens=usage["cached"],
                    output_tokens=usage["output"], reasoning_tokens=usage["reasoning"],
                    cost_usd=cost, latency_ms=int((self.clock() - started) * 1000),
                    request_hash=digest,
                )
            last = GatewayResult(Status.ERROR, request.agent_id, model=model,
                                 detail=f"http {code}", request_hash=digest)
            if code not in RETRY_STATUSES:
                break
        self.breaker.failure()
        return last
