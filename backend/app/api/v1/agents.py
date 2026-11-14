"""The agent registry, read-only (stage 1).

One GET. It describes the 51 roles and which existing code carries each; it
changes nothing and reaches nothing that trades.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.agents import registry
from app.api.deps import Principal, require
from app.core.enums import Permission

router = APIRouter(prefix="/agents", tags=["agents"])

READ = Depends(require(Permission.READ))


@router.get("/registry")
def read_registry(_: Principal = READ) -> dict[str, Any]:
    return registry.snapshot()
