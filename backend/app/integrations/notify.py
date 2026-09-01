"""Telegram and n8n (spec phases 45-46, §46-47).

One rule governs this whole module, and it is the reason it is written as
carefully as the execution layer:

**Nothing arriving from outside can cause a trade.**

A Telegram message is a message. It cannot place an order, cannot resize one,
cannot disengage a kill switch, and cannot approve anything. The chat is an
output device with a read-only query surface, and that is not a policy anybody
has to remember — there is no code path from an inbound message to the
execution engine, and a test parses this module's imports to prove it.

The reason is not paranoia about Telegram specifically. It is that a chat
transport authenticates a *channel*, not a person: anyone holding the bot token,
anyone who has compromised a phone, anyone in a group that got forwarded, is
indistinguishable from the owner. An order needs an API key with the execute
permission, which `app.api.deps` checks and which lives somewhere a human chose
to put it.

Outbound messages carry the same honesty as everything else: an alert that
cannot state its measurement says so rather than rounding it to something
reassuring.

For n8n, the direction is inbound and the same rule applies. A webhook is
verified by HMAC over the raw body — signature checks that compare with `==`
leak the answer a byte at a time, so the comparison is constant-time — and a
verified webhook may still only request read-only work.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from app.core.errors import ValidationFailedError

# Inbound requests may only ask for these. Absent from the set, permanently:
# anything that opens, closes, resizes or authorises a position, and anything
# that changes a limit.
READ_ONLY_COMMANDS = frozenset(
    {
        "status",
        "positions",
        "health",
        "why_no_trade",
        "journal",
        "drawdown",
        "help",
        # Added deliberately and visibly, which is the point of an allowlist:
        # each one is a question with a published answer and no side effect.
        "accounts",
        "orders",
        "brains",
        "challenge",
        "prices",
    }
)

# A webhook older than this is refused even with a valid signature: a captured
# request replayed later is a valid request, and the timestamp is what makes it
# not one.
MAX_WEBHOOK_AGE = timedelta(minutes=5)


class Urgency(StrEnum):
    """How loud a message should be.

    CRITICAL exists so an operator's notification settings can distinguish "a
    limit was breached" from "the daily summary is ready". A channel where
    everything is urgent is a channel where nothing is.
    """

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class Message:
    """An outbound notification. Text and urgency, nothing actionable."""

    urgency: Urgency
    title: str
    body: str
    at: datetime
    context: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValidationFailedError("a notification with no title is noise")
        if self.at.tzinfo is None:
            raise ValidationFailedError("notification timestamps must be timezone-aware")

    def as_dict(self) -> dict[str, Any]:
        return {
            "urgency": self.urgency.value,
            "title": self.title,
            "body": self.body,
            "at": self.at.isoformat(),
            "context": self.context,
            # Stated on every outbound message: this channel cannot be replied
            # to with an instruction that does anything.
            "actionable": False,
        }


def redact(payload: dict[str, Any]) -> dict[str, Any]:
    """Strip anything that must never leave the process.

    Chat history is durable, searchable, and frequently forwarded. A token that
    reaches it is a token that has to be rotated, and the person who pasted it
    usually finds out much later.
    """
    secret_ish = ("token", "key", "secret", "password", "credential", "authorization")
    cleaned: dict[str, Any] = {}
    for name, value in payload.items():
        if any(marker in name.lower() for marker in secret_ish):
            cleaned[name] = "[redacted]"
        elif isinstance(value, dict):
            cleaned[name] = redact(value)
        else:
            cleaned[name] = value
    return cleaned


def format_alert(
    *,
    title: str,
    urgency: Urgency,
    facts: dict[str, Any],
    unavailable: dict[str, str] | None = None,
    at: datetime | None = None,
) -> Message:
    """Build a message that names what it could not measure.

    `unavailable` is not decoration. An alert that silently omits the figure it
    could not compute reads as an alert about a healthy system, which is the
    single most expensive way for a notification to be wrong.
    """
    lines = [f"{name}: {value}" for name, value in sorted(redact(facts).items())]
    for name, reason in sorted((unavailable or {}).items()):
        lines.append(f"{name}: unavailable — {reason}")

    return Message(
        urgency=urgency,
        title=title,
        body="\n".join(lines) if lines else "no measurements available",
        at=at or datetime.now(UTC),
        context=redact(facts),
    )


@dataclass
class InboundRequest:
    """Something the outside world asked for. Read-only, always."""

    command: str
    arguments: dict[str, Any] = field(default_factory=dict)
    source: str = "unknown"

    def as_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "arguments": self.arguments,
            "source": self.source,
            "read_only": True,
        }


def accept_command(text: str, *, source: str) -> InboundRequest:
    """Parse an inbound instruction, refusing anything that is not a question.

    The refusal is by allowlist rather than blocklist. A blocklist has to
    anticipate every dangerous verb somebody might add later; an allowlist has
    to anticipate nothing, and adding a command to it is a visible change in a
    diff that somebody reviews.
    """
    command = (text or "").strip().lstrip("/").split()[0].lower() if text.strip() else ""
    if not command:
        raise ValidationFailedError("empty command")
    if command not in READ_ONLY_COMMANDS:
        raise ValidationFailedError(
            f"{command!r} is not a read-only command. This channel authenticates a "
            "channel, not a person: anyone holding the bot token is indistinguishable "
            "from the owner, so it can answer questions and nothing else. Trading "
            "needs an API key with the execute permission.",
            command=command,
            allowed=sorted(READ_ONLY_COMMANDS),
        )
    return InboundRequest(command=command, source=source)


def sign(body: bytes, secret: str) -> str:
    """HMAC-SHA256 over the raw body."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify_webhook(
    body: bytes,
    signature: str,
    secret: str,
    *,
    sent_at: datetime,
    now: datetime | None = None,
    max_age: timedelta = MAX_WEBHOOK_AGE,
) -> InboundRequest | None:
    """Check a webhook's signature and freshness. Returns None on any failure.

    `compare_digest` rather than `==`: an ordinary string comparison returns as
    soon as it finds a difference, and the time it took says how many leading
    bytes were right, which is enough to reconstruct a signature one byte at a
    time.
    """
    if not secret:
        # An unset secret must not mean "accept everything". It means the
        # deployment is not configured to receive webhooks.
        return None

    moment = now or datetime.now(UTC)
    if sent_at.tzinfo is None:
        return None
    age = moment - sent_at
    if age > max_age or age < -max_age:
        # A captured request replayed tomorrow carries a perfectly valid
        # signature; the timestamp is the only thing that makes it invalid.
        return None
    if not hmac.compare_digest(sign(body, secret), signature):
        return None
    return InboundRequest(command="webhook", arguments={"bytes": len(body)}, source="n8n")
