"""Users, roles and service tiers over HTTP (spec §45, §68).

Everything here is a GET behind READ. Creating a user, changing a role or
moving a tenant between tiers are all state changes, and none of them exist
yet: the execution gate walks this router at import and refuses to start the
application if a mutating route appears without a permission dependency, so a
half-built admin panel cannot ship by accident.

What this publishes is the shape of the system - which roles exist, what each
one may do, which features each tier includes, and why. That is worth
publishing on its own. A permission model nobody can read is one nobody can
audit, and the first person to discover its edges should not be an attacker.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import ROLE_PERMISSIONS, Principal, require
from app.core.enums import Permission, UserRole
from app.core.plans import CATALOG, Condition, Feature, Plan, evaluate, features_for

router = APIRouter(prefix="/access", tags=["access"])

READ = Depends(require(Permission.READ))


@router.get("/roles")
def read_roles(_: Principal = READ) -> dict[str, Any]:
    """Every role and the permissions it carries.

    Read from the same table the dependency reads, not a copy. A published
    matrix that drifts from the enforced one is worse than no matrix: it tells
    an auditor the system does something it does not.
    """
    return {
        "roles": [
            {
                "role": role.value,
                "permissions": sorted(p.value for p in perms),
                "can_execute": Permission.EXECUTE in perms,
            }
            for role, perms in ROLE_PERMISSIONS.items()
        ],
        "permissions": [p.value for p in Permission],
        "anonymous_holds": ["read"],
        "note": (
            "a role grants authority to act. Whether the capability exists for "
            "this tenant at all is a separate question, answered by the plan"
        ),
    }


@router.get("/plans")
def read_plans(_: Principal = READ) -> dict[str, Any]:
    """The three tiers, every feature, and the reason each sits where it does."""
    return {
        "plans": [p.value for p in Plan],
        "conditions": [c.value for c in Condition],
        "features": [spec.as_dict() for spec in CATALOG],
        "by_plan": {
            plan.value: features_for(plan, satisfied=frozenset()) for plan in Plan
        },
        "billing": (
            "this deployment records which tier a tenant is on and refuses "
            "features outside it. There is no payment processor, no card "
            "handling and no invoice anywhere in this codebase"
        ),
        "note": (
            "measurement is free on purpose: the part of this system worth "
            "trusting is the part that says 'no proven edge', and behind a "
            "paywall that would be selling confidence rather than evidence"
        ),
    }


@router.get("/features")
def read_features(
    plan: Plan = Query(default=Plan.FREE),
    satisfied: str = Query(
        default="",
        description="Comma-separated conditions this tenant meets, e.g. calibrated",
    ),
    _: Principal = READ,
) -> dict[str, Any]:
    """What a tenant on this tier, meeting these conditions, can reach.

    The conditions are supplied rather than looked up, for the same reason the
    risk endpoints take an account state: there is no tenant behind this
    request. An endpoint that invented one would answer a different question in
    a convincing voice.
    """
    met = frozenset(
        Condition(value)
        for value in (v.strip() for v in satisfied.split(",") if v.strip())
        if value in {c.value for c in Condition}
    )
    split = features_for(plan, satisfied=met)
    return {
        "plan": plan.value,
        "conditions_met": sorted(c.value for c in met),
        **split,
        "verdicts": [
            evaluate(feature, plan, satisfied=met).as_dict() for feature in Feature
        ],
        "note": (
            "'awaiting a condition' and 'beyond this plan' are reported apart. "
            "Locked because you have not traded yet and locked because you have "
            "not paid are different sentences, and merging them makes the first "
            "look like the second"
        ),
    }


@router.get("/matrix")
def read_matrix(_: Principal = READ) -> dict[str, Any]:
    """Roles down, tiers across: what a given user on a given plan can do.

    Published as one table because the two axes get confused constantly. An
    admin on the free tier holds EXECUTE and cannot reach live execution; a
    viewer on the paid tier can open every page and cannot place an order.
    Neither is a bug, and both look like one until the axes are drawn.
    """
    rows = []
    for role, perms in ROLE_PERMISSIONS.items():
        for plan in Plan:
            live = evaluate(Feature.LIVE_EXECUTION, plan, satisfied=frozenset())
            rows.append(
                {
                    "role": role.value,
                    "plan": plan.value,
                    "holds_execute_permission": Permission.EXECUTE in perms,
                    "plan_includes_live_execution": live.allowed,
                    # Both have to be true. The gate is an AND and is written
                    # that way rather than derived, so a change to either side
                    # cannot quietly turn it into an OR.
                    "could_place_an_order": (Permission.EXECUTE in perms) and live.allowed,
                }
            )
    return {
        "matrix": rows,
        "roles": [r.value for r in UserRole],
        "plans": [p.value for p in Plan],
        "note": (
            "both axes must agree. A role grants authority, a plan grants "
            "access, and an order needs both - which is why neither check can "
            "be removed by improving the other"
        ),
        "still_refused_here": (
            "no route in this API places an order regardless of this table; "
            "execution is disabled and the kill switch defaults engaged"
        ),
    }
