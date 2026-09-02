"""One decision about whether an order may go, with every reason it may not.

Three states used to be read as one. "The engine is on" was taken to mean
orders were flowing; "the kill switch is engaged" was taken to mean the engine
was off; a readiness failure was answered by proposing to stop the engine. They
are three different facts about three different things:

    ENGINE_STATE              is the process running and evaluating?
    KILL_SWITCH_STATE         has a human released the halt?
    ORDER_AUTHORIZATION_STATE may *this* order go, right now?

The engine runs whether or not orders are authorised. It keeps collecting,
deciding, measuring and recording the control - that is how the evidence the
other two states are judged on gets produced. Blocking orders never stops it,
and nothing in this module can stop it: there is no field here that turns the
engine off, by construction.

Authorisation is recomputed from live facts on every call. Nothing is
remembered between calls, so a blocker that clears - disk freed, feed back,
switch released - clears the next time anybody asks, without a restart and
without anything to reset. And a blocker that returns, returns the same way.
That is the whole of "automatic recovery": no state to recover.

Every refusal is a named reason in a list, never a boolean. A reader who sees
`order_authorized: false` and nothing else has learned that something is
wrong and nothing about what.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class EngineState(StrEnum):
    RUNNING = "running"
    STOPPED = "stopped"


class KillSwitchState(StrEnum):
    ENGAGED = "engaged"
    RELEASED = "released"


class OrderAuthorizationState(StrEnum):
    AUTHORIZED = "authorized"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class Gate:
    """One condition an order needs, with what was observed."""

    name: str
    passed: bool
    reason: str
    #: Mandatory gates block; advisory ones are reported and do not.
    mandatory: bool = True
    observed: Any = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "mandatory": self.mandatory,
            "reason": self.reason,
            "observed": self.observed,
        }


@dataclass(frozen=True)
class Facts:
    """What the decision is made from. Every field is a live observation.

    `None` anywhere means "not observed", and a gate that cannot observe its
    fact fails: not knowing whether the disk is full is not evidence that it
    is not.
    """

    engine_running: bool | None
    kill_switch_engaged: bool | None
    kill_switch_reason: str = ""
    #: Names of readiness checks graded BLOCKING that did not pass.
    readiness_blocking_failures: list[str] | None = None
    #: Names of readiness checks graded IMPORTANT that did not pass. Reported;
    #: only the ones listed in `IMPORTANT_THAT_BLOCK` stop an order.
    readiness_important_failures: list[str] | None = None
    data_age_bars: float | None = None
    max_data_age_bars: float = 3.0
    account_available: bool | None = None
    account_reason: str = ""
    proven_edge: bool | None = None
    proven_edge_reason: str = ""
    #: `MOLIDO_TRADE_WITHOUT_PROVEN_EDGE`. Reported by name on every decision
    #: it affects, so the override cannot be forgotten.
    trade_without_proven_edge: bool = False
    risk_approved: bool | None = None
    risk_reason: str = ""
    execution_mode: str | None = None
    execution_mode_consistent: bool | None = None


#: Readiness checks graded IMPORTANT whose failure still blocks an order.
#: `readiness` grades the whole deployment; these are the ones about *this
#: order's* inputs. A stale feed or a full disk is not "will hurt later", it
#: is "the next order is sized on data that is not there".
IMPORTANT_THAT_BLOCK = frozenset({"data_is_fresh", "disk_headroom", "audit_chain_intact"})


@dataclass
class Decision:
    evaluated_at: datetime
    engine: EngineState
    kill_switch: KillSwitchState
    authorization: OrderAuthorizationState
    gates: list[Gate] = field(default_factory=list)

    @property
    def order_authorized(self) -> bool:
        return self.authorization is OrderAuthorizationState.AUTHORIZED

    @property
    def blocking_reasons(self) -> list[str]:
        return [f"{g.name}: {g.reason}" for g in self.gates if g.mandatory and not g.passed]

    @property
    def advisories(self) -> list[str]:
        return [f"{g.name}: {g.reason}" for g in self.gates if not g.mandatory and not g.passed]

    def gate(self, name: str) -> Gate | None:
        return next((g for g in self.gates if g.name == name), None)

    def as_dict(self) -> dict[str, Any]:
        def passed(name: str) -> bool | None:
            gate = self.gate(name)
            return None if gate is None else gate.passed

        return {
            "evaluated_at": self.evaluated_at.isoformat(),
            "engine_state": self.engine.value,
            "kill_switch_state": self.kill_switch.value,
            "order_authorization_state": self.authorization.value,
            # The conceptual shape, spelled out, so a dashboard can bind to
            # names rather than to positions in a list.
            "engine_running": self.engine is EngineState.RUNNING,
            "kill_switch_released": self.kill_switch is KillSwitchState.RELEASED,
            "operational_ready": passed("operational_readiness"),
            "data_fresh": passed("data_fresh"),
            "account_ready": passed("account_known"),
            "proven_edge": passed("proven_edge"),
            "risk_approved": passed("risk_approved"),
            "order_authorized": self.order_authorized,
            "blocking_reasons": self.blocking_reasons,
            "advisories": self.advisories,
            "gates": [g.as_dict() for g in self.gates],
            "note": (
                "engine running is not order authorized; the engine keeps "
                "evaluating while every reason above stands"
            ),
        }


def decide(facts: Facts, *, now: datetime | None = None) -> Decision:
    """Every gate, every time, from facts alone. Nothing is inferred from
    the engine being on, and nothing is remembered from last time."""
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    gates: list[Gate] = []

    engine = EngineState.RUNNING if facts.engine_running else EngineState.STOPPED
    gates.append(
        Gate(
            "engine_running",
            facts.engine_running is True,
            "the engine is running" if facts.engine_running else "the engine is not running",
            observed=facts.engine_running,
        )
    )

    if facts.kill_switch_engaged is None:
        switch = KillSwitchState.ENGAGED
        gates.append(
            Gate(
                "kill_switch_released",
                False,
                "the kill switch could not be read, and an unreadable switch halts",
                observed=None,
            )
        )
    else:
        switch = KillSwitchState.ENGAGED if facts.kill_switch_engaged else KillSwitchState.RELEASED
        gates.append(
            Gate(
                "kill_switch_released",
                not facts.kill_switch_engaged,
                (
                    f"the kill switch is engaged: {facts.kill_switch_reason}"
                    if facts.kill_switch_engaged
                    else f"released ({facts.kill_switch_reason})"
                ),
                observed=switch.value,
            )
        )

    blocking = facts.readiness_blocking_failures
    important = facts.readiness_important_failures
    if blocking is None or important is None:
        gates.append(
            Gate(
                "operational_readiness",
                False,
                "readiness was not assessed, which is not the same as ready",
                observed=None,
            )
        )
    else:
        hard = list(blocking) + [n for n in important if n in IMPORTANT_THAT_BLOCK]
        soft = [n for n in important if n not in IMPORTANT_THAT_BLOCK]
        gates.append(
            Gate(
                "operational_readiness",
                not hard,
                (
                    "every blocking readiness check passes"
                    if not hard
                    else "readiness checks failing: " + ", ".join(hard)
                ),
                observed={"blocking": list(blocking), "important": list(important)},
            )
        )
        if soft:
            gates.append(
                Gate(
                    "operational_readiness_advisory",
                    False,
                    "important checks failing without blocking this order: " + ", ".join(soft),
                    mandatory=False,
                    observed=soft,
                )
            )

    if facts.data_age_bars is None:
        gates.append(
            Gate("data_fresh", False, "the age of the data is unknown, and unknown is stale", observed=None)
        )
    else:
        fresh = facts.data_age_bars <= facts.max_data_age_bars
        gates.append(
            Gate(
                "data_fresh",
                fresh,
                (
                    f"data is {facts.data_age_bars:.2f} bars old"
                    if fresh
                    else f"data is {facts.data_age_bars:.2f} bars old, beyond the "
                    f"{facts.max_data_age_bars:.0f}-bar limit"
                ),
                observed=facts.data_age_bars,
            )
        )

    # Unobserved is not refused, and the difference matters to whoever reads
    # this. Only the trading cycle holds a terminal's publication and the risk
    # brain's verdict; the API route leaves both None, and a report that said
    # "the bridge cannot describe the account" from a process that never asked
    # a bridge would be inventing a diagnosis. Both still block - an order may
    # not go on a fact nobody checked - but they say which of the two it is.
    if facts.account_available is None:
        gates.append(
            Gate(
                "account_known",
                False,
                "not observed here: only the trading cycle reads a terminal's account",
                observed=None,
            )
        )
    else:
        gates.append(
            Gate(
                "account_known",
                facts.account_available,
                (
                    facts.account_reason or "the terminal describes the account"
                    if facts.account_available
                    else facts.account_reason
                    or "the bridge cannot describe the account, so it is treated as real money and refused"
                ),
                observed=facts.account_available,
            )
        )

    if facts.proven_edge:
        gates.append(
            Gate("proven_edge", True, facts.proven_edge_reason or "a registered edge clears the bar", observed=True)
        )
    elif facts.trade_without_proven_edge:
        # Permitted, and said in full on every decision it touches. The
        # override is a deliberate bet that the measurement is wrong, and a
        # bet that is not restated is a bet that gets forgotten.
        gates.append(
            Gate(
                "proven_edge",
                True,
                "no registered edge clears the bar; trading under "
                "MOLIDO_TRADE_WITHOUT_PROVEN_EDGE, a deliberate override - "
                + (facts.proven_edge_reason or ""),
                observed={"proven": False, "override": True},
            )
        )
    else:
        gates.append(
            Gate(
                "proven_edge",
                False,
                facts.proven_edge_reason or "no registered edge clears the bar",
                observed={"proven": False, "override": False},
            )
        )

    if facts.risk_approved is None:
        gates.append(
            Gate(
                "risk_approved",
                False,
                "not observed here: the risk brain is asked once per cycle, against an account",
                observed=None,
            )
        )
    else:
        gates.append(
            Gate(
                "risk_approved",
                facts.risk_approved,
                facts.risk_reason
                or ("the risk brain approves" if facts.risk_approved else "the risk brain has not approved"),
                observed=facts.risk_approved,
            )
        )

    if facts.execution_mode is not None:
        gates.append(
            Gate(
                "execution_mode_consistent",
                facts.execution_mode_consistent is True,
                (
                    f"mode {facts.execution_mode}"
                    if facts.execution_mode_consistent
                    else f"mode {facts.execution_mode}: simulated fills would not be labelled"
                ),
                observed=facts.execution_mode,
            )
        )

    authorised = all(g.passed for g in gates if g.mandatory)
    return Decision(
        evaluated_at=moment,
        engine=engine,
        kill_switch=switch,
        authorization=(
            OrderAuthorizationState.AUTHORIZED if authorised else OrderAuthorizationState.BLOCKED
        ),
        gates=gates,
    )


__all__ = [
    "Decision",
    "EngineState",
    "Facts",
    "Gate",
    "IMPORTANT_THAT_BLOCK",
    "KillSwitchState",
    "OrderAuthorizationState",
    "decide",
]
