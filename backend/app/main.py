"""FastAPI application entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.deps import AuthenticationError, AuthorizationError
from app.api.guard import assert_execution_gate
from app.api.net import client_address, user_agent
from app.api.v1 import api_router
from app.api.v1.health import router as health_router
from app.core.config import get_settings
from app.core.enums import AuditEventType
from app.core.errors import MolidoError
from app.core.logging import bind_trace, configure_logging, get_logger
from app.providers import registry
from app.services import security_log

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    registry.install_defaults()
    log.info("app.startup", **settings.safe_summary())
    yield
    log.info("app.shutdown")


app = FastAPI(
    title="MolidoTrade AI",
    version=__version__,
    description=(
        "Trading intelligence, risk and execution platform. "
        "Historical reads are point-in-time enforced."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)


@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    """Attach a trace id to every request, echo it back, and note the request.

    The note is one service-level observation - latency and status - queued
    in memory and flushed to the database in batches (`app.ops.slo`). An
    objective measured against a list that empties on every deploy is not
    measured; the table is what makes `slo_window_populated` reachable.
    """
    import time as _time

    incoming = request.headers.get("x-trace-id")
    trace_id = bind_trace(incoming)
    started = _time.perf_counter()
    response = await call_next(request)
    response.headers["x-trace-id"] = trace_id
    try:
        from app.ops import slo as slo_module

        due = slo_module.observe_request(
            request.url.path, response.status_code, (_time.perf_counter() - started) * 1000.0
        )
        if due:
            from app.db.session import SessionLocal

            with SessionLocal() as db:
                slo_module.flush_requests(db)
    except Exception:  # noqa: BLE001 - an observation must never fail a request
        pass
    return response


@app.exception_handler(MolidoError)
async def domain_error_handler(request: Request, exc: MolidoError) -> JSONResponse:
    """Domain errors carry their own status and a machine-readable code.

    Notably `insufficient_data` surfaces as 409 rather than an empty 200, so a
    caller cannot mistake "we don't know" for "there is nothing".

    A refused permission is recorded on its way past. This is the only place it
    can be: `require()` refuses by raising, and the exception is what discards
    the request's transaction - so the record has to be written on a session of
    its own, after the rollback, or it is written and then destroyed by the
    thing it was written about. The sign-in limiter learned that the expensive
    way.

    Recording cannot fail the response. `record_isolated` swallows everything,
    including there being no database at all, because an exception handler that
    raises replaces a 403 the caller can act on with a 500 nobody can.
    """
    if isinstance(exc, AuthorizationError | AuthenticationError):
        security_log.record_isolated(
            AuditEventType.PERMISSION_DENIED,
            summary=f"{request.method} {request.url.path} refused: {exc.message}",
            address=client_address(request),
            user_agent=user_agent(request),
            detail={
                "path": request.url.path,
                "method": request.method,
                "code": exc.code,
                # `require()` puts the caller's role on the error. It is absent
                # for an unauthenticated caller, which is itself the answer.
                "role": exc.context.get("role"),
                "authenticated": exc.context.get("authenticated"),
            },
        )
    return JSONResponse(status_code=exc.http_status, content=exc.to_payload())


app.include_router(health_router)
app.include_router(api_router)

# Checked at import, not at first request: a hole that only appears under load
# is a hole that ships. See app/api/guard.py for what this refuses to allow.
assert_execution_gate(app, require_auth=get_settings().require_auth)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"name": "MolidoTrade AI", "version": __version__, "docs": "/docs"}
