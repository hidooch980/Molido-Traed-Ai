"""Safe mode (spec §71).

A process-local latch that blocks risk-increasing actions while monitoring and
reconciliation continue. It is intentionally simple and in-memory at this
milestone: nothing in the codebase yet increases risk, but every later phase
must consult `SafeMode.assert_can_increase_risk()` before acting, so the choke
point exists from the start.

Persisted, multi-process safe-mode state lands with the Stability Core phase.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from app.core.errors import SafeModeError


class SafeModeReason(StrEnum):
    CRITICAL_DATA_FAILURE = "critical_data_failure"
    BROKER_UNCERTAINTY = "broker_uncertainty"
    RISK_ENGINE_UNAVAILABLE = "risk_engine_unavailable"
    DATABASE_INCONSISTENCY = "database_inconsistency"
    RECONCILIATION_FAILURE = "reconciliation_failure"
    SECURITY_INCIDENT = "security_incident"
    MODEL_HEALTH_FAILURE = "model_health_failure"
    SYSTEM_OVERLOAD = "system_overload"
    MANUAL = "manual"


@dataclass
class SafeModeState:
    active: bool = False
    reasons: set[SafeModeReason] = field(default_factory=set)
    since: datetime | None = None
    detail: str | None = None


class SafeMode:
    """Global latch. Engaging is cheap; clearing requires an explicit reason."""

    _lock = threading.Lock()
    _state = SafeModeState()

    @classmethod
    def state(cls) -> SafeModeState:
        return cls._state

    @classmethod
    def engage(cls, reason: SafeModeReason, detail: str | None = None) -> None:
        with cls._lock:
            if not cls._state.active:
                cls._state = SafeModeState(
                    active=True,
                    reasons={reason},
                    since=datetime.now(UTC),
                    detail=detail,
                )
            else:
                cls._state.reasons.add(reason)
                if detail:
                    cls._state.detail = detail

    @classmethod
    def clear(cls, reason: SafeModeReason) -> None:
        """Clear one reason. Safe mode lifts only when no reasons remain."""
        with cls._lock:
            cls._state.reasons.discard(reason)
            if not cls._state.reasons:
                cls._state = SafeModeState()

    @classmethod
    def assert_can_increase_risk(cls) -> None:
        st = cls._state
        if st.active:
            raise SafeModeError(
                "System is in safe mode; risk-increasing actions are blocked.",
                reasons=sorted(r.value for r in st.reasons),
                since=st.since.isoformat() if st.since else None,
            )

    @classmethod
    def reset_for_tests(cls) -> None:
        with cls._lock:
            cls._state = SafeModeState()
