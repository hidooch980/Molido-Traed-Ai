"""Audit event recording (spec §66), chained so an edit is provable.

Every event written here carries the hash of the one before it. Changing any
stored event changes its hash, and every later event then names a hash that
no longer exists, so `verify` can point at the first place the record was
touched. Chaining does not make the table immutable - nothing in a process
can - it makes tampering *detectable*, which is what an audit trail is for.

Rows from before the chain existed have no hash and are counted as
`pre_chain`. They are not verified and they are not rewritten: giving them
hashes now would be manufacturing continuity, exactly the thing the chain is
meant to catch.

Appends are serialised through the single row of `audit_chain_head`, locked
`FOR UPDATE` inside the caller's transaction. Three processes write audit
events; without the lock two of them read the same tail and the chain forks.
On a database without row locks (the sqlite test session) the lock clause is
a no-op and the tests run single-threaded, which is the same guarantee.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.enums import AuditEventType, Severity
from app.core.logging import current_trace_id, get_logger
from app.models.audit import AuditChainHead, AuditEvent

log = get_logger(__name__)

GENESIS_HASH = "0" * 64


def _material(
    *,
    sequence: int,
    occurred_at: datetime,
    service: str,
    event_type: str,
    severity: str,
    summary: str | None,
    payload: dict[str, Any],
    previous_hash: str,
) -> str:
    return json.dumps(
        {
            "sequence": sequence,
            "occurred_at": occurred_at.isoformat(),
            "service": service,
            "event_type": event_type,
            "severity": severity,
            "summary": summary,
            "payload": payload,
            "previous": previous_hash,
        },
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )


def entry_hash(event: AuditEvent, *, previous_hash: str) -> str:
    """The hash an event should carry, recomputed from its stored fields."""
    severity = event.severity.value if hasattr(event.severity, "value") else str(event.severity)
    return hashlib.sha256(
        _material(
            sequence=int(event.sequence or 0),
            occurred_at=event.occurred_at,
            service=event.service,
            event_type=event.event_type,
            severity=severity,
            summary=event.summary,
            payload=event.payload or {},
            previous_hash=previous_hash,
        ).encode()
    ).hexdigest()


def _head(session: Session) -> AuditChainHead:
    """The chain tail, locked for the rest of this transaction.

    Created at genesis when absent. Migration 0021 inserts it in production;
    a database built from metadata (the test session) has the table and no
    row, and a chain that cannot start is a chain that never verifies.
    """
    statement = select(AuditChainHead).where(AuditChainHead.id == 1)
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        statement = statement.with_for_update()
    head = session.execute(statement).scalar_one_or_none()
    if head is None:
        head = AuditChainHead(id=1, sequence=-1, entry_hash=GENESIS_HASH)
        session.add(head)
        session.flush()
    return head


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
    """Append one audit event, chained to the last, and mirror it to the log.

    Payloads carry metadata only. Callers must not pass credentials, tokens or
    raw provider responses.

    Requires migration 0021 (the chain columns and the head row); on a
    database built from metadata the head is created at genesis on first use.
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
    head = _head(session)
    if event.occurred_at is None:
        from app.db.base import utcnow

        event.occurred_at = utcnow()
    event.sequence = int(head.sequence) + 1
    event.previous_hash = head.entry_hash
    event.entry_hash = entry_hash(event, previous_hash=head.entry_hash)
    head.sequence = event.sequence
    head.entry_hash = event.entry_hash
    session.add(event)
    log.info(str(event_type), summary=summary, severity=severity.value, **(payload or {}))
    return event


@dataclass
class ChainVerification:
    """What walking the chain found."""

    intact: bool
    chained: int
    pre_chain: int
    head_sequence: int | None
    first_broken_sequence: int | None = None
    problems: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "intact": self.intact,
            "chained": self.chained,
            "pre_chain": self.pre_chain,
            "head_sequence": self.head_sequence,
            "first_broken_sequence": self.first_broken_sequence,
            "problems": self.problems,
            "note": (
                "pre-chain rows predate the chain and are counted, not verified; "
                "they are never rewritten. A tail verification proves the last "
                "N events link to each other and to the head, not the rows before"
            ),
        }


def verify(session: Session, *, tail: int | None = None) -> ChainVerification:
    """Walk the chained events in sequence and recompute each hash.

    Checks, in order: no gaps in the sequence, each `previous_hash` names the
    hash before it, each `entry_hash` matches its own fields, timestamps do
    not run backwards, and the head row agrees with the last event. `intact`
    is True only with at least one chained event: an empty chain has not
    been verified, it has been found empty.

    `tail` walks only the last N events, anchored on the first one's stored
    `previous_hash`. That proves the tail is internally linked and agrees
    with the head; it does not prove the rows before it. The per-cycle check
    uses it because a full walk of a year's events on every cycle is a cost
    paid for nothing new; the full walk is for the nightly job and the CLI.
    """
    pre_chain = int(
        session.execute(
            text("SELECT count(*) FROM audit_events WHERE sequence IS NULL")
        ).scalar_one()
    )
    head = session.execute(select(AuditChainHead).where(AuditChainHead.id == 1)).scalar_one_or_none()
    statement = (
        select(AuditEvent)
        .where(AuditEvent.sequence.is_not(None))
        .order_by(AuditEvent.sequence.asc())
    )
    if tail and head is not None:
        statement = statement.where(AuditEvent.sequence > int(head.sequence) - int(tail))
    events = session.execute(statement).scalars().all()

    problems: list[str] = []
    previous = GENESIS_HASH
    expected_sequence = 0
    if tail and events:
        # Anchor on what the first event of the tail says came before it.
        # The rows before are not checked here, and the note says so.
        previous = str(events[0].previous_hash or "")
        expected_sequence = int(events[0].sequence)
    last_at: datetime | None = None
    broken_at: int | None = None
    for event in events:
        sequence = int(event.sequence)
        if sequence != expected_sequence:
            problems.append(f"gap: expected sequence {expected_sequence}, found {sequence}")
            broken_at = broken_at if broken_at is not None else sequence
            break
        if event.previous_hash != previous:
            problems.append(f"sequence {sequence} names a previous hash that is not the one before it")
            broken_at = broken_at if broken_at is not None else sequence
            break
        if event.entry_hash != entry_hash(event, previous_hash=previous):
            problems.append(f"sequence {sequence} does not hash to its own fields")
            broken_at = broken_at if broken_at is not None else sequence
            break
        if last_at is not None and event.occurred_at < last_at:
            problems.append(f"sequence {sequence} occurred before sequence {sequence - 1}")
            broken_at = broken_at if broken_at is not None else sequence
            break
        previous = event.entry_hash
        last_at = event.occurred_at
        expected_sequence += 1

    if not problems and events and head is not None:
        if int(head.sequence) != int(events[-1].sequence) or head.entry_hash != events[-1].entry_hash:
            problems.append("the chain head does not agree with the last chained event")
            broken_at = int(events[-1].sequence)

    return ChainVerification(
        intact=bool(events) and not problems,
        chained=len(events),
        pre_chain=pre_chain,
        head_sequence=int(head.sequence) if head is not None else None,
        first_broken_sequence=broken_at,
        problems=problems,
    )


__all__ = ["ChainVerification", "GENESIS_HASH", "entry_hash", "record", "verify"]
