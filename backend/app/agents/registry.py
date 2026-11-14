"""Lookups over the 51 roles. Pure data; no I/O, no trading imports."""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.agents.model import (
    COMMON_RESTRICTIONS,
    HUMAN_ONLY_L5,
    AgentGroup,
    AgentRole,
    ImplementationStatus,
)
from app.agents.roles import ROLES

REGISTRY_VERSION = 1

#: The IDs the brief names, in order. The registry must match this exactly.
EXPECTED_IDS: tuple[str, ...] = (
    tuple(f"SC{i:02d}" for i in range(1, 11))
    + tuple(f"SM{i:02d}" for i in range(1, 11))
    + tuple(f"TA{i:02d}" for i in range(1, 7))
    + tuple(f"AI{i:02d}" for i in range(1, 5))
    + tuple(f"RK{i:02d}" for i in range(1, 6))
    + tuple(f"EX{i:02d}" for i in range(1, 6))
    + ("BRAIN-01",)
    + tuple(f"RT{i:02d}" for i in range(1, 11))
)

_BY_ID: dict[str, AgentRole] = {role.id: role for role in ROLES}


def all_roles() -> tuple[AgentRole, ...]:
    return ROLES


def get(agent_id: str) -> AgentRole | None:
    return _BY_ID.get(agent_id)


def ids() -> tuple[str, ...]:
    return tuple(role.id for role in ROLES)


def by_group(group: AgentGroup) -> tuple[AgentRole, ...]:
    return tuple(role for role in ROLES if role.group is group)


def status_counts() -> dict[str, int]:
    counts = Counter(role.status.value for role in ROLES)
    return {status.value: counts.get(status.value, 0) for status in ImplementationStatus}


def snapshot() -> dict[str, Any]:
    """The whole registry as JSON-ready data, for the read-only endpoint."""
    return {
        "version": REGISTRY_VERSION,
        "stage": 1,
        "mode": "paper_only",
        "total": len(ROLES),
        "status_counts": status_counts(),
        "groups": {
            group.value: [role.id for role in by_group(group)] for group in AgentGroup
        },
        "human_only_l5": list(HUMAN_ONLY_L5),
        "common_restrictions": list(COMMON_RESTRICTIONS),
        "note": (
            "Stage 1 describes roles and maps them to existing code. No role runs as "
            "a separate process, none calls a language model, and none can place, "
            "size or authorise an order."
        ),
        "agents": [role.as_dict() for role in ROLES],
    }
