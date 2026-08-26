"""Registering terminals, and seeing which of them are actually publishing.

Two questions on one screen, and they are different questions. "Which accounts
have I told the platform about" is configuration; "which of them sent anything
in the last minute" is operational, and a page that answered only the first
would list eleven healthy-looking rows for eleven terminals that were all
switched off.

So every row carries its bridge state beside it, read from the directory rather
than from the record. A registration is a claim; a heartbeat is evidence.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.core.enums import Permission
from app.db.session import get_db
from app.providers.metatrader import MetaTraderBridge
from app.services import terminals as service
from app.services.challenge_accounts import default_tenant

router = APIRouter(prefix="/terminals", tags=["terminals"])

READ = Depends(require(Permission.READ))
MANAGE = Depends(require(Permission.BROKER_MANAGE))


class TerminalPayload(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    label: str = Field(default="", max_length=120)
    broker: str = Field(default="", max_length=120)
    kind: str = Field(default="", max_length=32)


class ActivePayload(BaseModel):
    active: bool


def _row(terminal: Any, *, publishing: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(terminal.id),
        "key": terminal.key,
        "label": terminal.label,
        "broker": terminal.broker,
        "kind": terminal.kind,
        "is_active": terminal.is_active,
        "created_at": terminal.created_at.isoformat() if terminal.created_at else None,
        **publishing,
    }


def _publishing(key: str) -> dict[str, Any]:
    """What the directory says, as distinct from what the record claims."""
    try:
        state = MetaTraderBridge(directory=service.directory_for(key)).state()
    except Exception as problem:  # noqa: BLE001 - one bad row must not hide the rest
        return {
            "publishing": False,
            "login": 0,
            "reason": f"{type(problem).__name__}: {problem}",
        }
    return {
        "publishing": state.running,
        "usable": state.usable,
        "login": state.login,
        "age_seconds": state.age_seconds,
        "reason": state.reason,
    }


@router.get("")
def list_terminals(
    _: Principal = READ,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Every registered terminal, with whether it is publishing."""
    tenant_id = default_tenant(session)
    rows = service.listing(session, tenant_id=tenant_id)
    return {
        "terminals": [_row(t, publishing=_publishing(t.key)) for t in rows],
        "total": len(rows),
        # The two figures a page needs to say something honest at a glance:
        # how many were set up, and how many are actually alive.
        "publishing": sum(1 for t in rows if _publishing(t.key)["publishing"]),
        "note": (
            "a registration is a claim; the heartbeat beside it is evidence. "
            "A terminal with no heartbeat is set up and switched off, which is "
            "a different problem from one that was never set up"
        ),
    }


@router.post("", status_code=201)
def create_terminal(
    body: TerminalPayload,
    _: Principal = MANAGE,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Register a terminal and create the directory it will publish into."""
    tenant_id = default_tenant(session)
    terminal = service.register(
        session,
        tenant_id=tenant_id,
        key=body.key,
        label=body.label,
        broker=body.broker,
        kind=body.kind,
    )
    session.commit()
    return {
        "created": True,
        "terminal": _row(terminal, publishing=_publishing(terminal.key)),
        # Handed back rather than left to be looked up. This is the moment
        # somebody is about to type these into an expert, and the account key
        # in particular has to match exactly - the backend refuses an unknown
        # one rather than filing it somewhere plausible.
        "expert_settings": {
            "PublishAccountKey": terminal.key,
            "PublishUrl": "/api/v1/bridge/publish",
            "note": (
                "put the full https URL of this deployment in front of that "
                "path, and add the same URL under Tools > Options > Expert "
                "Advisors > Allow WebRequest for listed URL, then restart the "
                "terminal"
            ),
        },
    }


@router.post("/{terminal_id}/active")
def set_active(
    terminal_id: uuid.UUID,
    body: ActivePayload,
    _: Principal = MANAGE,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Switch a terminal off, or back on.

    Off rather than deleted: the bridge directory keeps whatever it last
    published, and a decision recorded against a terminal that no longer
    resolves is a decision about nobody.
    """
    tenant_id = default_tenant(session)
    terminal = service.set_active(
        session, tenant_id=tenant_id, terminal_id=terminal_id, active=body.active
    )
    session.commit()
    return {"terminal": _row(terminal, publishing=_publishing(terminal.key))}
