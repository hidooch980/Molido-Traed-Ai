"""Circuit breaker: after N consecutive failures, stop calling for a while."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class CircuitBreaker:
    threshold: int = 5
    cooldown: float = 60.0
    clock: Callable[[], float] = field(default=time.monotonic)
    failures: int = 0
    opened_at: float | None = None
    _trial: bool = False

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        if self.clock() - self.opened_at >= self.cooldown:
            return "half_open"
        return "open"

    def allow(self) -> bool:
        state = self.state
        if state == "closed":
            return True
        if state == "half_open" and not self._trial:
            self._trial = True  # exactly one probe
            return True
        return False

    def success(self) -> None:
        self.failures, self.opened_at, self._trial = 0, None, False

    def failure(self) -> None:
        self.failures += 1
        self._trial = False
        if self.failures >= self.threshold or self.opened_at is not None:
            self.opened_at = self.clock()
