"""Audit event recording (spec §66)."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.enums import AuditEventType, Severity
from app.core.logging import current_trace_id, get_logger
from app.models.audit import AuditEvent

log = get_logger(__name__)


def record(
    session: Session,
    event_type: AuditEventType | str,
    *,
    summary: str | None = None,
    severity: Severity = Severity.INFO,
    tenant_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    account_id: uuid.UUID | None = None,
    service: str = "backend",
    payload: dict | None = None,
    model_version: str | None = None,
) -> AuditEvent:
    """Append one audit event and mirror it to the structured log.

    Payloads carry metadata only. Callers must not pass credentials, tokens or
    raw provider responses.
    """
    event = AuditEvent(
        trace_id=current_trace_id(),
        tenant_id=tenant_id,
        user_id=user_id,
        account_id=account_id,
        service=service,
        event_type=str(event_type),
        severity=severity,
        summary=summary,
        payload=payload or {},
        model_version=model_version,
    )
    session.add(event)
    log.info(str(event_type), summary=summary, severity=severity.value, **(payload or {}))
    return event
