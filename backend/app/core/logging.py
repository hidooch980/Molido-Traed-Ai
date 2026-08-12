"""Structured logging with trace propagation.

Every log line carries `trace_id` (and `tenant_id` when a tenant context is
bound), per the spec's observability event model. Secrets are never logged;
values that look like credentials are scrubbed by `_scrub`.
"""

from __future__ import annotations

import logging
import sys
import uuid
from collections.abc import MutableMapping
from contextvars import ContextVar
from typing import Any

import structlog

_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)
_tenant_id: ContextVar[str | None] = ContextVar("tenant_id", default=None)

_SENSITIVE_KEYS = {
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "broker_password",
    "investor_password",
}


def new_trace_id() -> str:
    return uuid.uuid4().hex


def bind_trace(trace_id: str | None = None) -> str:
    tid = trace_id or new_trace_id()
    _trace_id.set(tid)
    return tid


def bind_tenant(tenant_id: str | None) -> None:
    _tenant_id.set(tenant_id)


def current_trace_id() -> str | None:
    return _trace_id.get()


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("***" if k.lower() in _SENSITIVE_KEYS else _scrub(v)) for k, v in value.items()
        }
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def _add_context(
    _logger: Any, _name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    trace = _trace_id.get()
    if trace:
        event_dict.setdefault("trace_id", trace)
    tenant = _tenant_id.get()
    if tenant:
        event_dict.setdefault("tenant_id", tenant)
    return _scrub(event_dict)


def configure_logging(level: str = "INFO", json_output: bool = False) -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )
    renderer: Any = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _add_context,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
