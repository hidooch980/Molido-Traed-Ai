"""Who did what, from where, and whether it worked (spec §52, §66).

The question this exists to answer is the one asked after a scare, at speed,
by somebody frightened: *did anybody get in, and what did they touch?*
Answering it needs three things that were each present and never joined -
`login_attempts` knows about passwords and nothing else, `audit_events` knows
about ingestion runs and has no idea who called, and the permission layer
refused things without leaving any record at all.

Four decisions carry this module.

**It writes into `audit_events`, not a table of its own.** One timeline is the
whole point. "The collector failed, then somebody signed in from an address
nobody has used before, then the kill switch was released" is a sentence you
can only read if all three are in one place, in order. A separate security
table would have to be read side by side with this one and mentally
interleaved, which is a thing nobody does correctly at 3am.

**Failures are their own event types.** `SIGN_IN_FAILED` rather than
`SIGN_IN` with an outcome field, so "show me every failed sign-in" is an
indexed lookup instead of a scan that opens every payload. The index on
`(event_type, occurred_at)` already exists.

**Recording never breaks the thing it records.** Every entry point swallows
its own exceptions. A log that can fail a sign-in is a log that takes the
deployment down the first time the disk fills, and the failure it causes is
never the one it was written to catch.

**Nothing secret is written, ever.** Not passwords, not session tokens, not
API keys, not the proof-of-work solution. What goes in is the address that was
tried - which is not a secret to whoever typed it - the caller's address, the
user agent, and what the system decided. If a field might be a credential, it
does not belong in this file.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import AuditEventType, Severity
from app.core.logging import get_logger
from app.models.audit import AuditEvent
from app.services import audit

log = get_logger(__name__)

#: The event types this module owns. Written out rather than derived from a
#: string prefix: a family added later should have to be added here on purpose,
#: because appearing in the security log is a decision about who may read it.
SECURITY_EVENTS: tuple[AuditEventType, ...] = (
    AuditEventType.SIGN_IN_SUCCEEDED,
    AuditEventType.SIGN_IN_FAILED,
    AuditEventType.SIGN_IN_THROTTLED,
    AuditEventType.HUMAN_CHECK_FAILED,
    AuditEventType.SIGN_OUT,
    AuditEventType.PERMISSION_DENIED,
    AuditEventType.USER_CREATED,
    AuditEventType.USER_REGISTERED,
    AuditEventType.USER_ROLE_CHANGED,
    AuditEventType.USER_ACTIVE_CHANGED,
    AuditEventType.PASSWORD_CHANGED,
    AuditEventType.DEPLOYMENT_CLAIMED,
    AuditEventType.KEY_ISSUED,
    AuditEventType.KEY_REVOKED,
    AuditEventType.BROKER_LINKED,
    AuditEventType.ANALYST_SPOKE,
    AuditEventType.KILL_SWITCH_ENGAGED,
    AuditEventType.KILL_SWITCH_RELEASED,
)

#: Which of them are worth waking up for. Severity is stored on the row, so a
#: reader can ask for "just the alarming ones" without knowing this list.
ALARMING: frozenset[AuditEventType] = frozenset(
    {
        AuditEventType.PERMISSION_DENIED,
        AuditEventType.SIGN_IN_THROTTLED,
        AuditEventType.USER_ROLE_CHANGED,
        AuditEventType.KILL_SWITCH_RELEASED,
        AuditEventType.BROKER_LINKED,
    }
)

#: Keys that must never reach a payload. Checked rather than trusted, because
#: the caller who passes one is not doing it deliberately - they are passing a
#: dict through from somewhere else and have not looked inside it.
FORBIDDEN = ("password", "token", "secret", "key_hash", "nonce", "cookie", "authorization")


def _clean(detail: dict[str, Any] | None) -> dict[str, Any]:
    """Drop anything that looks like a credential, loudly.

    A dropped field is replaced by a marker rather than removed silently, so
    the reader of a payload can tell "nothing was passed" from "something was
    passed and refused".
    """
    if not detail:
        return {}
    safe: dict[str, Any] = {}
    for name, value in detail.items():
        if any(word in name.lower() for word in FORBIDDEN):
            safe[name] = "<withheld: looked like a credential>"
        else:
            safe[name] = value
    return safe


def record(
    session: Session,
    event: AuditEventType,
    *,
    summary: str,
    subject: str | None = None,
    user_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    role: str | None = None,
    address: str | None = None,
    user_agent: str | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditEvent | None:
    """Append one security event. Returns None if it could not be written.

    None rather than raising. Every caller is in the middle of doing something
    more important than logging it, and a log that can fail a sign-in is a log
    that takes the deployment down the first time the disk fills.
    """
    try:
        return audit.record(
            session,
            event,
            summary=summary,
            severity=Severity.WARNING if event in ALARMING else Severity.INFO,
            tenant_id=tenant_id,
            user_id=user_id,
            service="security",
            payload={
                # The account that was named. Present even when no such account
                # exists, which is most of what a failed sign-in log contains
                # and the whole shape of an enumeration attempt.
                "subject": subject,
                "role": role,
                "address": address,
                "user_agent": user_agent,
                **_clean(detail),
            },
        )
    except Exception:  # noqa: BLE001 - deliberate: see the docstring
        log.warning("security_log.write_failed", kind=str(event), exc_info=True)
        return None


def record_isolated(
    event: AuditEventType,
    *,
    summary: str,
    **fields: Any,
) -> None:
    """Record on a session of its own, and commit it.

    For the callers whose own transaction is being rolled back around them - a
    permission denial is raised as an exception, and the exception is what
    discards the session that would have carried the record of it. The same
    trap the sign-in limiter fell into, in a place where there is no request
    transaction left to commit.

    Silent on failure, including when there is no database at all. This is
    called from an exception handler, and an exception handler that raises
    replaces a 403 the caller can understand with a 500 that nobody can.
    """
    try:
        from app.db.session import session_scope

        with session_scope() as session:
            record(session, event, summary=summary, **fields)
    except Exception:  # noqa: BLE001 - deliberate: see the docstring
        log.warning("security_log.isolated_write_failed", kind=str(event), exc_info=True)


def recent(
    session: Session,
    *,
    limit: int = 100,
    since: datetime | None = None,
    events: Sequence[AuditEventType] | None = None,
    alarming_only: bool = False,
    now: datetime | None = None,
) -> list[AuditEvent]:
    """The security timeline, newest first.

    `since` defaults to a week. Not to "everything": the default answer to an
    unbounded question on a table that grows forever is a query that gets
    slower every day until somebody notices it as an outage.
    """
    moment = now or datetime.now(UTC)
    # `is not None`, not truthiness. An empty sequence is a filter that matched
    # nothing, and treating it as "no filter given" turns a mistyped event name
    # into the whole log - which is the one wrong answer that looks right. A
    # reader who asked for `auth.sign_in.faled` and got everything concludes
    # the filter is not supported; a reader who gets nothing looks at the name.
    wanted = tuple(events) if events is not None else SECURITY_EVENTS
    if alarming_only:
        wanted = tuple(e for e in wanted if e in ALARMING)

    statement = (
        select(AuditEvent)
        .where(AuditEvent.event_type.in_([str(e) for e in wanted]))
        .where(AuditEvent.occurred_at >= (since or moment - timedelta(days=7)))
        .order_by(AuditEvent.occurred_at.desc())
        .limit(max(1, min(limit, 1000)))
    )
    return list(session.scalars(statement))


def as_dict(event: AuditEvent) -> dict[str, Any]:
    """One row, shaped for a person reading it rather than for storage."""
    payload = dict(event.payload or {})
    return {
        "at": event.occurred_at.isoformat(),
        "event": event.event_type,
        "severity": event.severity,
        "summary": event.summary,
        "subject": payload.get("subject"),
        "role": payload.get("role"),
        "address": payload.get("address"),
        "user_agent": payload.get("user_agent"),
        "user_id": str(event.user_id) if event.user_id else None,
        "trace_id": event.trace_id,
        "detail": {
            k: v
            for k, v in payload.items()
            if k not in {"subject", "role", "address", "user_agent"}
        },
    }


def summarise(events: Sequence[AuditEvent]) -> dict[str, Any]:
    """What the timeline adds up to, for a page that has to say something
    before anybody scrolls.

    Counts, not conclusions. "Six failed sign-ins from two addresses" is a
    fact; "you are under attack" is a guess, and a dashboard that guesses
    teaches its reader to ignore it.
    """
    by_event: dict[str, int] = {}
    addresses: set[str] = set()
    subjects: set[str] = set()
    for event in events:
        by_event[event.event_type] = by_event.get(event.event_type, 0) + 1
        payload = event.payload or {}
        if payload.get("address"):
            addresses.add(str(payload["address"]))
        if payload.get("subject"):
            subjects.add(str(payload["subject"]))

    failed = by_event.get(str(AuditEventType.SIGN_IN_FAILED), 0)
    succeeded = by_event.get(str(AuditEventType.SIGN_IN_SUCCEEDED), 0)
    return {
        "total": len(events),
        "by_event": dict(sorted(by_event.items())),
        "distinct_addresses": len(addresses),
        "distinct_accounts_named": len(subjects),
        "sign_ins": {"succeeded": succeeded, "failed": failed},
        "alarming": sum(
            1 for e in events if e.event_type in {str(a) for a in ALARMING}
        ),
        "note": (
            "counts, not conclusions. Whether this is an attack or somebody "
            "on holiday with the wrong password is not a thing a count knows"
        ),
    }
