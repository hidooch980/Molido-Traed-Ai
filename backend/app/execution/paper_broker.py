"""A broker that answers like the real one and sends nothing.

The mandatory first gate before a demo account is a full run on live data with
no money at risk. The project had the mode - `autopilot` has told the truth
about `paper` since the beginning - but `autotrade` refused the cycle outright
when it saw one, so the mode meant "do nothing" rather than "do everything
except send".

That is the wrong shape for the gate it is supposed to be. Everything upstream
of the send is where the work is: the kill switch, the risk brain's sizing,
the challenge rulebook, the news window, the correlation headroom, the spread
ceiling, the lot arithmetic against the broker's own tick value. A paper mode
that stops before all of that exercises none of it, and the first time any of
it runs is on real money.

So this implements the same `submit` and returns the same `ExecutionReport`,
filled at the intent's own entry price, and writes nothing anywhere. It is
deliberately a separate class rather than a flag on the real adapter: a flag
is one `if` away from sending, and the branch that decides is the one nobody
reads twice.

**Why the name is not `PaperBroker`.** `broker.PaperBroker` already exists and
is a different thing: the execution engine's simulator, which fills against
`client_order_id` and reports `risk_r` as the filled quantity. This one mirrors
`MetaTraderBroker` instead - keyed on `intent_id`, sized from the `lots` the
sizing produced - because it stands in for that adapter in live paper mode and
must answer the way the thing it replaces answers. Two classes with one name in
sibling modules meant the import decided which contract you got.

**Filled, not unknown.** A paper report that came back UNKNOWN would exercise
the retry path on every cycle and teach the journal that every order times
out. The point is to exercise the path that a working broker produces.

**No slippage model here.** Filling at the requested price overstates the
result by exactly the spread, and inventing a slippage number would make it
look measured. The spread is charged where it is known - in
`learning.measure.cost_in_r`, against the stop that defines R - and a second
guess at it here would be a different number in a second place.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.execution.contracts import ExecutionReport, OrderIntent, OrderState

#: Marks every report this produces. A paper fill that reads as a live one in
#: the journal is worse than no record: it would be counted in realised P&L,
#: in the hit rate, and in the evidence the edge registry is waiting on.
PAPER_MARKER = "paper"


class LivePaperBroker:
    """Answers like the real adapter, sends nothing, records what it saw."""

    name = "paper"

    def __init__(self) -> None:
        #: Every intent this saw, in order. Read by tests and by the cycle
        #: report; deliberately not persisted, because a paper fill in the
        #: positions file would be indistinguishable from a real one.
        self.submitted: list[OrderIntent] = []
        #: What was answered for each, so `status` and `reconcile` can answer
        #: from the same record `submit` wrote rather than from a second one.
        self.reports: dict[str, ExecutionReport] = {}
        self.accounts: dict[str, str] = {}

    def submit(self, intent: OrderIntent) -> ExecutionReport:
        """Accept the order at its own entry price and keep it in memory."""
        self.submitted.append(intent)
        client_order_id = str(intent.intent_id)
        lots = float(intent.metadata.get("lots") or 0.0)

        if lots <= 0:
            # The same refusal the real adapter makes, for the same reason: a
            # request that cannot succeed should not look like one that did.
            return self._remember(
                intent,
                ExecutionReport(
                    client_order_id=client_order_id,
                    state=OrderState.REJECTED,
                    at=datetime.now(UTC),
                    reason="no lots to send",
                    raw={"broker": PAPER_MARKER},
                ),
            )

        return self._remember(
            intent,
            ExecutionReport(
                client_order_id=client_order_id,
                # A ticket that cannot collide with a broker's, and that says
                # what it is on sight rather than only in a field somebody has
                # to check.
                broker_order_id=f"{PAPER_MARKER}-{uuid.uuid4().hex[:12]}",
                state=OrderState.FILLED,
                at=datetime.now(UTC),
                filled_quantity=lots,
                average_price=float(intent.entry) if intent.entry is not None else None,
                reason=None,
                raw={
                    "broker": PAPER_MARKER,
                    "note": (
                        "filled at the requested price and sent nowhere - this "
                        "overstates the result by the spread, which is charged "
                        "where it is measured rather than guessed at again here"
                    ),
                },
            ),
        )

    def status(self, client_order_id: str) -> ExecutionReport:
        """What this adapter answered for that order, if it answered at all.

        UNKNOWN rather than REJECTED for an order it has never seen, matching
        the rule every adapter obeys: not having a record is not evidence that
        nothing happened. Here it genuinely is - nothing is ever sent - but an
        adapter that reasons from what it knows about itself would be the one
        adapter whose UNKNOWN means something different from the rest.
        """
        found = self.reports.get(client_order_id)
        if found is not None:
            return found
        return ExecutionReport(
            client_order_id=client_order_id,
            state=OrderState.UNKNOWN,
            at=datetime.now(UTC),
            reason="no such order at this broker - it may never have arrived",
            raw={"broker": PAPER_MARKER},
        )

    def cancel(self, client_order_id: str) -> ExecutionReport:
        """Nothing here is ever cancellable, and this says so rather than lies.

        Every report this produces is terminal on the instant it is made -
        filled or rejected - so there is no pending state for a cancel to
        reach. Returning CANCELLED would put a state in the journal that never
        happened; the existing terminal report is returned instead, which is
        what a real broker returns when asked to cancel a filled order.
        """
        found = self.reports.get(client_order_id)
        if found is not None:
            return found
        return self.status(client_order_id)

    def reconcile(self, account_id: str) -> list[ExecutionReport]:
        """Every fill this process produced for that account.

        In memory only, and gone on restart. That is the honest answer for an
        adapter that sends nothing: there is no broker holding these, so there
        is nowhere to recover them from. A supervisor comparing this against
        its own record after a restart will see an empty account, which is
        correct - a paper position that survived a restart would be a position
        no broker has ever heard of.
        """
        return [
            report
            for order_id, report in self.reports.items()
            if self.accounts.get(order_id) == account_id
        ]

    def _remember(self, intent: OrderIntent, report: ExecutionReport) -> ExecutionReport:
        self.reports[report.client_order_id] = report
        self.accounts[report.client_order_id] = intent.account_id
        return report

    def as_dict(self) -> dict[str, Any]:
        return {
            "broker": PAPER_MARKER,
            "submitted": len(self.submitted),
            "symbols": sorted({i.symbol for i in self.submitted}),
        }
