"""Gateway configuration, read from the environment.

Model names and the endpoint were checked against the official xAI docs on
2026-11-14 (https://docs.x.ai/docs/models, https://docs.x.ai/docs/api-reference:
`POST https://api.x.ai/v1/responses`, bearer auth, `usage.input_tokens`,
`usage.input_tokens_details.cached_tokens`, `usage.output_tokens`). They are
defaults, overridable by env, because xAI renames and reprices models.

**Prices are not in the code.** They come from `MOLIDO_XAI_PRICING_JSON`; with
none configured, cost is recorded as unknown (null) and only the token budget
binds. A made-up price is worse than an unknown one: it makes a budget look
enforced when it is not.

**The key is never stored on this object.** `api_key()` reads the environment
at the moment of the request, and nothing here serialises it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any

API_KEY_ENV = "XAI_API_KEY"
DEFAULT_BASE_URL = "https://api.x.ai/v1"


class Priority(IntEnum):
    """Lower runs first. LOW is optional work, the first thing budgets drop."""

    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


class Complexity(StrEnum):
    LIGHT = "light"
    STANDARD = "standard"
    DEEP = "deep"


@dataclass(frozen=True)
class ModelPrice:
    """USD per one million tokens, as configured by the operator."""

    input: float
    cached_input: float
    output: float
    #: Prompts at or above this many tokens bill every token at the long rates.
    long_context_threshold: int | None = None
    long_input: float | None = None
    long_cached_input: float | None = None
    long_output: float | None = None

    def cost(self, input_tokens: int, cached_tokens: int, output_tokens: int) -> float:
        long = (
            self.long_context_threshold is not None
            and input_tokens >= self.long_context_threshold
        )
        rate_in = (self.long_input if long and self.long_input is not None else self.input)
        rate_cached = (
            self.long_cached_input
            if long and self.long_cached_input is not None
            else self.cached_input
        )
        rate_out = self.long_output if long and self.long_output is not None else self.output
        fresh = max(0, input_tokens - cached_tokens)
        return (fresh * rate_in + cached_tokens * rate_cached + output_tokens * rate_out) / 1e6


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def parse_pricing(raw: str) -> dict[str, ModelPrice]:
    """`{"model": {"input": .., "cached_input": .., "output": ..}}`. Bad -> {}."""
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
        return {str(name): ModelPrice(**spec) for name, spec in data.items()}
    except (ValueError, TypeError):
        return {}


@dataclass(frozen=True)
class GatewayConfig:
    base_url: str = DEFAULT_BASE_URL
    models: dict[Complexity, str] = field(
        default_factory=lambda: {
            Complexity.LIGHT: "grok-4.3",
            Complexity.STANDARD: "grok-4.3",
            Complexity.DEEP: "grok-4.7",
        }
    )
    pricing: dict[str, ModelPrice] = field(default_factory=dict)
    max_concurrency: int = 2
    max_queue: int = 32
    timeout_seconds: float = 30.0
    max_retries: int = 2
    backoff_base_seconds: float = 1.0
    backoff_max_seconds: float = 8.0
    cache_ttl_seconds: float = 300.0
    cache_max_entries: int = 512
    max_prompt_tokens: int = 6000
    max_output_tokens: int = 600
    breaker_threshold: int = 5
    breaker_cooldown_seconds: float = 60.0
    daily_token_limit: int = 200_000
    daily_usd_limit: float | None = None
    economy_at: float = 0.7
    temperature: float = 0.2

    @classmethod
    def from_env(cls) -> GatewayConfig:
        usd = os.environ.get("MOLIDO_XAI_DAILY_USD_LIMIT", "").strip()
        return cls(
            base_url=os.environ.get("MOLIDO_XAI_BASE_URL", DEFAULT_BASE_URL),
            models={
                Complexity.LIGHT: os.environ.get("MOLIDO_XAI_MODEL_LIGHT", "grok-4.3"),
                Complexity.STANDARD: os.environ.get("MOLIDO_XAI_MODEL_STANDARD", "grok-4.3"),
                Complexity.DEEP: os.environ.get("MOLIDO_XAI_MODEL_DEEP", "grok-4.7"),
            },
            pricing=parse_pricing(os.environ.get("MOLIDO_XAI_PRICING_JSON", "")),
            max_concurrency=max(1, _int("MOLIDO_XAI_MAX_CONCURRENCY", 2)),
            max_queue=max(0, _int("MOLIDO_XAI_MAX_QUEUE", 32)),
            timeout_seconds=_float("MOLIDO_XAI_TIMEOUT_SECONDS", 30.0),
            max_retries=max(0, min(5, _int("MOLIDO_XAI_MAX_RETRIES", 2))),
            daily_token_limit=max(0, _int("MOLIDO_XAI_DAILY_TOKEN_LIMIT", 200_000)),
            daily_usd_limit=float(usd) if usd else None,
            max_output_tokens=max(16, _int("MOLIDO_XAI_MAX_OUTPUT_TOKENS", 600)),
            max_prompt_tokens=max(64, _int("MOLIDO_XAI_MAX_PROMPT_TOKENS", 6000)),
        )

    def public(self) -> dict[str, Any]:
        """Safe to show: no key, ever."""
        return {
            "base_url": self.base_url,
            "models": {k.value: v for k, v in self.models.items()},
            "priced_models": sorted(self.pricing),
            "max_concurrency": self.max_concurrency,
            "max_queue": self.max_queue,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "max_prompt_tokens": self.max_prompt_tokens,
            "max_output_tokens": self.max_output_tokens,
            "daily_token_limit": self.daily_token_limit,
            "daily_usd_limit": self.daily_usd_limit,
        }


def api_key() -> str:
    return os.environ.get(API_KEY_ENV, "").strip()


def enabled() -> bool:
    return bool(api_key())
