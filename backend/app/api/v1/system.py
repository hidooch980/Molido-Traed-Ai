"""Deployment settings, read-only and redacted (spec §68).

Two rules, and the second is the one that earns the module:

**Reporting is not configuring.** There is no route that changes a setting.
Configuration lives in the environment on the server, changed by a person with
shell access, and a settings endpoint that accepted writes would be a mutating
route the execution gate refuses to boot with anyway. The page this feeds says
what the deployment *is*, not what somebody could make it.

**Redaction happens at the source, not at the edge.** The payload is built from
`safe_summary()` and fields chosen one by one — never by serialising the whole
settings object and deleting the dangerous keys. A blocklist of dangerous keys
has to anticipate every secret somebody adds later; building the payload
field-by-field means a new secret is absent by default rather than leaked by
default. There is a test that greps the response for the database password's
shape rather than trusting this paragraph.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import Principal, require
from app.core.config import get_settings
from app.core.enums import Permission
from app.services import retention

router = APIRouter(prefix="/system", tags=["system"])

READ = Depends(require(Permission.READ))


@router.get("/settings")
def read_settings(_: Principal = READ) -> dict[str, Any]:
    """What this deployment is configured to do, with secrets absent by design."""
    settings = get_settings()

    watchlist = [
        entry.strip() for entry in settings.watchlist.split(",") if entry.strip()
    ]
    return {
        "app": settings.safe_summary(),
        "collector": {
            "provider": settings.collector_provider,
            "interval_seconds": settings.collector_interval_seconds,
            "watchlist_size": len(watchlist),
            # Symbols only; the provider-specific mapping stays out of the
            # payload because it is an implementation detail of ingestion, not
            # a fact about what is being watched.
            "symbols": sorted({w.split(":")[0] for w in watchlist}),
        },
        "ingestion": {
            "max_retries": settings.ingest_max_retries,
            "backoff_base_seconds": settings.ingest_backoff_base_seconds,
            "chunk_days": settings.ingest_chunk_days,
            "min_quality_score": settings.min_quality_score,
        },
        "execution": {
            "enabled": settings.enable_execution,
            "dry_run": settings.execution_dry_run,
            "require_auth": settings.require_auth,
            "max_risk_r_per_order": settings.max_risk_r_per_order,
        },
        "retention": [p.as_dict() for p in retention.POLICIES],
        "read_only": True,
        "note": (
            "configuration is changed in the environment on the server, by a "
            "person; this endpoint reports it and offers no way to write it"
        ),
    }
