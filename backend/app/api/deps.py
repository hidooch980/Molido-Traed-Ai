"""Authentication and authorization dependencies (spec §52).

The model is deliberately small: an API key identifies a tenant and a user, a
role grants a permission tier, and every protected route declares the tier it
needs. That is enough to satisfy the spec's requirement that Telegram, n8n and
the dashboard all pass through the same gate, without inventing a session
system nothing uses yet.

**Read stays open while nothing mutates.** `MOLIDO_REQUIRE_AUTH` defaults to
false, so the current read-only public deployment keeps working. The moment a
route mutates state — the first order endpoint, the first broker credential —
that flag must be on and the route must require EXECUTE. That is not left to
memory: `app.api.guard` walks the router table at import and refuses to start
the application if any mutating route is reachable without a permission, so
the openness above is bounded by a check rather than by good intentions.

**Tenant isolation is carried, not assumed.** The resolved principal carries
its tenant id, and any route touching tenant-scoped data must filter on it
rather than trusting a query parameter.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Cookie, Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.guard import PERMISSION_ATTR
from app.core.config import get_settings
from app.core.enums import Permission, UserRole
from app.core.errors import MolidoError
from app.core.logging import bind_tenant
from app.core.security import api_key_matches
from app.db.session import get_db
from app.models.tenancy import ApiKey, User


class AuthenticationError(MolidoError):
    code = "unauthenticated"
    http_status = 401


class AuthorizationError(MolidoError):
    code = "forbidden"
    http_status = 403


# Which permissions each role holds. A trader may execute; an analyst may
# simulate but never execute; a viewer may only read.
ROLE_PERMISSIONS: dict[UserRole, set[Permission]] = {
    UserRole.OWNER: {Permission.READ, Permission.SIMULATE, Permission.EXECUTE},
    UserRole.ADMIN: {Permission.READ, Permission.SIMULATE, Permission.EXECUTE},
    UserRole.TRADER: {Permission.READ, Permission.SIMULATE, Permission.EXECUTE},
    UserRole.ANALYST: {Permission.READ, Permission.SIMULATE},
    UserRole.VIEWER: {Permission.READ},
}


@dataclass(frozen=True)
class Principal:
    """Who is making this request, and what they are allowed to do."""

    tenant_id: uuid.UUID | None
    user_id: uuid.UUID | None
    role: UserRole
    permissions: frozenset[Permission]
    authenticated: bool

    def can(self, permission: Permission) -> bool:
        return permission in self.permissions


# The principal used when authentication is switched off. It holds READ only —
# so if a mutating route is ever added while auth is disabled, the route is
# refused rather than silently executed by an anonymous caller.
ANONYMOUS = Principal(
    tenant_id=None,
    user_id=None,
    role=UserRole.VIEWER,
    permissions=frozenset({Permission.READ}),
    authenticated=False,
)


def _principal_for(session: Session, key: ApiKey) -> Principal:
    """One `Principal` from one stored credential, whichever kind it is.

    A browser session and an API key are stored the same way on purpose, so
    everything above this line is spared knowing which arrived. A permission
    check that had to ask would eventually be written twice and drift.
    """
    role = UserRole.VIEWER
    if key.user_id:
        user = session.get(User, key.user_id)
        if user is not None:
            if not user.is_active:
                raise AuthenticationError("This user account is disabled.")
            role = UserRole(user.role)

    bind_tenant(str(key.tenant_id))
    return Principal(
        tenant_id=key.tenant_id,
        user_id=key.user_id,
        role=role,
        permissions=frozenset(ROLE_PERMISSIONS.get(role, {Permission.READ})),
        authenticated=True,
    )


def resolve_principal(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    molido_session: str | None = Cookie(default=None, alias="molido_session"),
    session: Session = Depends(get_db),
) -> Principal:
    """Identify the caller from a session cookie or an API key.

    The cookie is tried first because it is the ordinary case: somebody signed
    in on the site. The key remains for scripts and for anything that cannot
    hold a cookie, and both resolve to the same principal with the same
    permissions - a session grants nothing a key would not.
    """
    settings = get_settings()

    if molido_session:
        from app.services import sessions_auth

        row = sessions_auth.resolve(session, molido_session)
        if row is not None:
            return _principal_for(session, row)
        # A stale cookie falls through to the key rather than failing. The
        # ordinary end of a session is not an error, and refusing here would
        # lock somebody out of the public pages for holding an old cookie.

    if not x_api_key:
        if settings.require_auth:
            raise AuthenticationError("An API key is required for this deployment.")
        return ANONYMOUS

    prefix = x_api_key[:12]
    now = datetime.now(UTC)

    # Narrow by the non-secret prefix, then compare the hash in constant time.
    # Matching on the prefix alone would be an authentication bypass; matching
    # without it would mean scanning every key on every request.
    candidates = session.scalars(select(ApiKey).where(ApiKey.key_prefix == prefix))

    for key in candidates:
        if not api_key_matches(x_api_key, key.key_hash):
            continue
        if key.revoked_at is not None:
            raise AuthenticationError("This API key has been revoked.")
        if key.expires_at is not None and key.expires_at <= now:
            raise AuthenticationError("This API key has expired.")

        key.last_used_at = now
        return _principal_for(session, key)

    # Deliberately identical to the revoked/expired message shape: a caller
    # must not be able to tell a wrong key from a disabled one.
    raise AuthenticationError("Invalid API key.")


def require(permission: Permission):
    """Dependency factory: `Depends(require(Permission.EXECUTE))`.

    Attaching the check to the dependency rather than to route code means a new
    protected endpoint cannot forget it — the permission is part of the
    signature. `app.api.guard` then reads the stamped marker to prove, at
    startup, that no mutating route was declared without one.
    """

    def dependency(principal: Principal = Depends(resolve_principal)) -> Principal:
        # Anything beyond reading must be attributable to someone. ANONYMOUS
        # holds READ alone, so today this branch is unreachable — it exists so
        # that widening the anonymous principal later cannot quietly open an
        # unauthenticated path to simulation or execution.
        if permission is not Permission.READ and not principal.authenticated:
            raise AuthenticationError(
                f"The {permission.value} permission requires an authenticated API key."
            )
        if not principal.can(permission):
            raise AuthorizationError(
                f"This action requires the {permission.value} permission.",
                role=principal.role.value,
                authenticated=principal.authenticated,
            )
        return principal

    setattr(dependency, PERMISSION_ATTR, permission)
    return dependency
