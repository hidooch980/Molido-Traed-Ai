"""The execution gate (spec §52, §21).

The spec's chain is *AI proposes, risk authorises, execution executes* — and it
only holds if execution is unreachable by an unnamed caller. Two ways that
breaks in practice, neither of which a code review reliably catches:

1. Someone adds the first `POST /orders` and forgets the permission dependency.
   The route works, so nothing looks wrong.
2. Someone adds it *with* the dependency, but `MOLIDO_REQUIRE_AUTH` is still
   false from the read-only era, so there is no authenticated identity behind
   the audit trail the spec requires.

Both are caught here, at import time, by walking the router table rather than
by trusting anyone to remember. The application refuses to start rather than
start with a hole — a boot failure is loud and reversible; a silent one is
neither.

This is why the read-only deployment can stay public: the openness is bounded
by a check, not by the current absence of mutating routes.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from app.core.enums import Permission

# Attribute stamped on the dependency returned by `deps.require()`. A bare
# closure is indistinguishable from any other dependency once FastAPI has it,
# so the marker is what makes the permission visible to this walk.
PERMISSION_ATTR = "__molido_permission__"

#: Set by `public_mutation` on the handful of routes that must change state
#: before anybody can authenticate. Never inferred, never defaulted: a route
#: without it that mutates on READ alone still refuses to start the app.
PUBLIC_MUTATION_ATTR = "__molido_public_mutation__"

# HTTP methods that cannot change state. Everything else is a mutation and
# must be gated, whatever the handler happens to do today.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


class ExecutionGateError(RuntimeError):
    """Raised at startup when a mutating route is not properly gated."""


@dataclass(frozen=True)
class UngatedRoute:
    path: str
    methods: tuple[str, ...]
    reason: str

    def __str__(self) -> str:
        joined = "/".join(self.methods)
        return f"{joined} {self.path}: {self.reason}"


def _marked_permissions(depends_list: Any) -> set[Permission]:
    """Permissions stamped on a list of `Depends(...)` markers."""
    found: set[Permission] = set()
    for item in depends_list or []:
        permission = getattr(getattr(item, "dependency", None), PERMISSION_ATTR, None)
        if isinstance(permission, Permission):
            found.add(permission)
    return found


def iter_leaf_routes(app: Any) -> Iterator[tuple[str, Any, frozenset[Permission]]]:
    """Every endpoint in the application, with its full path and inherited gates.

    `app.routes` is not flat: since FastAPI 0.141 an included router stays a
    single wrapper object holding the sub-router and the prefix it was mounted
    under. An earlier version of this walk iterated the top level only, found
    no mutating routes anywhere, and passed — which is precisely the silent
    success this module exists to prevent, so the recursion is the gate.
    """

    def walk(
        routes: Any, prefix: str, inherited: frozenset[Permission]
    ) -> Iterator[tuple[str, Any, frozenset[Permission]]]:
        for route in routes:
            original = getattr(route, "original_router", None)
            if original is not None:
                context = getattr(route, "include_context", None)
                gained = _marked_permissions(getattr(context, "dependencies", None))
                yield from walk(
                    original.routes,
                    prefix + (getattr(context, "prefix", "") or ""),
                    inherited | gained,
                )
                continue

            nested = getattr(route, "routes", None)
            if nested is not None and getattr(route, "dependant", None) is None:
                yield from walk(
                    nested, prefix + (getattr(route, "prefix", "") or ""), inherited
                )
                continue

            yield prefix + (getattr(route, "path", "") or ""), route, inherited

    yield from walk(app.routes, "", frozenset())


def _declared_permissions(dependant: Any) -> set[Permission]:
    """Every permission required anywhere in a route's dependency tree.

    The walk is recursive because a router-level or nested dependency is just
    as binding as one declared on the handler, and refusing to see it would
    push authors toward repeating themselves on every route.
    """
    found: set[Permission] = set()
    stack = [dependant]
    while stack:
        current = stack.pop()
        permission = getattr(getattr(current, "call", None), PERMISSION_ATTR, None)
        if isinstance(permission, Permission):
            found.add(permission)
        stack.extend(getattr(current, "dependencies", []))
    return found


def mutating_routes(app: Any) -> list[tuple[str, tuple[str, ...]]]:
    """Paths and methods of everything that can change state."""
    out: list[tuple[str, tuple[str, ...]]] = []
    for path, route, _ in iter_leaf_routes(app):
        methods = getattr(route, "methods", None)
        if not methods or getattr(route, "dependant", None) is None:
            continue
        mutating = tuple(sorted(set(methods) - SAFE_METHODS))
        if mutating:
            out.append((path, mutating))
    return out



def public_mutation(reason: str):
    """Mark a mutating route as reachable without authentication.

    For sign-in and nothing that is not sign-in shaped: a route that has to
    change state before a caller can possibly hold a credential. The reason is
    required and is published in the security posture, because an exemption
    nobody can see is an exemption nobody will re-examine.

        @router.post("/sign-in")
        @public_mutation("creates a session; unreachable if it needed one")
        def sign_in(...): ...
    """
    if not reason or len(reason) < 20:
        raise ValueError(
            "a public mutation needs a written reason - it is the only thing "
            "standing between this exemption and a habit"
        )

    def decorate(function):
        setattr(function, PUBLIC_MUTATION_ATTR, reason)
        return function

    return decorate


def public_mutations(app: Any) -> list[tuple[str, str]]:
    """Every route claiming the exemption, with its stated reason."""
    found: list[tuple[str, str]] = []
    for path, route, _permissions in iter_leaf_routes(app):
        endpoint = getattr(route, "endpoint", None)
        reason = getattr(endpoint, PUBLIC_MUTATION_ATTR, None)
        if reason:
            found.append((path, reason))
    return sorted(found)


def find_ungated_routes(app: Any, *, require_auth: bool) -> list[UngatedRoute]:
    """Mutating routes that are not safely reachable. Empty means the gate holds."""
    offenders: list[UngatedRoute] = []

    for path, route, inherited in iter_leaf_routes(app):
        methods = getattr(route, "methods", None)
        dependant = getattr(route, "dependant", None)
        if not methods or dependant is None:
            continue

        mutating = tuple(sorted(set(methods) - SAFE_METHODS))
        if not mutating:
            continue

        permissions = _declared_permissions(dependant) | set(inherited)

        if not permissions:
            offenders.append(
                UngatedRoute(path, mutating, "mutates state but declares no permission")
            )
            continue

        if permissions == {Permission.READ}:
            # The one exemption, and it has to be claimed by name. Sign-in
            # changes state and cannot require more than READ, because a door
            # that needs a key to reach the key is not a door. Anything that
            # has not written down why it deserves this still refuses to start.
            exempt = getattr(getattr(route, "endpoint", None), PUBLIC_MUTATION_ATTR, None)
            if exempt:
                continue
            offenders.append(
                UngatedRoute(
                    path,
                    mutating,
                    "mutates state but requires only 'read', which the anonymous "
                    "principal already holds",
                )
            )
            continue

        # An execute route without authentication would act on an account with
        # no record of who asked. Reducing risk is not enough here; the spec
        # requires the actor to be identifiable.
        if Permission.EXECUTE in permissions and not require_auth:
            offenders.append(
                UngatedRoute(
                    path,
                    mutating,
                    "requires 'execute' while MOLIDO_REQUIRE_AUTH is false — set "
                    "it to true before deploying any execution endpoint",
                )
            )

    return offenders


def assert_execution_gate(app: Any, *, require_auth: bool) -> None:
    """Refuse to start if any mutating route is ungated."""
    offenders = find_ungated_routes(app, require_auth=require_auth)
    if not offenders:
        return

    detail = "\n  ".join(str(o) for o in offenders)
    raise ExecutionGateError(
        "Refusing to start: mutating routes are not gated.\n  " + detail
    )
