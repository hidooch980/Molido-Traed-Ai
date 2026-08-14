"""Send to Telegram, under the rules the rest of this system already follows.

`notify` decides what a message says and what must never appear in one. This
sends it, and the sending is where the mistakes live: a channel that repeats
one condition four hundred times, a token in a log line, a bot that answers
"buy EURUSD" because somebody typed it.

Four constraints, and none of them is new - each one is a rule that already
exists somewhere in this codebase, applied here.

**Read-only.** The channel answers questions and does nothing else. A chat
transport authenticates a channel, not a person: anyone holding the bot token
is indistinguishable from the owner, and a token sits in a config file on a
host that gets brute-forced daily. Trading needs an API key with the execute
permission, and this is not that.

**Deduplicated through incident memory.** The cooldown already built for alerts
is the one used here, so a flapping container does not send a message every
thirty seconds. An alert everybody has learned to ignore is the one that
mattered.

**Secrets redacted before the message exists.** `notify.format_alert` redacts
the facts while building the `Message`, so nothing here redacts anything and
nothing here re-implements that rule - two implementations of one redaction
disagree eventually, and the disagreement is a leak.

**Unconfigured means off, never open.** No token is not "send to nobody" and
not "try anyway" - it is a stated, reported refusal, the same way an unset
webhook secret means "not configured to receive" rather than "accept
everything".
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ValidationFailedError
from app.integrations import notify
from app.ops import incidents as incident_memory

API_ROOT = "https://api.telegram.org"

#: Telegram rejects anything longer, and a truncated alert that says so is
#: better than one the API silently refuses.
MAX_MESSAGE = 4096

#: How long to wait on the network. Short: an alert that blocks a health check
#: for a minute has become the outage.
TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class Delivery:
    """What happened to one message. Never contains the token or the payload."""

    sent: bool
    reason: str | None = None
    suppressed: bool = False
    chat_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "sent": self.sent,
            "suppressed": self.suppressed,
            "reason": self.reason,
            "chat_id": self.chat_id,
        }


def configured() -> tuple[bool, str | None]:
    """Whether this deployment can send at all, and why not if it cannot."""
    settings = get_settings()
    token = (getattr(settings, "telegram_bot_token", "") or "").strip()
    chat = (getattr(settings, "telegram_chat_id", "") or "").strip()

    if not token:
        return False, (
            "no bot token is set, which means this deployment is not configured "
            "to send - never 'send to nobody' and never 'try anyway'"
        )
    if not chat:
        return False, "a bot token is set but no channel, so there is nowhere to send"
    return True, None


def _post(method: str, payload: dict[str, Any]) -> tuple[bool, str]:
    """One call to the Telegram API.

    The token goes in the URL because that is the API's design, and no part of
    this function returns or logs that URL. Errors report the API's message,
    never the request.
    """
    settings = get_settings()
    token = (getattr(settings, "telegram_bot_token", "") or "").strip()
    url = f"{API_ROOT}/bot{token}/{method}"
    # Checked rather than assumed. API_ROOT is a constant today, but a scheme
    # this function does not expect would turn a bot token into a file read or
    # a request to somewhere nobody chose - and the check costs one comparison.
    if not url.startswith("https://"):
        return False, "refusing to send over anything but https"

    body = urllib.parse.urlencode(payload).encode("utf-8")

    request = urllib.request.Request(  # noqa: S310 - scheme checked above
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(  # noqa: S310 - scheme checked above
            request, timeout=TIMEOUT_SECONDS
        ) as response:
            answer = json.loads(response.read())
        if answer.get("ok"):
            return True, "delivered"
        # Telegram's own description, which is specific and useful. The URL is
        # deliberately absent from anything returned here.
        return False, str(answer.get("description") or "the API refused the message")
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get("description")
        except Exception:  # noqa: BLE001 - the status alone is still useful
            detail = None
        return False, f"HTTP {exc.code}: {detail or 'no detail'}"
    except Exception as exc:  # noqa: BLE001 - reported, never swallowed
        return False, f"{type(exc).__name__}: could not reach the Telegram API"


def send(
    message: notify.Message,
    *,
    session: Session | None = None,
    fingerprint: str | None = None,
    now: datetime | None = None,
) -> Delivery:
    """Send one message, subject to configuration and the alert cooldown.

    `fingerprint` opts into deduplication. Without it every call sends, which
    is right for a message a person asked for and wrong for one a checker
    produces - so the caller states which it is rather than this guessing.
    """
    ready, reason = configured()
    if not ready:
        return Delivery(sent=False, reason=reason)

    if fingerprint and session is not None:
        allowed, why = incident_memory.should_alert(session, fingerprint, now=now)
        if not allowed:
            return Delivery(sent=False, suppressed=True, reason=why)

    # `Message` was already built by `notify.format_alert`, which redacts the
    # facts on the way in. Re-formatting here would be a second implementation
    # of the same rule, and two of those disagree eventually.
    text = f"{message.title}\n\n{message.body}"
    if len(text) > MAX_MESSAGE:
        text = text[: MAX_MESSAGE - 40] + "\n\n[truncated]"

    settings = get_settings()
    chat = (getattr(settings, "telegram_chat_id", "") or "").strip()
    ok, detail = _post(
        "sendMessage",
        {"chat_id": chat, "text": text, "disable_web_page_preview": "true"},
    )

    if ok and fingerprint and session is not None:
        incident_memory.mark_alerted(session, fingerprint, now=now)

    return Delivery(sent=ok, reason=None if ok else detail, chat_id=chat if ok else None)


def answer(text: str, *, source: str = "telegram") -> dict[str, Any]:
    """What the channel would reply to an inbound message.

    Runs the real `accept_command`, so the answer is the answer the channel
    gives rather than a second implementation that can disagree with it. A
    command outside the allowlist is refused with the list, because a bot that
    says only "no" teaches nobody what it does.
    """
    # `accept_command` refuses by raising, and the exception carries the command
    # and the allowlist. Caught here rather than propagated: a chat message is
    # not a request that deserves a stack trace, and the refusal is the reply.
    try:
        request = notify.accept_command(text, source=source)
    except ValidationFailedError as exc:
        return {
            "accepted": False,
            "command": getattr(exc, "context", {}).get("command"),
            "reason": str(exc),
            "allowed": sorted(notify.READ_ONLY_COMMANDS),
            "note": (
                "this channel answers questions and places no orders. Anyone "
                "holding the bot token is indistinguishable from the owner, so "
                "trading needs an API key carrying the execute permission"
            ),
        }

    return {
        "accepted": True,
        "command": request.command,
        "reason": None,
        "allowed": sorted(notify.READ_ONLY_COMMANDS),
        "note": (
            "this channel answers questions and places no orders. Anyone "
            "holding the bot token is indistinguishable from the owner, so "
            "trading needs an API key carrying the execute permission"
        ),
    }


def check() -> dict[str, Any]:
    """Ask Telegram who this bot is, without sending anything to anybody.

    The one call worth making before trusting the configuration: a wrong token
    fails here rather than at the moment an alert matters.
    """
    ready, reason = configured()
    if not ready:
        return {"configured": False, "reason": reason}

    ok, detail = _post("getMe", {})
    return {
        "configured": True,
        "reachable": ok,
        "detail": detail,
        "note": "getMe sends nothing to the channel; it only proves the token works",
    }
