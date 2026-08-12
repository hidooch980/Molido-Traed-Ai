"""Shared vocabulary.

Kept in one place so the data layer, the (future) brain layer and the frontend
agree on the same strings. Values are stable wire identifiers - renaming one is
a migration, not a refactor.
"""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum


class Timeframe(StrEnum):
    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"
    W1 = "W1"
    MN1 = "MN1"

    @property
    def delta(self) -> timedelta:
        return _TIMEFRAME_DELTAS[self]

    @property
    def is_calendar_based(self) -> bool:
        """Months/weeks do not have a fixed duration; gap detection must differ."""
        return self in (Timeframe.W1, Timeframe.MN1)


_TIMEFRAME_DELTAS: dict[Timeframe, timedelta] = {
    Timeframe.M1: timedelta(minutes=1),
    Timeframe.M5: timedelta(minutes=5),
    Timeframe.M15: timedelta(minutes=15),
    Timeframe.M30: timedelta(minutes=30),
    Timeframe.H1: timedelta(hours=1),
    Timeframe.H4: timedelta(hours=4),
    Timeframe.D1: timedelta(days=1),
    Timeframe.W1: timedelta(weeks=1),
    Timeframe.MN1: timedelta(days=30),
}


class TradingSession(StrEnum):
    """Major FX sessions (spec §11 "session", §48 filters).

    Boundaries are defined in each centre's own local time and resolved through
    `zoneinfo`, so London and New York shift with their respective DST rules
    rather than drifting an hour apart twice a year.
    """

    SYDNEY = "sydney"
    TOKYO = "tokyo"
    LONDON = "london"
    NEW_YORK = "new_york"
    OFF = "off"


class HolidayKind(StrEnum):
    CLOSED = "closed"  # market does not trade at all
    EARLY_CLOSE = "early_close"  # shortened session
    LATE_OPEN = "late_open"


class Regime(StrEnum):
    """Market regimes (spec §12).

    UNCERTAIN is a first-class answer, not a fallback. The spec requires risk
    allocation to fall when regime confidence drops, which is impossible if the
    engine always names a regime.
    """

    TREND_UP = "trend_up"
    TREND_DOWN = "trend_down"
    RANGE = "range"
    BREAKOUT = "breakout"
    REVERSAL = "reversal"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"
    NEWS_EVENT = "news_event"
    UNCERTAIN = "uncertain"


class Decision(StrEnum):
    BUY = "buy"
    SELL = "sell"
    WAIT = "wait"


class RiskVerdict(StrEnum):
    APPROVE = "approve"
    REDUCE = "reduce"
    BLOCK = "block"


class AssetClass(StrEnum):
    FOREX = "forex"
    METAL = "metal"
    INDEX = "index"
    STOCK = "stock"
    FUTURE = "future"
    CRYPTO = "crypto"
    COMMODITY = "commodity"
    BOND = "bond"
    OTHER = "other"


class DataQualityIssue(StrEnum):
    MISSING_CANDLE = "missing_candle"
    DUPLICATE_BAR = "duplicate_bar"
    DUPLICATE_TICK = "duplicate_tick"
    INVALID_TIMESTAMP = "invalid_timestamp"
    NON_MONOTONIC_TIMESTAMP = "non_monotonic_timestamp"
    PRICE_GAP = "price_gap"
    ABNORMAL_SPREAD = "abnormal_spread"
    ABNORMAL_VOLUME = "abnormal_volume"
    OUTLIER = "outlier"
    INVALID_OHLC_RELATION = "invalid_ohlc_relation"
    NON_POSITIVE_PRICE = "non_positive_price"
    PROVIDER_CONFLICT = "provider_conflict"
    SESSION_MISMATCH = "session_mismatch"
    STALE_DATA = "stale_data"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class IngestionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"


class UserRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    TRADER = "trader"
    ANALYST = "analyst"
    VIEWER = "viewer"


class Permission(StrEnum):
    """Command-palette / API permission tiers (spec §45)."""

    READ = "read"
    SIMULATE = "simulate"
    EXECUTE = "execute"


class AuditEventType(StrEnum):
    INGESTION_STARTED = "ingestion.started"
    INGESTION_COMPLETED = "ingestion.completed"
    INGESTION_FAILED = "ingestion.failed"
    QUALITY_FINDING = "data_quality.finding"
    INSTRUMENT_CREATED = "instrument.created"
    SAFE_MODE_ENGAGED = "safe_mode.engaged"
    SAFE_MODE_CLEARED = "safe_mode.cleared"
    API_REQUEST = "api.request"
