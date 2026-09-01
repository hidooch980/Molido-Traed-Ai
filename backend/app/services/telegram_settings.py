"""Read and write the chat channel's configuration.

Three rules, and all three are about the token:

**It is stored in full and returned never.** Sending needs the whole token, so
hashing it is not an option; every read path returns `masked` instead, and the
one function that returns the real value is named for what it does and is
called only by the sender.

**The database is the source, the environment is the fallback.** A deployment
that set `MOLIDO_TELEGRAM_BOT_TOKEN` in its env file keeps working exactly as
it did - until somebody saves a token from the site, at which point the stored
one wins. Two sources that silently disagree is the failure this ordering
avoids: the newer, deliberate act wins.

**A chat id is a string.** Telegram ids exceed 32 bits and a group id is
negative; anything that treats them as machine integers eventually truncates
one, and the alert goes to nobody with no error anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ValidationFailedError
from app.models.telegram_config import TelegramConfig

#: How much of the token the site is allowed to see. Enough to tell two tokens
#: apart, not enough to use one: the numeric bot id before the colon is public
#: in every Telegram API error message anyway.
VISIBLE_PREFIX = 8


@dataclass(frozen=True)
class ChannelConfig:
    """What the channel is configured to do, safe to hand to a route."""

    token: str
    chat_ids: tuple[str, ...]
    enabled: bool
    source: str

    @property
    def masked(self) -> str | None:
        if not self.token:
            return None
        head = self.token[:VISIBLE_PREFIX]
        return f"{head}…{len(self.token)} chars"

    @property
    def ready(self) -> bool:
        return bool(self.token and self.chat_ids and self.enabled)

    def as_dict(self) -> dict[str, Any]:
        """Never includes the token. This is the shape routes return."""
        return {
            "configured": bool(self.token),
            "enabled": self.enabled,
            "masked_token": self.masked,
            "chat_ids": list(self.chat_ids),
            "recipients": len(self.chat_ids),
            "source": self.source,
            "ready": self.ready,
            "note": (
                "the token is stored and never returned. A saved token "
                "replaces the environment's; clearing it falls back to the "
                "environment rather than to silence"
            ),
        }


def _row(session: Session) -> TelegramConfig | None:
    return session.scalars(select(TelegramConfig).limit(1)).first()


def load(session: Session | None) -> ChannelConfig:
    """The configuration in force, database first and environment second.

    A `None` session is the sender running somewhere without one; the
    environment answer is still correct there, and returning an empty
    configuration instead would mute a working deployment.
    """
    settings = get_settings()
    env_token = (getattr(settings, "telegram_bot_token", "") or "").strip()
    env_chat = (getattr(settings, "telegram_chat_id", "") or "").strip()

    row = _row(session) if session is not None else None
    if row is not None and (row.bot_token or row.chat_ids):
        return ChannelConfig(
            token=row.bot_token or env_token,
            chat_ids=tuple(str(c) for c in (row.chat_ids or []))
            or ((env_chat,) if env_chat else ()),
            enabled=bool(row.enabled),
            source="site" if row.bot_token else "site+env",
        )

    return ChannelConfig(
        token=env_token,
        chat_ids=(env_chat,) if env_chat else (),
        enabled=True,
        source="environment",
    )


def _clean_chat_ids(raw: list[Any] | None) -> tuple[str, ...]:
    """Validated ids, deduplicated, order kept.

    Refused rather than dropped: an id somebody typed wrong is a person who
    thinks they will be alerted and will not be, and silently discarding it
    is how that goes unnoticed until the day it matters.
    """
    out: list[str] = []
    for entry in raw or []:
        text = str(entry).strip()
        if not text:
            continue
        candidate = text[1:] if text.startswith("-") else text
        if not candidate.isdigit():
            raise ValidationFailedError(
                f"{text!r} is not a Telegram chat id. Ids are numeric and a "
                "group's is negative - a username or a link is not one.",
                chat_id=text,
            )
        if text not in out:
            out.append(text)
    return tuple(out)


def save(
    session: Session,
    *,
    token: str | None = None,
    chat_ids: list[Any] | None = None,
    enabled: bool | None = None,
) -> ChannelConfig:
    """Store what was given, leave what was not.

    `token=None` means "unchanged" and `token=""` means "clear it" - two
    different intentions that one nullable field would collapse into whichever
    the caller happened to send.
    """
    row = _row(session)
    if row is None:
        row = TelegramConfig(bot_token="", chat_ids=[], enabled=True)
        session.add(row)

    if token is not None:
        cleaned = token.strip()
        if cleaned and ":" not in cleaned:
            raise ValidationFailedError(
                "that does not look like a bot token. BotFather issues them as "
                "digits, a colon, then a long secret - a token with no colon "
                "would be refused by Telegram on the first send.",
            )
        row.bot_token = cleaned

    if chat_ids is not None:
        row.chat_ids = list(_clean_chat_ids(chat_ids))

    if enabled is not None:
        row.enabled = bool(enabled)

    session.flush()
    return load(session)
