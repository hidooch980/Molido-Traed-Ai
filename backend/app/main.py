"""FastAPI application entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.guard import assert_execution_gate
from app.api.v1 import api_router
from app.api.v1.health import router as health_router
from app.core.config import get_settings
from app.core.errors import MolidoError
from app.core.logging import bind_trace, configure_logging, get_logger
from app.providers import registry

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
    """Attach a trace id to every request and echo it back to the client."""
    incoming = request.headers.get("x-trace-id")
    trace_id = bind_trace(incoming)
    response = await call_next(request)
    response.headers["x-trace-id"] = trace_id
    return response


@app.exception_handler(MolidoError)
async def domain_error_handler(_: Request, exc: MolidoError) -> JSONResponse:
    """Domain errors carry their own status and a machine-readable code.

    Notably `insufficient_data` surfaces as 409 rather than an empty 200, so a
    caller cannot mistake "we don't know" for "there is nothing".
    """
    return JSONResponse(status_code=exc.http_status, content=exc.to_payload())


app.include_router(health_router)
app.include_router(api_router)

# Checked at import, not at first request: a hole that only appears under load
# is a hole that ships. See app/api/guard.py for what this refuses to allow.
assert_execution_gate(app, require_auth=get_settings().require_auth)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"name": "MolidoTrade AI", "version": __version__, "docs": "/docs"}
