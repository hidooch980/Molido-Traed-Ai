"""Providers, canonical instruments, and broker-specific symbol mappings.

Canonical instruments are global (not tenant-scoped): XAUUSD is the same
instrument for everyone. Broker symbols are tenant-scoped, because a tenant's
broker may name and size it differently and those properties drive real money
calculations.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import AssetClass
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import JSONType, UUIDType


class Provider(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A market-data source. Adapters are replaceable (spec §4)."""

    __tablename__ = "providers"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="market_data", nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Declared capabilities: {"ohlcv": true, "ticks": false, "depth": false, ...}
    capabilities: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    # Operator trust weight used when reconciling conflicting providers (0..1).
    trust_weight: Mapped[float] = mapped_column(Numeric(4, 3), default=0.5, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Instrument(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Canonical instrument, independent of any broker's naming."""

    __tablename__ = "instruments"

    symbol: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    asset_class: Mapped[AssetClass] = mapped_column(String(32), nullable=False)
    base_currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    quote_currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    exchange: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Holiday calendar this instrument follows: FX, CRYPTO, XNYS, CME, ...
    market_code: Mapped[str] = mapped_column(String(16), default="FX", nullable=False, index=True)
    # IANA name, e.g. "Etc/UTC" or "America/New_York". Sessions are derived here.
    timezone: Mapped[str] = mapped_column(String(64), default="Etc/UTC", nullable=False)
    # Weekly trading windows in the instrument's own timezone:
    # [{"day": 0, "open": "00:00", "close": "24:00"}, ...] where day 0 = Monday.
    # Empty means "use the asset-class default" (see services/sessions.py).
    trading_hours: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    broker_symbols: Mapped[list[BrokerSymbol]] = relationship(
        back_populates="instrument", cascade="all, delete-orphan"
    )


class BrokerSymbol(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Broker-specific contract properties for a canonical instrument (spec §7).

    These values are load-bearing for position sizing; they are stored exactly
    as the broker reports them and never inferred.
    """

    __tablename__ = "broker_symbols"
    __table_args__ = (
        UniqueConstraint("tenant_id", "broker_code", "raw_symbol", name="uq_broker_symbol"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("instruments.id", ondelete="CASCADE"), index=True
    )
    broker_code: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_symbol: Mapped[str] = mapped_column(String(64), nullable=False)

    contract_size: Mapped[float | None] = mapped_column(Numeric(20, 8), nullable=True)
    digits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    point: Mapped[float | None] = mapped_column(Numeric(20, 10), nullable=True)
    tick_size: Mapped[float | None] = mapped_column(Numeric(20, 10), nullable=True)
    tick_value: Mapped[float | None] = mapped_column(Numeric(20, 10), nullable=True)
    volume_min: Mapped[float | None] = mapped_column(Numeric(20, 8), nullable=True)
    volume_max: Mapped[float | None] = mapped_column(Numeric(20, 8), nullable=True)
    volume_step: Mapped[float | None] = mapped_column(Numeric(20, 8), nullable=True)
    margin_rules: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    spread_model: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    trading_hours: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    instrument: Mapped[Instrument] = relationship(back_populates="broker_symbols")
