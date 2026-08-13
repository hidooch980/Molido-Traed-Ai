"""The pre-execution checklist (spec phase 25, §22).

Everything upstream of here can be wrong and cost nothing. This is the last
place a mistake is still free, so the checklist is written to fail closed at
every step rather than to be convenient.

Four properties, in the order they matter:

**Every default is the safe one.** The kill switch starts engaged. Execution is
disabled. Dry-run is on. None of these are flags that turn safety *on*; they
are flags that a human has to deliberately turn off, one at a time, and the
absence of any of them is not an oversight that quietly permits trading.

**Approval must come from four different layers.** Risk, portfolio, challenge
and stress each answer a different question, and the checklist requires all
four by name. A caller cannot satisfy it with four sign-offs from the layer
that happened to be enthusiastic, and it cannot satisfy it by omitting one:
a missing approval is a block, never a pass.

**Approvals go stale.** A risk decision is a statement about an account state,
and the account moves. Evidence older than a few seconds is refused, because
the alternative is an order sized against an account that no longer exists.

**"We do not know" is not "it did not happen".** A submission that timed out
may have filled. The idempotency check treats a previously-seen intent as
already live rather than retrying it into a second position, and resolving it
means asking the broker, not assuming.

Nothing in this module places an order. It decides whether one may be placed,
and `execute` in `engine.py` cannot proceed without its answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.execution.contracts import OrderIntent

# The four layers that must each have said yes, by name. Adding a fifth means
# editing this tuple, which is a visible change in a diff; satisfying the
# checklist by accident is not possible.
REQUIRED_APPROVALS: tuple[str, ...] = ("risk", "portfolio", "challenge", "stress")

# How old the evidence may be. Five seconds is not a network budget - it is how
# long an account state stays true enough to size against during a session
# where price is moving.
MAX_AUTHORISATION_AGE_SECONDS = 5.0

# An authorisation stamped in the future is a clock problem, and a clock
# problem in this layer is indistinguishable from a replayed approval.
MAX_AUTHORISATION_SKEW_SECONDS = 1.0


@dataclass
class KillSwitch:
    """One switch, engaged by default, that no automated path may disengage.

    The default matters more than the mechanism. A kill switch that starts
    disengaged protects nothing until somebody remembers it exists, and the
    moment you need one is exactly the moment nobody is remembering anything.
    """

    engaged: bool = True
    reason: str = "the kill switch has not been deliberately disengaged"
    engaged_at: datetime | None = None
    engaged_by: str | None = None

    def engage(self, reason: str, *, by: str = "system") -> None:
        self.engaged = True
        self.reason = reason
        self.engaged_at = datetime.now(UTC)
        self.engaged_by = by

    def disengage(self, *, by: str) -> None:
        """Disengage. `by` is required and recorded: this is a human act.

        There is deliberately no automated caller for this anywhere in the
        codebase. A system that can re-arm itself after halting has a halt that
        means nothing.
        """
        if not by.strip():
            raise ValueError("disengaging the kill switch must be attributable")
        self.engaged = False
        self.reason = f"disengaged by {by}"
        self.engaged_at = None
        self.engaged_by = by

    def as_dict(self) -> dict[str, Any]:
        return {
            "engaged": self.engaged,
            "reason": self.reason,
            "engaged_at": self.engaged_at.isoformat() if self.engaged_at else None,
            "engaged_by": self.engaged_by,
        }


@dataclass(frozen=True)
class ExecutionPolicy:
    """The deployment's standing answer to "may this process trade at all?".

    Frozen, and every default refuses. `dry_run` is separate from `enabled`
    on purpose: turning execution on and turning simulation off are two
    decisions, and collapsing them into one flag means the first person to
    enable the engine also silently enables live orders.
    """

    enabled: bool = False
    dry_run: bool = True
    # Mirrors MOLIDO_REQUIRE_AUTH. An order placed by an unauthenticated caller
    # is an order with no attributable actor, which the audit trail the spec
    # requires cannot be reconstructed from afterwards.
    require_auth: bool = False
    max_risk_r_per_order: float = 1.0


@dataclass
class PreflightResult:
    """Why the order may or may not proceed, check by check.

    `checks` is returned whole rather than only the failures: an operator
    debugging a refusal needs to see what *did* pass, and a checklist that only
    reports its objections is impossible to reason about at three in the
    morning.
    """

    cleared: bool
    blocks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)
    duplicate_of: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "cleared": self.cleared,
            "blocks": self.blocks,
            "warnings": self.warnings,
            "checks": self.checks,
            "duplicate_of": self.duplicate_of,
            # Passing preflight is permission to *attempt* an order, and
            # nothing more. The attempt can still fail at the broker.
            "note": "preflight clears an attempt; it does not guarantee a fill",
        }


def preflight(
    intent: OrderIntent,
    *,
    policy: ExecutionPolicy,
    kill_switch: KillSwitch,
    already_submitted: str | None = None,
    now: datetime | None = None,
) -> PreflightResult:
    """Run the whole checklist. Any single failure is a block.

    `already_submitted` is the client order id of a prior submission of this
    same intent, if the caller's store has one. Passing None means "not seen
    before" and passing the id means "seen"; there is no third value, because
    a store that cannot answer must be treated as one that answered yes - see
    `engine.execute`, which refuses rather than guessing.
    """
    moment = now or datetime.now(UTC)
    blocks: list[str] = []
    warnings: list[str] = []
    checks: dict[str, bool] = {}

    def check(name: str, passed: bool, failure: str) -> None:
        checks[name] = passed
        if not passed:
            blocks.append(failure)

    check(
        "execution_enabled",
        policy.enabled,
        "execution is disabled for this deployment",
    )
    check(
        "kill_switch_clear",
        not kill_switch.engaged,
        f"the kill switch is engaged: {kill_switch.reason}",
    )
    check(
        "auth_required",
        policy.require_auth,
        "MOLIDO_REQUIRE_AUTH is false — an order would have no attributable actor",
    )

    # ------------------------------------------------------------- approvals
    for source in REQUIRED_APPROVALS:
        approval = intent.approval(source)
        if approval is None:
            check(f"approved_by_{source}", False, f"no approval from the {source} layer")
        else:
            check(
                f"approved_by_{source}",
                approval.approved,
                f"the {source} layer refused: {approval.detail}",
            )

    # ------------------------------------------------------------ freshness
    age = intent.age_seconds(moment)
    if age < -MAX_AUTHORISATION_SKEW_SECONDS:
        check(
            "authorisation_not_future_dated",
            False,
            f"authorisation is stamped {-age:.1f}s in the future — clock skew or a replay",
        )
    else:
        checks["authorisation_not_future_dated"] = True
        check(
            "authorisation_fresh",
            age <= MAX_AUTHORISATION_AGE_SECONDS,
            f"authorisation is {age:.1f}s old, beyond the "
            f"{MAX_AUTHORISATION_AGE_SECONDS:.0f}s limit — the account has moved since",
        )

    # Each approval is checked for staleness in its own right: an intent can be
    # assembled fresh out of one layer's month-old opinion.
    for approval in intent.approvals:
        approval_age = (moment - approval.at).total_seconds()
        if approval_age > MAX_AUTHORISATION_AGE_SECONDS:
            check(
                f"{approval.source}_approval_fresh",
                False,
                f"the {approval.source} approval is {approval_age:.1f}s old",
            )

    # ----------------------------------------------------------------- size
    check(
        "size_within_ceiling",
        intent.risk_r <= policy.max_risk_r_per_order,
        f"{intent.risk_r:.2f} R exceeds the {policy.max_risk_r_per_order:.2f} R "
        "per-order ceiling",
    )

    # --------------------------------------------------------- idempotency
    if already_submitted is not None:
        checks["not_a_duplicate"] = False
        blocks.append(
            f"this intent was already submitted as {already_submitted} — resubmitting "
            "would open a second position, not retry the first"
        )
    else:
        checks["not_a_duplicate"] = True

    if policy.dry_run:
        warnings.append("dry run: the order will be simulated, not sent")

    return PreflightResult(
        cleared=not blocks,
        blocks=blocks,
        warnings=warnings,
        checks=checks,
        duplicate_of=already_submitted,
    )
