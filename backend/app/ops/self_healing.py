"""Repair, under conditions strict enough to be worth having (spec §35-36).

A system that repairs itself is a system that can break itself, and the failure
mode is worse than the one it fixes: a restart loop that misread the cause
takes down a healthy service, and on a two-core host that is enough to take the
rest with it. So the design starts from what must be impossible rather than
from what would be convenient.

Four constraints, each one load-bearing.

**Only reversible actions.** Restarting a worker is reversible - the worst case
is a lost cycle. Deleting rows, rewriting config or killing a database is not,
and nothing here will ever do those. The catalogue is a fixed table, not a
capability: an action that is not in it cannot be taken by any caller.

**A budget per fingerprint.** Three attempts in an hour, then it stops trying
and says so. An unbounded healer facing a problem it cannot fix does not fail -
it loops, and the loop is indistinguishable from the outage until somebody
notices the same restart in the log four hundred times.

**Recorded before it acts.** The intent is written first, the action second.
Written afterwards, a crash mid-repair leaves no trace that anything was
attempted, and the next reader diagnoses a system that has been restarting
itself all night without knowing it.

**Verified after, or it did not work.** An action is credited only when the
signal that raised the incident actually clears. "The command exited zero" is
not repair; it is a command exiting zero.

Nothing here runs automatically yet. `plan` decides, `apply` executes when
called, and the caller is a person or a job that has to pass `confirm=True`.
Turning that into a timer is a separate decision with its own consequences, and
it belongs to whoever owns the machine.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.incidents import Incident
from app.ops import incidents as incident_memory

#: How many repair attempts one fingerprint gets before the healer stops and
#: hands it to a person. Three is enough for a transient fault and few enough
#: that a loop is visible rather than endemic.
MAX_ATTEMPTS_PER_WINDOW = 3
ATTEMPT_WINDOW = timedelta(hours=1)

#: How long to wait for the raising signal to clear before calling an action
#: unverified. Long enough for a container to come back, short enough that a
#: person is not left watching a spinner.
VERIFY_TIMEOUT = timedelta(minutes=5)


@dataclass(frozen=True)
class Action:
    """One repair this system is permitted to attempt.

    `reversible` is not a field anybody sets to False - it is here so the
    catalogue reads as a claim that can be checked, and a test asserts every
    entry is True. An irreversible action does not belong in a table that
    something else decides when to run.
    """

    name: str
    description: str
    #: Why this is safe to do without asking. The sentence is the review: an
    #: action whose justification cannot be written in one line has not been
    #: thought about enough to run unattended.
    why_safe: str
    reversible: bool = True


#: The whole catalogue. Adding to it is a deliberate act with a code review
#: attached, which is the point - a healer that can learn new actions at
#: runtime is a healer nobody can reason about.
CATALOGUE: dict[str, Action] = {
    "restart_collector": Action(
        name="restart_collector",
        description="restart the collector worker",
        why_safe=(
            "the worker is stateless between cycles and resumes from a stored "
            "checkpoint, so the worst case is one lost cycle of bars that the "
            "next run re-fetches"
        ),
    ),
    "restart_terminal": Action(
        name="restart_terminal",
        description="restart the MetaTrader terminal",
        why_safe=(
            "the terminal holds no state this system depends on - its account, "
            "config and expert are all on disk and reload on start. It places "
            "no orders, so a restart cannot interrupt one"
        ),
    ),
    "prune_build_cache": Action(
        name="prune_build_cache",
        description="reclaim the docker build cache",
        why_safe=(
            "build cache is derived data. Removing it costs the next deploy "
            "some rebuild time and nothing else, and it is the single largest "
            "reclaimable thing on this host"
        ),
    ),
}


@dataclass
class Plan:
    """What the healer would do, and why it would or would not."""

    fingerprint: str
    action: Action | None
    allowed: bool
    reason: str
    attempts_in_window: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "action": self.action.name if self.action else None,
            "description": self.action.description if self.action else None,
            "why_safe": self.action.why_safe if self.action else None,
            "allowed": self.allowed,
            "reason": self.reason,
            "attempts_in_window": self.attempts_in_window,
            "budget": MAX_ATTEMPTS_PER_WINDOW,
        }


#: Which incident sources map to which repair. Deliberately narrow: a source
#: with no entry gets no automatic action, which is the correct default for
#: anything nobody has thought about.
ROUTES: dict[str, str] = {
    "collector": "restart_collector",
    "metatrader": "restart_terminal",
    "disk": "prune_build_cache",
}


def _attempts_in_window(incident: Incident, now: datetime) -> int:
    """How many times this has been attempted recently.

    Read from the incident's own details rather than a separate table: the
    budget has to survive a restart, and a counter in memory resets on exactly
    the event most likely to be part of the loop.
    """
    history = (incident.details or {}).get("repair_attempts", [])
    cutoff = now - ATTEMPT_WINDOW
    recent = 0
    for stamp in history:
        try:
            when = datetime.fromisoformat(stamp)
        except (TypeError, ValueError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        if when >= cutoff:
            recent += 1
    return recent


def plan(session: Session, fingerprint: str, *, now: datetime | None = None) -> Plan:
    """Decide what to do about one incident, without doing it.

    Separate from `apply` on purpose. A caller can ask what would happen, a
    person can read it, and a test can assert the decision without a container
    being restarted to find out.
    """
    moment = now or datetime.now(UTC)
    incident = session.scalar(select(Incident).where(Incident.fingerprint == fingerprint))
    if incident is None:
        return Plan(fingerprint, None, False, "no incident with that fingerprint")

    if incident.resolved_at is not None:
        return Plan(fingerprint, None, False, "the incident is already resolved")

    action_name = ROUTES.get(incident.source)
    if action_name is None:
        return Plan(
            fingerprint,
            None,
            False,
            f"no repair is defined for source {incident.source!r}, which is the "
            "correct default for anything nobody has thought about",
        )

    action = CATALOGUE[action_name]
    attempts = _attempts_in_window(incident, moment)
    if attempts >= MAX_ATTEMPTS_PER_WINDOW:
        return Plan(
            fingerprint,
            action,
            False,
            f"budget spent: {attempts} attempt(s) in the last "
            f"{ATTEMPT_WINDOW.total_seconds() / 3600:.0f}h. An unbounded healer "
            "facing something it cannot fix loops instead of failing",
            attempts,
        )

    return Plan(fingerprint, action, True, "within budget and reversible", attempts)


def apply(
    session: Session,
    fingerprint: str,
    runner: Callable[[Action], tuple[bool, str]],
    *,
    confirm: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Attempt the planned repair.

    `confirm` must be passed explicitly. A healer that acts because it was
    imported is a healer nobody chose to run, and the default here is the one
    that does nothing.

    `runner` is supplied by the caller rather than built in, so this module
    never holds the ability to execute anything on its own. Tests pass a
    function that records; production passes one that shells out. Nothing about
    the decision changes between them.
    """
    moment = now or datetime.now(UTC)
    decision = plan(session, fingerprint, now=moment)

    if not confirm:
        return {
            "attempted": False,
            "reason": "confirm=True is required; nothing acts by default",
            "plan": decision.as_dict(),
        }
    if not decision.allowed or decision.action is None:
        return {"attempted": False, "reason": decision.reason, "plan": decision.as_dict()}

    incident = session.scalar(select(Incident).where(Incident.fingerprint == fingerprint))
    if incident is None:
        return {"attempted": False, "reason": "the incident vanished", "plan": decision.as_dict()}

    # Written before the action, not after. A crash mid-repair must leave a
    # trace that something was attempted, or the next reader diagnoses a system
    # that has been restarting itself all night without knowing it.
    history = list((incident.details or {}).get("repair_attempts", []))
    history.append(moment.isoformat())
    incident.details = {**(incident.details or {}), "repair_attempts": history}
    incident_memory.record_remedy(
        session, fingerprint, f"attempted: {decision.action.description}"
    )
    session.flush()

    succeeded, detail = runner(decision.action)

    return {
        "attempted": True,
        "action": decision.action.name,
        "command_succeeded": succeeded,
        "detail": detail,
        # The command exiting zero is not repair. The remedy stays unconfirmed
        # until the signal that raised the incident actually clears, which is
        # `incident_memory.clear` on a later pass.
        "verified": False,
        "verification": (
            "unverified until the raising signal clears on its own. A command "
            "that exited zero has exited zero, which is a different claim from "
            "having fixed anything"
        ),
        "plan": decision.as_dict(),
    }
