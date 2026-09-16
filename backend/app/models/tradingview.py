"""TradingView alerts, kept as a record and never as an instruction.

Two tables. The config is one row holding a hash of the webhook secret - the
secret itself is shown once when it is made and never stored, because checking
a webhook needs only to compare, unlike Telegram where sending needs the token.
Alerts are what arrived, verbatim, so what TradingView said can later be
measured against what the market did.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import JSONType


class TradingViewConfig(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """The webhook secret, as a hash."""

    __tablename__ = "tradingview_config"

    secret_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    #: The first characters, so the page can say which secret is active.
    secret_hint: Mapped[str] = mapped_column(String(8), default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class TradingViewAlert(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One alert as it arrived. `created_at` is when."""

    __tablename__ = "tradingview_alerts"

    symbol: Mapped[str] = mapped_column(String(32), default="", nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    timeframe: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: The whole body minus the secret.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
