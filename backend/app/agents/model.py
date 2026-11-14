"""Types for the agent registry.

A role here is a *description* of a responsibility and of which existing code
carries it today - not a running process. The status field is the honest
answer to "does this exist", taken from the stage-1 audit, and it is checked
by tests against the files it names so a mapping cannot point at nothing.

**No role can authorise itself past risk.** The permission ladder stops at L4
(CONTROL). L5 - changing risk policy, enabling real-money trading, moving
funds, changing security access - belongs to a named human and is not a value
this type can hold. `may_override_risk` and `can_submit_orders` exist only so
the refusal is visible on every serialised role; constructing a role with
either set raises.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any


class AgentGroup(StrEnum):
    SCALPING = "A_scalping"
    SMART_MONEY = "B_smart_money_ict"
    TECHNICAL = "C_technical_strategy"
    PREDICTION = "D_prediction_learning"
    RISK = "E_risk_capital"
    EXECUTION = "F_execution_supervision"
    CENTRAL = "G_central_intelligence"
    ROCKET = "H_rocket_trade_hunter"


class PermissionLevel(IntEnum):
    """L1-L4 only. L5 (human authorisation) is deliberately absent."""

    READ = 1  # read shared data and its own records
    ANALYZE = 2  # produce analysis, scores, scenarios
    PROPOSE = 3  # propose a strategy, a trade or a change - never execute it
    CONTROL = 4  # refuse proposals that break rules, bounded emergency stop


#: What L5 covers, stated so the registry can say who holds it.
HUMAN_ONLY_L5 = (
    "تغییر سیاست‌های ریسک",
    "فعال‌کردن معاملات واقعی (LIVE)",
    "دسترسی به سفارش‌گذاری واقعی",
    "تغییر دسترسی‌های امنیتی",
    "انتقال وجه و برداشت",
)


class ImplementationStatus(StrEnum):
    IMPLEMENTED = "IMPLEMENTED"
    PARTIAL = "PARTIAL"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


#: Applied to every role on top of its own restrictions.
COMMON_RESTRICTIONS = (
    "حق دورزدن یا لغو تصمیم Risk Brain را ندارد.",
    "حق ارسال سفارش LIVE ندارد؛ این مرحله فقط Paper است.",
    "به رمز، API Key یا اطلاعات حساب دسترسی ندارد و آن‌ها را ثبت نمی‌کند.",
    "در نبود داده معتبر باید WAIT یا ABSTAIN اعلام کند، نه حدس.",
)


@dataclass(frozen=True)
class AgentRole:
    id: str
    name_fa: str
    name_en: str
    group: AgentGroup
    responsibilities: tuple[str, ...]
    permission_level: PermissionLevel
    restrictions: tuple[str, ...]
    triggers: tuple[str, ...]
    #: Repository-relative paths of existing code that carries (part of) the
    #: role today. Empty when nothing does.
    modules: tuple[str, ...]
    status: ImplementationStatus
    notes: str = ""
    may_override_risk: bool = field(default=False)
    can_submit_orders: bool = field(default=False)

    def __post_init__(self) -> None:
        if self.may_override_risk:
            raise ValueError(f"{self.id}: no role may override the risk brain")
        if self.can_submit_orders:
            raise ValueError(
                f"{self.id}: the registry grants no order permission; orders pass "
                "through the risk brain and the execution gate, not through a role"
            )
        if not isinstance(self.permission_level, PermissionLevel):
            raise ValueError(f"{self.id}: permission level must be L1-L4")
        if self.status is ImplementationStatus.NOT_IMPLEMENTED and self.modules:
            raise ValueError(f"{self.id}: a NOT_IMPLEMENTED role cannot claim modules")
        if self.status is not ImplementationStatus.NOT_IMPLEMENTED and not self.modules:
            raise ValueError(f"{self.id}: an implemented or partial role must name its code")

    @property
    def all_restrictions(self) -> tuple[str, ...]:
        return COMMON_RESTRICTIONS + self.restrictions

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name_fa": self.name_fa,
            "name_en": self.name_en,
            "group": self.group.value,
            "responsibilities": list(self.responsibilities),
            "permission_level": f"L{int(self.permission_level)}",
            "permission_name": self.permission_level.name,
            "restrictions": list(self.all_restrictions),
            "triggers": list(self.triggers),
            "modules": list(self.modules),
            "status": self.status.value,
            "notes": self.notes,
            "may_override_risk": self.may_override_risk,
            "can_submit_orders": self.can_submit_orders,
        }
