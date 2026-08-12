"""Execution-gate tests (spec §52).

The gate is the reason the read-only deployment can stay public. These tests
are therefore about the ways someone could add a mutating endpoint without
noticing they had opened it, and they must all fail loudly.
"""

from __future__ import annotations

import pytest
from fastapi import APIRouter, Depends, FastAPI

from app.api import deps
from app.api.guard import (
    PERMISSION_ATTR,
    ExecutionGateError,
    assert_execution_gate,
    find_ungated_routes,
    iter_leaf_routes,
    mutating_routes,
)
from app.core.enums import Permission, UserRole

# Built once at module level: ruff's B008 rightly objects to calling a
# dependency factory inside a signature default, and the production routers
# follow the same shape.
READ_GATE = Depends(deps.require(Permission.READ))
EXECUTE_GATE = Depends(deps.require(Permission.EXECUTE))


def toy_app(router: APIRouter) -> FastAPI:
    application = FastAPI()
    application.include_router(router)
    return application


class TestTheRealApplication:
    def test_the_shipped_app_has_no_ungated_route(self):
        from app.main import app

        assert find_ungated_routes(app, require_auth=False) == []

    def test_every_route_is_still_read_only(self):
        """If this fails, phase 25 has begun and auth must be reconsidered."""
        from app.main import app

        assert mutating_routes(app) == []

    def test_the_walk_actually_reaches_the_included_routers(self):
        """Guards the guard: an empty result must mean safe, not blind."""
        from app.main import app

        paths = [path for path, _, _ in iter_leaf_routes(app)]

        assert "/api/v1/instruments" in paths
        assert len(paths) > 15


class TestForgottenPermissions:
    def test_a_mutating_route_without_a_permission_is_caught(self):
        router = APIRouter()

        @router.post("/orders")
        async def place_order() -> dict[str, str]:
            return {"status": "ok"}

        offenders = find_ungated_routes(toy_app(router), require_auth=True)

        assert len(offenders) == 1
        assert "declares no permission" in offenders[0].reason

    def test_read_permission_does_not_gate_a_mutation(self):
        """READ is what the anonymous principal already holds; it gates nothing."""
        router = APIRouter()

        @router.delete("/positions/{position_id}")
        async def close(
            position_id: str, _: deps.Principal = READ_GATE
        ) -> None:
            return None

        offenders = find_ungated_routes(toy_app(router), require_auth=True)

        assert len(offenders) == 1
        assert "only 'read'" in offenders[0].reason

    def test_execute_route_is_refused_while_auth_is_off(self):
        router = APIRouter()

        @router.post("/orders")
        async def place(
            _: deps.Principal = EXECUTE_GATE,
        ) -> None:
            return None

        offenders = find_ungated_routes(toy_app(router), require_auth=False)

        assert len(offenders) == 1
        assert "MOLIDO_REQUIRE_AUTH" in offenders[0].reason

    def test_the_same_route_passes_once_auth_is_on(self):
        router = APIRouter()

        @router.post("/orders")
        async def place(
            _: deps.Principal = EXECUTE_GATE,
        ) -> None:
            return None

        assert find_ungated_routes(toy_app(router), require_auth=True) == []

    def test_a_router_level_dependency_counts(self):
        """Otherwise the gate would force every route to repeat itself."""
        router = APIRouter(dependencies=[EXECUTE_GATE])

        @router.post("/orders")
        async def place() -> None:
            return None

        assert find_ungated_routes(toy_app(router), require_auth=True) == []

    def test_an_include_level_dependency_counts(self):
        router = APIRouter()

        @router.post("/orders")
        async def place() -> None:
            return None

        application = FastAPI()
        application.include_router(
            router, dependencies=[EXECUTE_GATE]
        )

        assert find_ungated_routes(application, require_auth=True) == []

    def test_get_routes_are_never_gated(self):
        router = APIRouter()

        @router.get("/bars")
        async def bars() -> list[str]:
            return []

        assert find_ungated_routes(toy_app(router), require_auth=True) == []

    def test_the_assertion_raises_and_names_the_route(self):
        router = APIRouter()

        @router.post("/orders")
        async def place() -> None:
            return None

        with pytest.raises(ExecutionGateError) as caught:
            assert_execution_gate(toy_app(router), require_auth=True)

        assert "/orders" in str(caught.value)

    def test_a_nested_include_is_still_found(self):
        """Depth is where a walk quietly stops looking."""
        inner = APIRouter()

        @inner.post("/orders")
        async def place() -> None:
            return None

        middle = APIRouter(prefix="/v1")
        middle.include_router(inner)

        application = FastAPI()
        application.include_router(middle, prefix="/api")

        offenders = find_ungated_routes(application, require_auth=True)

        assert [o.path for o in offenders] == ["/api/v1/orders"]


class TestPermissionMarker:
    def test_require_stamps_the_permission_it_enforces(self):
        dependency = deps.require(Permission.EXECUTE)

        assert getattr(dependency, PERMISSION_ATTR) is Permission.EXECUTE

    def test_anonymous_cannot_execute(self):
        assert deps.ANONYMOUS.can(Permission.READ) is True
        assert deps.ANONYMOUS.can(Permission.EXECUTE) is False
        assert deps.ANONYMOUS.can(Permission.SIMULATE) is False

    def test_unauthenticated_is_refused_even_holding_the_permission(self):
        """Belt and braces: a widened anonymous principal still cannot execute."""
        widened = deps.Principal(
            tenant_id=None,
            user_id=None,
            role=UserRole.TRADER,
            permissions=frozenset(
                {Permission.READ, Permission.SIMULATE, Permission.EXECUTE}
            ),
            authenticated=False,
        )

        with pytest.raises(deps.AuthenticationError):
            deps.require(Permission.EXECUTE)(principal=widened)

    def test_reading_stays_open_for_anonymous(self):
        assert deps.require(Permission.READ)(principal=deps.ANONYMOUS) is deps.ANONYMOUS
