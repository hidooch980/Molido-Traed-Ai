"""The broker boundary, and the only implementation that exists (phase 26, §23).

An adapter's job is to be the one place that knows a broker's dialect: its
symbol names, its contract sizes, its error codes, its particular way of timing
out. Everything above it speaks in risk and prices.

Two rules the protocol enforces on every implementation:

**An adapter never invents a state.** If it cannot reach the broker it returns
UNKNOWN with the reason. Returning REJECTED would be a claim about what the
broker did, and a timeout is precisely the case where nobody knows.

**An adapter converts, it does not decide.** No adapter checks risk, size,
limits or permission. Those checks live in `safety.preflight`, and an adapter
that repeated them would eventually disagree with it — at which point there
are two answers and no way to tell which one is authoritative.

`PaperBroker` is the only adapter here. A real one is a separate module with
credentials the operator supplies on the server; this file deliberately
contains no network client, so nothing in this repository can reach a live
account.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from app.core.errors import MolidoError
from app.execution.contracts import (
    ExecutionReport,
    OrderIntent,
    OrderSide,
    OrderState,
    OrderType,
)


class BrokerUnavailableError(MolidoError):
    """The broker could not be reached. Says nothing about the order."""

    code = "broker_unavailable"
    http_status = 503


class BrokerAdapter(Protocol):
    """What every broker must be able to do.

    Deliberately four methods. `reconcile` is not optional and not an
    afterthought: an execution layer without a way to ask "what do you
    actually have?" cannot recover from its own uncertainty, and uncertainty
    here is routine.
    """

    name: str

    def submit(self, intent: OrderIntent) -> ExecutionReport:
        """Place the order. Must return UNKNOWN rather than raise on a timeout."""
        ...

    def cancel(self, client_order_id: str) -> ExecutionReport: ...

    def status(self, client_order_id: str) -> ExecutionReport: ...

    def reconcile(self, account_id: str) -> list[ExecutionReport]:
        """Everything the broker believes is live for this account."""
        ...


@dataclass
class PaperFill:
    """How a simulated order is priced.

    Slippage is a required argument with no default. A paper broker that fills
    at the requested price teaches a system that execution is free, and every
    number computed on top of it — expectancy, drawdown, the survivable size —
    inherits that lie.
    """

    price: float
    slippage: float
    at: datetime


@dataclass
class PaperBroker:
    """A broker that fills nothing anywhere.

    It exists so the layers above can be exercised end to end — including the
    failure paths, which is why `fail_next` and `timeout_next` are part of the
    adapter rather than something a test monkeypatches. The awkward states are
    the ones worth rehearsing.
    """

    name: str = "paper"
    slippage: float = 0.0001
    orders: dict[str, ExecutionReport] = field(default_factory=dict)
    intents: dict[str, OrderIntent] = field(default_factory=dict)
    # Set by a caller rehearsing a failure. Consumed by the next submit.
    fail_next: str | None = None
    timeout_next: bool = False

    def submit(self, intent: OrderIntent) -> ExecutionReport:
        now = datetime.now(UTC)

        if self.timeout_next:
            self.timeout_next = False
            # Recorded before returning: from this adapter's point of view the
            # order may well be live at the broker, and forgetting it here is
            # how a system loses track of a position it opened.
            report = ExecutionReport(
                client_order_id=intent.client_order_id,
                state=OrderState.UNKNOWN,
                at=now,
                reason="the broker did not answer; the order may or may not be live",
            )
            self.orders[intent.client_order_id] = report
            self.intents[intent.client_order_id] = intent
            return report

        if self.fail_next is not None:
            reason, self.fail_next = self.fail_next, None
            report = ExecutionReport(
                client_order_id=intent.client_order_id,
                state=OrderState.REJECTED,
                at=now,
                reason=reason,
            )
            self.orders[intent.client_order_id] = report
            return report

        existing = self.orders.get(intent.client_order_id)
        if existing is not None:
            # The broker's own idempotency, mirroring what a real one does with
            # a repeated client order id: return the original rather than
            # opening a second position.
            return existing

        price = intent.entry
        if price is None:
            raise BrokerUnavailableError(
                "a market order needs a reference price to simulate a fill against; "
                "supply `entry` even for market orders",
                client_order_id=intent.client_order_id,
            )
        filled = self._slipped(price, intent.side)
        report = ExecutionReport(
            client_order_id=intent.client_order_id,
            broker_order_id=f"paper-{uuid.uuid4().hex[:12]}",
            state=OrderState.FILLED
            if intent.order_type is OrderType.MARKET
            else OrderState.ACCEPTED,
            at=now,
            filled_quantity=intent.risk_r if intent.order_type is OrderType.MARKET else 0.0,
            average_price=filled if intent.order_type is OrderType.MARKET else None,
            reason=None,
            raw={"simulated": True, "requested_price": price, "slippage": self.slippage},
        )
        self.orders[intent.client_order_id] = report
        self.intents[intent.client_order_id] = intent
        return report

    def _slipped(self, price: float, side: OrderSide) -> float:
        """Slippage always costs. A fill better than requested is not modelled.

        Real fills are sometimes better, but modelling that here would let a
        simulated strategy earn the difference, and a backtest that profits
        from its own optimism is worse than one with no slippage at all.
        """
        return price + self.slippage if side is OrderSide.BUY else price - self.slippage

    def cancel(self, client_order_id: str) -> ExecutionReport:
        now = datetime.now(UTC)
        existing = self.orders.get(client_order_id)
        if existing is None:
            return ExecutionReport(
                client_order_id=client_order_id,
                state=OrderState.UNKNOWN,
                at=now,
                reason="no such order at this broker — it may never have arrived",
            )
        if existing.is_terminal:
            return existing
        cancelled = ExecutionReport(
            client_order_id=client_order_id,
            broker_order_id=existing.broker_order_id,
            state=OrderState.CANCELLED,
            at=now,
        )
        self.orders[client_order_id] = cancelled
        return cancelled

    def status(self, client_order_id: str) -> ExecutionReport:
        existing = self.orders.get(client_order_id)
        if existing is not None:
            return existing
        return ExecutionReport(
            client_order_id=client_order_id,
            state=OrderState.UNKNOWN,
            at=datetime.now(UTC),
            reason="no such order at this broker — it may never have arrived",
        )

    def reconcile(self, account_id: str) -> list[ExecutionReport]:
        return [
            report
            for order_id, report in self.orders.items()
            if self.intents.get(order_id) is not None
            and self.intents[order_id].account_id == account_id
        ]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "simulated": True,
            "slippage": self.slippage,
            "orders": len(self.orders),
        }
