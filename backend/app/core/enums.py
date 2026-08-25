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
    """What a caller is allowed to do (spec §45).

    The first three were the whole model, and three tiers cannot express the
    difference between the people who use this system. `OWNER`, `ADMIN` and
    `TRADER` all held exactly `READ | SIMULATE | EXECUTE`, which is to say the
    roles were distinct in the database and identical in effect: an account
    added to read analysis could send an order. The rest exist so that a role
    can be given what it needs and nothing else.

    Two of them are one capability split in half, deliberately. `HALT` engages
    the kill switch and `RELEASE` clears it, and they are not the same
    authority: stopping moves toward safety and starting moves away from it.
    Everyone trusted enough to watch the system is trusted enough to stop it;
    only the account holder decides it may run again. A single `killswitch`
    permission would have made those one decision, and whoever was given the
    power to stop would have been given the power to start.

    `VIEWER` is left out of `HALT` on purpose - self sign-up lands there, so a
    stranger with an account would otherwise be able to halt trading.
    """

    #: The floor. Everything the dashboard displays.
    READ = "read"
    #: Run the chain without sending anything: replay, backtest, dry-run.
    SIMULATE = "simulate"
    #: Send a live order. Necessary and not sufficient - the plan must also
    #: include live execution, and both are checked separately.
    EXECUTE = "execute"

    #: Engage the kill switch. Wide on purpose.
    HALT = "halt"
    #: Clear a halt. Narrow on purpose.
    RELEASE = "release"

    #: Create users, disable them, change their roles.
    USERS_MANAGE = "users.manage"
    #: Issue and revoke API keys.
    KEYS_MANAGE = "keys.manage"
    #: Connect or disconnect a broker account. This is the permission that
    #: stands next to real money, so it is not given to an infrastructure role.
    BROKER_MANAGE = "broker.manage"
    #: Change deployment settings: watchlist, autopilot mode, intervals.
    SETTINGS_WRITE = "settings.write"
    #: Enter or change a prop-firm rulebook. A wrong rule here ends an account,
    #: which is why it stays with the person whose account it is.
    RULEBOOK_WRITE = "rulebook.write"
    #: Read the security and audit log. Not part of READ: the log records who
    #: signed in from where, and that is not everybody's business.
    AUDIT_READ = "audit.read"


class AuditEventType(StrEnum):
    """Everything worth being able to look up afterwards.

    The `auth.`, `user.`, `key.`, `broker.` and `killswitch.` families are the
    security log. They are listed here rather than in a separate enum because
    they land in the same table as everything else, and one timeline is the
    point: "the collector failed, then somebody signed in from a new address,
    then the kill switch was released" is a sentence you can only read if all
    three are in one place, in order.
    """

    INGESTION_STARTED = "ingestion.started"
    INGESTION_COMPLETED = "ingestion.completed"
    INGESTION_FAILED = "ingestion.failed"
    QUALITY_FINDING = "data_quality.finding"
    INSTRUMENT_CREATED = "instrument.created"
    SAFE_MODE_ENGAGED = "safe_mode.engaged"
    SAFE_MODE_CLEARED = "safe_mode.cleared"
    API_REQUEST = "api.request"

    # --- the security log ------------------------------------------------
    #
    # Failures are recorded as carefully as successes, and the two are
    # separate event types rather than one with an outcome field, so "show me
    # every failed sign-in" is an indexed lookup rather than a scan that has
    # to open every payload.
    SIGN_IN_SUCCEEDED = "auth.sign_in.succeeded"
    SIGN_IN_FAILED = "auth.sign_in.failed"
    #: Refused by the rate limiter before the password was read. Distinct from
    #: a failure: it says nothing about whether the password was right, and
    #: counting it as a failure would overstate how close an attacker got.
    SIGN_IN_THROTTLED = "auth.sign_in.throttled"
    HUMAN_CHECK_FAILED = "auth.human_check.failed"
    SIGN_OUT = "auth.sign_out"
    #: Somebody authenticated reached for authority they do not hold. Rare by
    #: construction, and the most interesting line in the log when it is not.
    PERMISSION_DENIED = "auth.permission.denied"

    USER_CREATED = "user.created"
    USER_REGISTERED = "user.registered"
    USER_ROLE_CHANGED = "user.role_changed"
    USER_ACTIVE_CHANGED = "user.active_changed"
    # The value is the name of an event, not a password. Ruff reads any
    # constant with "password" in its name as a leaked secret, which is
    # the right default and wrong here.
    PASSWORD_CHANGED = "user.password_changed"  # noqa: S105
    DEPLOYMENT_CLAIMED = "user.deployment_claimed"

    KEY_ISSUED = "key.issued"
    KEY_REVOKED = "key.revoked"

    BROKER_LINKED = "broker.linked"

    KILL_SWITCH_ENGAGED = "killswitch.engaged"
    KILL_SWITCH_RELEASED = "killswitch.released"
