"""Daily token and cost budget, and the mode it puts the gateway in.

NORMAL    - every priority runs.
ECONOMY   - at `economy_at` of either limit: LOW and NORMAL work stops, DEEP
            requests drop to the STANDARD model.
EMERGENCY - a limit is reached: no model calls at all. Agents abstain and the
            council produces WAIT. Risk, safety and journaling never depended
            on the gateway, so they are untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum

from app.agents.gateway.config import Complexity, Priority


class BudgetMode(StrEnum):
    NORMAL = "NORMAL"
    ECONOMY = "ECONOMY"
    EMERGENCY = "EMERGENCY"


def _today() -> date:
    return datetime.now(UTC).date()


@dataclass
class Budget:
    daily_token_limit: int
    daily_usd_limit: float | None = None
    economy_at: float = 0.7
    today: object = field(default=_today)
    tokens: int = 0
    usd: float = 0.0
    _day: date | None = None

    def _roll(self) -> None:
        day = self.today()  # type: ignore[operator]
        if day != self._day:
            self._day, self.tokens, self.usd = day, 0, 0.0

    def seed(self, tokens: int, usd: float) -> None:
        """Start from what the ledger says today already spent."""
        self._roll()
        self.tokens, self.usd = max(0, tokens), max(0.0, usd)

    def charge(self, tokens: int, usd: float | None) -> None:
        self._roll()
        self.tokens += max(0, tokens)
        if usd:
            self.usd += usd

    def fraction(self) -> float:
        self._roll()
        parts = []
        if self.daily_token_limit > 0:
            parts.append(self.tokens / self.daily_token_limit)
        else:
            parts.append(1.0)  # a zero limit means no model calls
        if self.daily_usd_limit is not None:
            parts.append(self.usd / self.daily_usd_limit if self.daily_usd_limit > 0 else 1.0)
        return max(parts)

    def mode(self) -> BudgetMode:
        used = self.fraction()
        if used >= 1.0:
            return BudgetMode.EMERGENCY
        if used >= self.economy_at:
            return BudgetMode.ECONOMY
        return BudgetMode.NORMAL

    def allows(self, priority: Priority) -> bool:
        mode = self.mode()
        if mode is BudgetMode.EMERGENCY:
            return False
        if mode is BudgetMode.ECONOMY:
            return priority <= Priority.HIGH
        return True

    def complexity(self, wanted: Complexity) -> Complexity:
        if self.mode() is BudgetMode.ECONOMY and wanted is Complexity.DEEP:
            return Complexity.STANDARD
        return wanted

    def snapshot(self) -> dict[str, object]:
        return {
            "mode": self.mode().value,
            "tokens_today": self.tokens,
            "usd_today": round(self.usd, 6) if self.usd else 0.0,
            "daily_token_limit": self.daily_token_limit,
            "daily_usd_limit": self.daily_usd_limit,
            "used_fraction": round(self.fraction(), 4),
        }
