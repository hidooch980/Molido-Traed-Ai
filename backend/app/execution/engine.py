"""The executor, and the position guardian (phases 25 and 27, §22 and §26).

`execute` is the only function in this system that causes anything to happen in
the outside world, so it is written to be boring. It runs the checklist, and if
the checklist clears it hands the intent to an adapter. It contains no
judgement of its own: there is no condition under which it decides the
checklist was being unreasonable.

The parts that are easy to get wrong, and how they are handled:

**The submission record is written before the submission.** If the process dies
between the two, the record says an order may be live and reconciliation will
find it. Written afterwards, a crash in the gap produces an order nobody owns —
and the next run, seeing no record, submits it again.

**A store that cannot answer is treated as one that said yes.** `SubmissionLog`
raising means the idempotency question is unanswered, and an unanswered
idempotency question is a refusal, not a retry.

**UNKNOWN is not a failure to be retried.** It is a position that may exist.
The guardian resolves it by asking the broker; nothing resolves it by assuming.

The guardian below watches what is already open — the spec's fourth verb. It
detects positions the system did not open, stops that vanished, and drift
between what the broker holds and what this system believes it holds. It
reports; it does not close anything, because closing a position it does not
understand is how a supervisor turns a discrepancy into a loss.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.execution.broker import BrokerAdapter
from app.execution.contracts import (
    ExecutionReport,
    OrderIntent,
    OrderState,
    assert_transition,
)
from app.execution.safety import (
    ExecutionPolicy,
    KillSwitch,
    PreflightResult,
    preflight,
)


class SubmissionLog:
    """Which intents have been sent, so none is sent twice.

    In-memory here. A deployment replaces it with a table whose unique key is
    the client order id, and the uniqueness constraint — not this class — is
    what actually prevents a duplicate under concurrency.
    """

    def __init__(self) -> None:
        self._by_intent: dict[str, str] = {}
        self._reports: dict[str, ExecutionReport] = {}

    def submitted_id(self, intent: OrderIntent) -> str | None:
        return self._by_intent.get(str(intent.intent_id))

    def record_attempt(self, intent: OrderIntent) -> None:
        self._by_intent[str(intent.intent_id)] = intent.client_order_id

    def record_report(self, report: ExecutionReport) -> None:
        previous = self._reports.get(report.client_order_id)
        # Enforced where reports are stored rather than where they are
        # produced, so an adapter cannot walk an order backwards out of a
        # terminal state by returning a stale message. An unchanged state is
        # exempt: polling an order that is still UNKNOWN answers the question
        # again, it does not move the order.
        if previous is not None and previous.state is not report.state:
            assert_transition(previous.state, report.state)
        self._reports[report.client_order_id] = report

    def report(self, client_order_id: str) -> ExecutionReport | None:
        return self._reports.get(client_order_id)

    def live_orders(self) -> list[ExecutionReport]:
        return [r for r in self._reports.values() if not r.is_terminal]


@dataclass
class ExecutionOutcome:
    """What happened, including the case where nothing was attempted."""

    attempted: bool
    preflight: PreflightResult
    report: ExecutionReport | None = None
    simulated: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "attempted": self.attempted,
            "simulated": self.simulated,
            "preflight": self.preflight.as_dict(),
            "report": self.report.as_dict() if self.report else None,
        }


def execute(
    intent: OrderIntent,
    *,
    broker: BrokerAdapter,
    policy: ExecutionPolicy,
    kill_switch: KillSwitch,
    log: SubmissionLog,
    now: datetime | None = None,
) -> ExecutionOutcome:
    """Run the checklist, then place the order if — and only if — it cleared."""
    try:
        already = log.submitted_id(intent)
    except Exception as exc:  # noqa: BLE001 - the reason is reported, not swallowed
        # An unanswerable idempotency question is a refusal. Submitting anyway
        # risks a second position; refusing risks a missed trade, and only one
        # of those is recoverable.
        result = PreflightResult(
            cleared=False,
            blocks=[f"the submission log could not be read: {exc}"],
            checks={"not_a_duplicate": False},
        )
        return ExecutionOutcome(attempted=False, preflight=result)

    result = preflight(
        intent,
        policy=policy,
        kill_switch=kill_switch,
        already_submitted=already,
        now=now,
    )
    if not result.cleared:
        return ExecutionOutcome(attempted=False, preflight=result)

    if policy.dry_run:
        # Nothing reaches the adapter, and nothing is written to the log: a
        # rehearsal that consumed the intent's idempotency would make the real
        # submission look like a duplicate.
        return ExecutionOutcome(
            attempted=False,
            simulated=True,
            preflight=result,
            report=ExecutionReport(
                client_order_id=intent.client_order_id,
                state=OrderState.DRAFT,
                at=now or datetime.now(UTC),
                reason="dry run — the order was not sent",
            ),
        )

    # Before, not after. A crash in the gap must leave evidence that an order
    # may be live, because reconciliation can resolve that and cannot resolve
    # silence.
    log.record_attempt(intent)
    report = broker.submit(intent)
    log.record_report(report)
    return ExecutionOutcome(attempted=True, preflight=result, report=report)


def resolve_unknown(
    client_order_id: str, *, broker: BrokerAdapter, log: SubmissionLog
) -> ExecutionReport:
    """Ask the broker what actually happened to an order we lost track of."""
    report = broker.status(client_order_id)
    log.record_report(report)
    return report


# ------------------------------------------------------------------ guardian


@dataclass
class Position:
    """A live position as somebody believes it to be."""

    symbol: str
    side: str
    quantity: float
    stop: float | None = None
    target: float | None = None
    client_order_id: str | None = None


@dataclass
class GuardianReport:
    """What the guardian found. Findings only — it closes nothing.

    A supervisor that acts on a discrepancy it does not understand converts an
    accounting problem into a realised loss. Every finding here is addressed to
    a human, and the most serious ones say so.
    """

    checked_at: datetime
    orphans: list[Position] = field(default_factory=list)
    missing: list[Position] = field(default_factory=list)
    unprotected: list[Position] = field(default_factory=list)
    drifted: list[str] = field(default_factory=list)
    unresolved_orders: list[str] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return not (
            self.orphans
            or self.missing
            or self.unprotected
            or self.drifted
            or self.unresolved_orders
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "checked_at": self.checked_at.isoformat(),
            "healthy": self.healthy,
            "orphans": [p.symbol for p in self.orphans],
            "missing": [p.symbol for p in self.missing],
            "unprotected": [p.symbol for p in self.unprotected],
            "drifted": self.drifted,
            "unresolved_orders": self.unresolved_orders,
            "alerts": self.alerts,
            "closes_nothing": True,
        }


def _key(position: Position) -> tuple[str, str]:
    return position.symbol, position.side


def supervise(
    *,
    broker_positions: list[Position],
    expected_positions: list[Position],
    log: SubmissionLog,
    quantity_tolerance: float = 1e-6,
    now: datetime | None = None,
) -> GuardianReport:
    """Compare what the broker holds with what this system believes it holds.

    Both directions are checked, and they mean different things. A position at
    the broker that this system did not open is the more alarming of the two:
    it is either a manual trade, a duplicate from a retry, or a fill from an
    order that timed out — and every one of those means the risk layer is
    sizing against an account it is not seeing.
    """
    report = GuardianReport(checked_at=now or datetime.now(UTC))

    broker_by_key = {_key(p): p for p in broker_positions}
    expected_by_key = {_key(p): p for p in expected_positions}

    for key, position in broker_by_key.items():
        if key not in expected_by_key:
            report.orphans.append(position)
            report.alerts.append(
                f"{position.symbol} {position.side} is open at the broker and this "
                "system did not open it — every risk figure is understated until "
                "this is explained"
            )

    for key, position in expected_by_key.items():
        if key not in broker_by_key:
            report.missing.append(position)
            report.alerts.append(
                f"{position.symbol} {position.side} is believed open but the broker "
                "does not have it — it may have closed without the system noticing"
            )

    for key, position in broker_by_key.items():
        expected = expected_by_key.get(key)
        if expected is None:
            continue
        if abs(position.quantity - expected.quantity) > quantity_tolerance:
            report.drifted.append(
                f"{position.symbol}: broker holds {position.quantity}, "
                f"this system believes {expected.quantity}"
            )

    # A position without a stop has no defined loss, so nothing above can size
    # against it and nothing can say whether the account survives it.
    for position in broker_positions:
        if position.stop is None:
            report.unprotected.append(position)
            report.alerts.append(
                f"{position.symbol} is open with no stop — its loss is unbounded and "
                "it cannot be counted in any risk figure"
            )

    for order in log.live_orders():
        if order.state is OrderState.UNKNOWN:
            report.unresolved_orders.append(order.client_order_id)
            report.alerts.append(
                f"{order.client_order_id} was never resolved — ask the broker before "
                "sending anything else for this account"
            )

    return report
