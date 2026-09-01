"""Chat, automation and the security posture (spec §46-47, §52).

The rule that governs this whole chapter: **nothing arriving from outside can
cause a trade.**

Not because a chat transport is untrustworthy in some special way, but because
it authenticates a *channel* rather than a person. Anyone holding the bot
token, anyone who compromised a phone, anyone in a group the message was
forwarded to, is indistinguishable from the owner. An order needs an API key
with the execute permission, which lives somewhere a human chose to put it.

So `/commands` is a *description* of what the channel would accept, and
`/command-check` tells a caller whether a given command is one of them. Neither
runs anything. The allowlist is the interesting part: it refuses by naming what
is permitted rather than by blocking what is dangerous, because a blocklist has
to anticipate every verb somebody might add later and an allowlist has to
anticipate nothing.

`/security` reports the posture rather than changing it, and reports it from
the live router table rather than from a document that was true once.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import ROLE_PERMISSIONS, Principal, require
from app.api.guard import PERMISSION_ATTR, find_ungated_routes, mutating_routes
from app.core.config import get_settings
from app.core.enums import Permission
from app.core.errors import ValidationFailedError
from app.db.session import get_db
from app.integrations import notify, telegram

router = APIRouter(prefix="/integrations", tags=["integrations"])

READ = Depends(require(Permission.READ))
SETTINGS_WRITE = Depends(require(Permission.SETTINGS_WRITE))


@router.get("/commands")
def read_commands(_: Principal = READ) -> dict[str, Any]:
    """What the chat channel will answer, and why that is all it will answer."""
    return {
        "allowed": sorted(notify.READ_ONLY_COMMANDS),
        "allowlist_not_blocklist": True,
        "why": (
            "a chat transport authenticates a channel, not a person: anyone "
            "holding the bot token is indistinguishable from the owner, so the "
            "channel answers questions and nothing else"
        ),
        "trading_requires": "an API key carrying the execute permission",
        "note": "this endpoint describes the channel; it does not run anything",
    }


@router.get("/command-check")
def read_command_check(
    text: str = Query(min_length=1, description="The command as a user would type it."),
    _: Principal = READ,
) -> dict[str, Any]:
    """Would the channel accept this, and if not, why not.

    Runs the real `accept_command`, so the answer is the answer the channel
    would give rather than a second implementation that can disagree with it.
    """
    try:
        request = notify.accept_command(text, source="preview")
    except ValidationFailedError as exc:
        return {
            "accepted": False,
            "reason": exc.message,
            "allowed": sorted(notify.READ_ONLY_COMMANDS),
            "executed": False,
        }
    payload = request.as_dict()
    payload["accepted"] = True
    # Stated explicitly: checking a command is not running it, and this route
    # has no path to anything that could.
    payload["executed"] = False
    return payload


@router.get("/webhooks")
def read_webhooks(_: Principal = READ) -> dict[str, Any]:
    """How an inbound webhook is verified, and what a verified one may ask for.

    A valid signature is not sufficient on its own: a captured request replayed
    tomorrow carries a perfectly valid one, and the timestamp is the only thing
    that makes it invalid.
    """
    settings = get_settings()
    return {
        "signature": "HMAC-SHA256 over the raw body, compared in constant time",
        "why_constant_time": (
            "an ordinary comparison returns as soon as it finds a difference, and "
            "the time it took says how many leading bytes were right"
        ),
        "max_age_seconds": notify.MAX_WEBHOOK_AGE.total_seconds(),
        "why_max_age": (
            "a captured request replayed later carries a valid signature; the "
            "timestamp is what expires"
        ),
        "secret_configured": False,
        "unset_secret_means": (
            "not configured to receive webhooks — never 'accept everything'"
        ),
        "verified_webhooks_may": sorted(notify.READ_ONLY_COMMANDS),
        "environment": settings.env,
    }


@router.get("/security")
def read_security(_: Principal = READ) -> dict[str, Any]:
    """The security posture, read from the running application.

    Every figure here comes from the live router table or the live settings.
    A security page assembled from a document is a page that was true once.
    """
    from app.main import app as fastapi_app

    settings = get_settings()
    return {
        "require_auth": settings.require_auth,
        "auth_model": "API key identifies a tenant and a user; a role grants a tier",
        "roles": {
            role.value: sorted(p.value for p in perms)
            for role, perms in ROLE_PERMISSIONS.items()
        },
        "anonymous_holds": ["read"],
        "routes": {
            "mutating": [f"{'/'.join(m)} {p}" for p, m in mutating_routes(fastapi_app)],
            "ungated": [
                str(o)
                for o in find_ungated_routes(fastapi_app, require_auth=settings.require_auth)
            ],
        },
        "gate": {
            "checked_at": "import time, not first request",
            "marker": PERMISSION_ATTR,
            "refuses_to_start_if": (
                "a route can change state without declaring a permission, or an "
                "execute route exists while MOLIDO_REQUIRE_AUTH is false"
            ),
        },
        "non_read_permissions_require_authentication": True,
        "note": (
            "auth being off is safe only while no endpoint changes state; the "
            "application refuses to start if one is added without it"
        ),
    }


@router.get("/telegram")
def read_telegram(
    _: Principal = READ,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Whether the chat channel is configured, and whether the token works.

    `getMe` proves the token without sending anything to the channel, so a
    wrong token fails here rather than at the moment an alert matters. Nothing
    on this route posts a message: the check and the send are separate, because
    a health check that notifies everybody every time it runs is its own
    outage.
    """
    state = telegram.check(session)
    return {
        **state,
        "read_only": True,
        "allowed_commands": sorted(notify.READ_ONLY_COMMANDS),
        "why_read_only": (
            "a chat transport authenticates a channel, not a person: anyone "
            "holding the bot token is indistinguishable from the owner, so the "
            "channel answers questions and nothing else"
        ),
        "deduplication": (
            "outbound alerts share the incident cooldown, so a flapping "
            "condition does not send a message every thirty seconds - the "
            "alert everybody learns to ignore is the one that mattered"
        ),
    }


class TelegramPayload(BaseModel):
    """What the site may set. Every field optional and every omission means
    "leave it alone" - a form that posts only the recipients must not wipe a
    token the operator cannot re-read from the page."""

    token: str | None = None
    chat_ids: list[str] | None = None
    enabled: bool | None = None


@router.put("/telegram")
def write_telegram(
    payload: TelegramPayload,
    _: Principal = SETTINGS_WRITE,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Save the bot token and who it talks to.

    Behind `settings.write` rather than `read`: a token is the channel's
    identity, and whoever can change it can redirect every alert this system
    produces to a chat the owner does not read.

    The response never contains the token. It comes back masked, like every
    other read of it, so a page that displays what it saved cannot become a
    way to recover a secret from a screen somebody left open.
    """
    from app.services import telegram_settings

    channel = telegram_settings.save(
        session,
        token=payload.token,
        chat_ids=payload.chat_ids,
        enabled=payload.enabled,
    )
    session.commit()
    return channel.as_dict()


@router.post("/telegram/test")
def test_telegram(
    _: Principal = SETTINGS_WRITE,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Send one real message to every configured recipient.

    A real send rather than `getMe`, because the two prove different things:
    `getMe` proves the token, this proves the *recipients* - and a chat id
    that is right-shaped and wrong is invisible until a message fails to
    arrive. Deliberately un-deduplicated: a test somebody asked for that is
    silently suppressed by the alert cooldown teaches the opposite of what
    they were testing.
    """
    from datetime import UTC, datetime

    from app.integrations import notify

    message = notify.Message(
        urgency=notify.Urgency.INFO,
        at=datetime.now(UTC),
        title="MolidoTrade AI",
        body=(
            "Test message. If you can read this, this chat is on the alert "
            "list - the channel answers questions and can never place an order."
        ),
    )
    delivery = telegram.send(message, session=session)
    return {
        "sent": delivery.sent,
        "delivered_to": delivery.chat_id,
        "reason": delivery.reason,
        "note": (
            "sent without the alert cooldown: a test that is silently "
            "suppressed proves the opposite of what it was asked to prove"
        ),
    }


@router.get("/mcp")
def read_mcp(_: Principal = READ) -> dict[str, Any]:
    """What an AI agent may ask this system, and what it may never do."""
    from app.integrations import mcp

    return mcp.manifest()


@router.get("/mcp/{tool_name}")
def call_mcp(
    tool_name: str,
    _: Principal = READ,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Run one read-only tool.

    A GET, and deliberately: every tool here reads, so making them GETs means
    the execution gate never has to decide whether an agent may mutate - the
    question does not arise. A POST here would be a mutating route one refactor
    away from doing something.
    """
    from app.integrations import mcp

    return mcp.call(session, tool_name)
