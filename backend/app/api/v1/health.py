"""Liveness and readiness (spec §35).

Liveness answers "is this process alive". Readiness answers "should traffic be
sent here", which requires the dependencies to actually be reachable — so
readiness touches the database and Redis rather than returning a constant.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Response
from sqlalchemy import text

from app import __version__
from app.core.config import get_settings
from app.core.safe_mode import SafeMode
from app.db.session import get_engine
from app.schemas.market import DependencyHealth, HealthResponse

router = APIRouter(tags=["health"])


def _check_database() -> DependencyHealth:
    started = time.perf_counter()
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return DependencyHealth(
            name="database",
            healthy=True,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )
    except Exception as exc:  # noqa: BLE001 - health must never raise
        return DependencyHealth(name="database", healthy=False, detail=type(exc).__name__)


def _check_redis() -> DependencyHealth:
    started = time.perf_counter()
    try:
        import redis  # noqa: PLC0415

        client = redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=2)
        client.ping()
        return DependencyHealth(
            name="redis",
            healthy=True,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )
    except Exception as exc:  # noqa: BLE001
        return DependencyHealth(name="redis", healthy=False, detail=type(exc).__name__)


@router.get("/health/live", response_model=HealthResponse)
def live() -> HealthResponse:
    settings = get_settings()
    state = SafeMode.state()
    return HealthResponse(
        status="ok",
        version=__version__,
        environment=settings.env,
        safe_mode=state.active,
        safe_mode_reasons=sorted(r.value for r in state.reasons),
    )


@router.get("/health/ready", response_model=HealthResponse)
def ready(response: Response) -> HealthResponse:
    settings = get_settings()
    state = SafeMode.state()
    dependencies = [_check_database(), _check_redis()]
    all_healthy = all(dep.healthy for dep in dependencies)

    if not all_healthy:
        status = "degraded"
        response.status_code = 503
    elif state.active:
        status = "safe_mode"
    else:
        status = "ok"

    return HealthResponse(
        status=status,
        version=__version__,
        environment=settings.env,
        safe_mode=state.active,
        safe_mode_reasons=sorted(r.value for r in state.reasons),
        dependencies=dependencies,
    )
