"""How a trade is managed after entry, as something that can be measured.

`geometry` asks where the stop and the target should be when the trade opens.
It cannot ask the question the owner asked on 14 September - should the stop
move sooner, move to entry, or should a trade that goes nowhere be closed -
because `resolve._outcome` only knows two fixed levels. This walks the same
bars under a management policy, so the policies can be swept with the same
discipline `geometry` already has: chosen on a training window, reported on a
window it never saw, against a coin flip managed by the same policy.

The rules are `_outcome`'s, deliberately:

  * **Strictly after the entry bar.** The caller passes only the bars after it.
  * **A bar that touches both levels is dropped, not guessed.** Which came
    first inside one bar is unknowable at this resolution.
  * **The stop only moves toward the price.** A management rule that could
    widen a stop is one that could turn a bounded loss into an unbounded one.
  * **A move is decided on a bar and takes effect from the next one.** The
    bar that set a new best price cannot also be the bar that fills the new
    stop, because inside it nobody knows the order of the high and the low.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExitPolicy:
    """One way of managing an open trade. `NONE` is today's fixed geometry.

    `trail_start_r`   best excursion, in R, before the stop starts to follow
    `trail_lag_r`     how far behind the best price the stop follows, in R
    `breakeven_at_r`  best excursion, in R, at which the stop moves to entry
    `max_bars`        bars after which an unresolved trade closes at the close
    """

    trail_start_r: float | None = None
    trail_lag_r: float = 0.6
    breakeven_at_r: float | None = None
    max_bars: int | None = None

    @property
    def label(self) -> str:
        parts = []
        if self.trail_start_r is not None:
            parts.append(f"trail@{self.trail_start_r:g}R-lag{self.trail_lag_r:g}")
        if self.breakeven_at_r is not None:
            parts.append(f"be@{self.breakeven_at_r:g}R")
        if self.max_bars is not None:
            parts.append(f"exit@{self.max_bars}bars")
        return "+".join(parts) or "fixed"

    def as_payload(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "trail_start_r": self.trail_start_r,
            "trail_lag_r": self.trail_lag_r,
            "breakeven_at_r": self.breakeven_at_r,
            "max_bars": self.max_bars,
        }


NONE = ExitPolicy()

#: What production runs today: trail from +1 R, 0.6 R behind (workers/trailing).
DEPLOYED = ExitPolicy(trail_start_r=1.0, trail_lag_r=0.6)

#: The grid a sweep tries. The fixed geometry and the deployed trail are both
#: in it, so a winner is always read against what is already running.
POLICIES: tuple[ExitPolicy, ...] = (
    NONE,
    DEPLOYED,
    ExitPolicy(trail_start_r=0.5, trail_lag_r=0.6),
    ExitPolicy(trail_start_r=0.7, trail_lag_r=0.5),
    ExitPolicy(trail_start_r=1.0, trail_lag_r=0.4),
    ExitPolicy(breakeven_at_r=0.5),
    ExitPolicy(breakeven_at_r=0.7),
    ExitPolicy(breakeven_at_r=0.5, trail_start_r=1.0, trail_lag_r=0.6),
    ExitPolicy(max_bars=48),
    ExitPolicy(trail_start_r=1.0, trail_lag_r=0.6, max_bars=72),
)


def walk(
    bars: Sequence[Any],
    *,
    side: int,
    entry: float,
    stop: float,
    target: float,
    policy: ExitPolicy = NONE,
    horizon: int | None = None,
) -> float | None:
    """The trade's result in R under `policy`, or None if it produced no evidence.

    `bars` are the bars strictly after the entry bar, each with `high`, `low`
    and `close`. None covers the same cases `_outcome` returns None for: not
    enough bars yet, and a bar that touched both levels.
    """
    risk = abs(entry - stop)
    if risk <= 0 or side not in (1, -1):
        return None
    reward = abs(target - entry) / risk
    current = stop
    best = 0.0  # best excursion in price, never negative

    window = list(bars if horizon is None else bars[:horizon])
    for count, bar in enumerate(window, start=1):
        high, low, close = float(bar.high), float(bar.low), float(bar.close)
        if side > 0:
            hit_stop, hit_target = low <= current, high >= target
        else:
            hit_stop, hit_target = high >= current, low <= target

        if hit_stop and hit_target:
            return None
        if hit_stop:
            return round((current - entry) * side / risk, 6)
        if hit_target:
            return reward

        if policy.max_bars is not None and count >= policy.max_bars:
            return round((close - entry) * side / risk, 6)

        # Decided on this bar, in force from the next one.
        best = max(best, (high - entry) if side > 0 else (entry - low))
        candidate = current
        if policy.breakeven_at_r is not None and best >= policy.breakeven_at_r * risk:
            candidate = entry
        if policy.trail_start_r is not None and best >= policy.trail_start_r * risk:
            trailed = entry + (best - policy.trail_lag_r * risk) * side
            candidate = max(candidate, trailed) if side > 0 else min(candidate, trailed)
        current = max(current, candidate) if side > 0 else min(current, candidate)

    return None


__all__ = ["DEPLOYED", "ExitPolicy", "NONE", "POLICIES", "walk"]
