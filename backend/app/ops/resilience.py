"""Stability and crash recovery (spec phases 35-36, §37-38).

A trading system does not get to choose between running and not running. It
runs in a degraded state, and the only question is whether it knows that.

The degradation ladder here is the answer. Each rung names what stopped
working, what is still safe to do on that rung, and — the part that matters —
what must stop. A system that responds to a broken feed by continuing to answer
is more dangerous than one that has crashed, because a crash is visible.

**FULL** — everything works.
**DEGRADED** — something non-essential is broken. Read, analyse, but no new
risk sized on the broken input.
**READ_ONLY** — the system can still describe the world and must not act on it.
**HALTED** — nothing.

Two rules hold the ladder together:

**Descent is automatic; ascent is not.** Any failing check drops the level
immediately. Climbing back requires the check to pass *and* a settling period,
because a dependency that has failed once inside a minute is a dependency that
is failing, and a circuit that closes on the first success oscillates.

**The level is the floor, not the ceiling.** Nothing above this module can
decide it is at a higher level than the checks support, and `permits` is the
only way to ask.

Crash recovery below answers the other half: after an unclean stop, what does
the process not know? It enumerates the questions rather than answering them,
because the answers live at the broker and in the database, and a recovery that
guesses is how a restart doubles a position.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import IntEnum
from typing import Any

# How long a dependency must stay healthy before the level may climb. Sixty
# seconds is not a network figure - it is long enough that a flapping
# dependency completes at least one more failure cycle inside it.
RECOVERY_SETTLE = timedelta(seconds=60)

# Consecutive failures before a circuit opens. One failure is an event; three
# in a row is a state.
CIRCUIT_FAILURE_THRESHOLD = 3


class Level(IntEnum):
    """Ordered so comparisons read the way the ladder does.

    IntEnum rather than StrEnum precisely because `level >= Level.READ_ONLY` is
    the question every caller asks, and a string enum would make that a lookup
    table somewhere else that can disagree with this one.
    """

    HALTED = 0
    READ_ONLY = 1
    DEGRADED = 2
    FULL = 3

    @property
    def label(self) -> str:
        return self.name.lower()


# What each rung permits. Absent from every rung below FULL: opening new risk
# on an input that is not working.
_PERMISSIONS: dict[Level, frozenset[str]] = {
    Level.FULL: frozenset({"read", "analyse", "simulate", "execute"}),
    Level.DEGRADED: frozenset({"read", "analyse", "simulate"}),
    Level.READ_ONLY: frozenset({"read"}),
    Level.HALTED: frozenset(),
}


@dataclass
class Dependency:
    """One thing that can fail, and what its failure costs.

    `floor` is the highest level the system may sit at while this dependency is
    down. A database outage floors the system at HALTED; a stale news feed
    floors it at DEGRADED. Writing the cost next to the dependency is what
    stops the ladder becoming a single boolean.
    """

    name: str
    floor: Level
    healthy: bool = True
    detail: str | None = None
    consecutive_failures: int = 0
    healthy_since: datetime | None = None

    @property
    def circuit_open(self) -> bool:
        return self.consecutive_failures >= CIRCUIT_FAILURE_THRESHOLD

    def record(self, healthy: bool, *, detail: str | None = None, now: datetime) -> None:
        if healthy:
            if not self.healthy:
                # Reset the clock, not the level: the settle window starts now,
                # and the level does not climb until it has elapsed.
                self.healthy_since = now
            elif self.healthy_since is None:
                self.healthy_since = now
            self.consecutive_failures = 0
        else:
            self.consecutive_failures += 1
            self.healthy_since = None
        self.healthy = healthy
        self.detail = detail

    def settled(self, now: datetime, *, settle: timedelta = RECOVERY_SETTLE) -> bool:
        if not self.healthy or self.healthy_since is None:
            return False
        return now - self.healthy_since >= settle

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "healthy": self.healthy,
            "floor_when_down": self.floor.label,
            "consecutive_failures": self.consecutive_failures,
            "circuit_open": self.circuit_open,
            "healthy_since": self.healthy_since.isoformat() if self.healthy_since else None,
            "detail": self.detail,
        }


@dataclass
class StabilityReport:
    level: Level
    reasons: list[str] = field(default_factory=list)
    holding_back: list[str] = field(default_factory=list)
    dependencies: list[dict[str, Any]] = field(default_factory=list)

    def permits(self, action: str) -> bool:
        return action in _PERMISSIONS[self.level]

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.label,
            "permits": sorted(_PERMISSIONS[self.level]),
            "reasons": self.reasons,
            "holding_back": self.holding_back,
            "dependencies": self.dependencies,
        }


class StabilityMonitor:
    """Holds the dependencies and computes the level from them.

    The level is never stored. Computing it on every read means there is no
    cached answer to go stale, and no path where a dependency fails and the
    level is simply not recomputed.
    """

    def __init__(self, dependencies: list[Dependency]) -> None:
        if not dependencies:
            raise ValueError("a monitor with no dependencies monitors nothing")
        self._dependencies = {d.name: d for d in dependencies}

    def record(
        self, name: str, healthy: bool, *, detail: str | None = None, now: datetime | None = None
    ) -> None:
        dependency = self._dependencies.get(name)
        if dependency is None:
            raise KeyError(f"unknown dependency {name!r}")
        dependency.record(healthy, detail=detail, now=now or datetime.now(UTC))

    def report(
        self, now: datetime | None = None, *, settle: timedelta = RECOVERY_SETTLE
    ) -> StabilityReport:
        moment = now or datetime.now(UTC)
        level = Level.FULL
        reasons: list[str] = []
        holding_back: list[str] = []

        for dependency in self._dependencies.values():
            if not dependency.healthy:
                if dependency.floor < level:
                    level = dependency.floor
                reasons.append(
                    f"{dependency.name} is down"
                    + (f": {dependency.detail}" if dependency.detail else "")
                    + f" — floors the system at {dependency.floor.label}"
                )
            elif not dependency.settled(moment, settle=settle):
                # Healthy but not yet trusted. The system does not climb on the
                # first success, because a dependency that failed a moment ago
                # is a dependency that is failing.
                if dependency.floor < level:
                    level = dependency.floor
                holding_back.append(
                    f"{dependency.name} recovered but has not settled for "
                    f"{settle.total_seconds():.0f}s"
                )

        return StabilityReport(
            level=level,
            reasons=reasons,
            holding_back=holding_back,
            dependencies=[d.as_dict() for d in self._dependencies.values()],
        )


# ---------------------------------------------------------------- recovery


@dataclass
class OpenQuestion:
    """Something the process does not know after an unclean stop.

    `resolvable_by` names where the answer lives, because the whole point is
    that this module does not invent it. A recovery routine that guesses is how
    a restart doubles a position.
    """

    topic: str
    question: str
    resolvable_by: str
    blocking: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "question": self.question,
            "resolvable_by": self.resolvable_by,
            "blocking": self.blocking,
        }


@dataclass
class RecoveryPlan:
    clean_shutdown: bool
    questions: list[OpenQuestion] = field(default_factory=list)
    permitted_level: Level = Level.HALTED

    @property
    def may_resume(self) -> bool:
        return not any(q.blocking for q in self.questions)

    def as_dict(self) -> dict[str, Any]:
        return {
            "clean_shutdown": self.clean_shutdown,
            "may_resume": self.may_resume,
            "permitted_level": self.permitted_level.label,
            "questions": [q.as_dict() for q in self.questions],
            "note": "this plan enumerates what is unknown; it answers nothing",
        }


def plan_recovery(
    *,
    clean_shutdown: bool,
    unresolved_orders: list[str],
    open_positions_believed: int,
    positions_reconciled: bool,
    last_checkpoint: datetime | None,
    now: datetime | None = None,
    max_checkpoint_age: timedelta = timedelta(minutes=15),
) -> RecoveryPlan:
    """Enumerate what a restarting process cannot know yet.

    A clean shutdown answers most of it. An unclean one answers none of it, and
    the difference between the two is not a matter of degree: after a kill the
    process has no grounds to believe any of its last-known state.
    """
    moment = now or datetime.now(UTC)
    plan = RecoveryPlan(clean_shutdown=clean_shutdown)

    if not clean_shutdown:
        plan.questions.append(
            OpenQuestion(
                topic="shutdown",
                question=(
                    "the process stopped without shutting down — nothing in its "
                    "last-known state is evidence about the account"
                ),
                resolvable_by="reconcile against the broker",
            )
        )

    for order_id in unresolved_orders:
        plan.questions.append(
            OpenQuestion(
                topic="order",
                question=f"{order_id} was never resolved; it may be live",
                resolvable_by="ask the broker for this client order id",
            )
        )

    if open_positions_believed > 0 and not positions_reconciled:
        plan.questions.append(
            OpenQuestion(
                topic="positions",
                question=(
                    f"{open_positions_believed} positions are believed open and have "
                    "not been confirmed against the broker"
                ),
                resolvable_by="reconcile against the broker",
            )
        )

    if last_checkpoint is None:
        plan.questions.append(
            OpenQuestion(
                topic="checkpoint",
                question="no checkpoint exists, so there is no state to resume from",
                resolvable_by="rebuild from the database",
            )
        )
    elif moment - last_checkpoint > max_checkpoint_age:
        age = (moment - last_checkpoint).total_seconds() / 60
        plan.questions.append(
            OpenQuestion(
                topic="checkpoint",
                question=f"the last checkpoint is {age:.0f} minutes old",
                resolvable_by="rebuild from the database",
                # Not blocking: a stale checkpoint costs work, not correctness,
                # because the database is authoritative and can be re-read.
                blocking=False,
            )
        )

    # Reading is always safe, so a process with open questions comes back able
    # to describe the world and unable to act on it. Halting entirely would
    # remove the one view an operator needs in order to resolve the questions.
    plan.permitted_level = Level.FULL if plan.may_resume else Level.READ_ONLY
    return plan
