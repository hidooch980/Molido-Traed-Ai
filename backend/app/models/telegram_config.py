"""The chat channel's own configuration, set from the site rather than the host.

The token used to live in the env file, which meant changing it was an SSH
session and a container restart - so in practice it was never set at all. A
channel nobody can configure is a channel nobody uses, and an alert path
nobody uses is the same as not having one.

One row, always. The token is stored because sending needs it in full; every
read path returns a masked prefix instead, and nothing here is ever logged.
Recipients are a list because an alert that reaches one phone is an alert that
waits for one person to wake up.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import JSONType


class TelegramConfig(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """The bot token and who it talks to."""

    __tablename__ = "telegram_config"

    #: Stored in full because the API needs it in full. Never returned by any
    #: route and never logged - `masked_token` is what the site sees.
    bot_token: Mapped[str] = mapped_column(String(200), default="", nullable=False)

    #: Chat ids, as strings: Telegram ids exceed 32 bits and a group id is
    #: negative, so anything that treats them as machine ints eventually
    #: truncates one and sends somebody else's alerts to nobody.
    chat_ids: Mapped[list[Any]] = mapped_column(
        JSONType, default=list, nullable=False
    )

    #: Off is a state, not an absence. A deployment that has a token and has
    #: deliberately muted the channel is different from one that never had a
    #: token, and the two want different messages on the page.
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
