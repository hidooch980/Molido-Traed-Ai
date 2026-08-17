"""Whoami and key management (spec 52).

There is deliberately no login-with-password endpoint yet. Sessions, cookies
and refresh tokens are a large surface, and nothing in this deployment needs
them: the dashboard renders server-side and the only non-browser callers are
machines, which are better served by keys. Adding that surface before it is
used would mean maintaining and securing code that protects nothing.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import Principal, require, resolve_principal
from app.core.config import get_settings
from app.core.enums import Permission

router = APIRouter(prefix="/auth", tags=["auth"])

READ = Depends(require(Permission.READ))


@router.get("/whoami")
def whoami(principal: Principal = Depends(resolve_principal)) -> dict:
    """What the caller is allowed to do, and whether auth is enforced at all.

    `auth_required` is reported so an operator can see, without reading the
    config, whether this deployment is currently open.
    """
    settings = get_settings()
    return {
        "authenticated": principal.authenticated,
        "auth_required": settings.require_auth,
        "tenant_id": str(principal.tenant_id) if principal.tenant_id else None,
        "user_id": str(principal.user_id) if principal.user_id else None,
        "role": principal.role.value,
        "permissions": sorted(p.value for p in principal.permissions),
    }
