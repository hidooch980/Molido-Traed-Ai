"""The adapter that actually sends an order, through the file bridge.

Until this existed the platform could not place one. `api_can_place_orders`
was false, the only adapter was `PaperBroker` - "a broker that fills nothing
anywhere" - and the autopilot reported `would_send_live_orders: true`, which
was a verdict about a path that did not exist. That gap was reported to the
user as "armed" more than once.

It talks to the expert through the same common folder the bars arrive in: a
request file appears, the expert claims it by renaming, sends it, and writes a
result file. Not elegant, and chosen anyway - the terminal runs under Wine with
no network listener, and a file both sides can see is the one channel that
already works and is already being watched.

**At most once, never exactly once.** The expert claims a request by renaming
it before reading it, so a second timer pass cannot pick up the same file. What
that buys is that a crash never doubles an order. What it cannot buy is
certainty: a crash between send and result leaves a position with no result
file, and the honest answer there is UNKNOWN, which is why `reconcile` is part
of the adapter protocol rather than an afterthought.

`submit` returns UNKNOWN rather than raising when the result does not arrive in
time. A timeout is not a rejection. Treating one as the other is how a system
decides an order failed, retries it, and ends up with two.
"""

from __future__ import annotations

import json
import pathlib
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.execution.contracts import (
    ExecutionReport,
    OrderIntent,
    OrderSide,
    OrderState,
)
from app.providers.metatrader import DEFAULT_BRIDGE_DIR

REQUEST_PREFIX = "molido_order_"
RESULT_PREFIX = "molido_result_"
CLAIM_PREFIX = "molido_claimed_"

#: How long to wait for the expert to answer.
#:
#: Was 45s, reasoned from the expert's twenty-second timer. The first live
#: probe took **seventy** - the timer fires on a terminal that is also
#: publishing forty-four bar files a cycle under Wine on a shared core, and it
#: had just restarted. At 45s that answer would have been reported UNKNOWN,
#: which is the most expensive outcome this adapter can produce: it means
#: reconciling against the terminal before anything else can be sent for that
#: symbol.
#:
#: Two minutes is not a latency budget, it is a patience budget. Waiting longer
#: costs one blocked call; giving up early costs a manual reconciliation and
#: possibly a duplicated position.
DEFAULT_TIMEOUT = 120.0

#: How often to look for the result file.
POLL_SECONDS = 0.5


@dataclass
class MetaTraderBroker:
    """Sends orders to the terminal by writing files it watches."""

    name: str = "metatrader"
    directory: pathlib.Path = field(
        default_factory=lambda: pathlib.Path(DEFAULT_BRIDGE_DIR)
    )
    timeout: float = DEFAULT_TIMEOUT
    #: Injected so tests never sleep and never touch a real terminal.
    clock: Any = time.monotonic
    sleeper: Any = time.sleep

    def submit(self, intent: OrderIntent) -> ExecutionReport:
        """Write the request, then wait for the expert to answer it."""
        client_order_id = str(intent.intent_id)
        lots = float(intent.metadata.get("lots") or 0.0)

        if lots <= 0:
            # Refused here rather than sent as zero. The expert would reject it
            # anyway, but a request that cannot succeed should not become a
            # pending file somebody has to explain later.
            return self._report(
                client_order_id,
                OrderState.REJECTED,
                reason=(
                    "no lot size on the intent - sizing is the caller's job and "
                    "an order with no size is not an order"
                ),
            )

        # The shape, as distances as well as levels.
        #
        # Levels alone anchor the trade to a price nobody got. The backend
        # reads a quote the expert published some seconds ago, computes a stop
        # and a target from it, and by the time the deal fills the market has
        # moved - so the stop sits at its intended distance from a price that
        # no longer exists, and at some other distance from the one actually
        # paid. Measured across twenty-eight live fills, a geometry designed
        # for one unit of reward per unit of risk was arriving at 0.77, and
        # eighteen of the twenty-eight were below parity. The worst was 0.15:
        # a trade needing an 87% win rate to break even, taken by a system
        # that believed it had taken an even-money bet.
        #
        # It is worse than a return problem. Size is computed from the
        # intended stop distance, so a fill that lands adverse risks more than
        # the budget allowed - the 0.15 trade risked 1.75 times what the risk
        # brain had authorised. The limit was not being honoured, and nothing
        # said so.
        #
        # Distances travel correctly because they are volatility, and the
        # expert can re-derive the levels from the price it actually got.
        # Levels are still sent: an expert that does not understand distances
        # keeps working exactly as before.
        stop_distance = (
            abs(intent.entry - intent.stop) if intent.entry is not None else None
        )
        target_distance = (
            abs(intent.target - intent.entry)
            if intent.target is not None and intent.entry is not None
            else None
        )

        payload = {
            "id": client_order_id,
            "symbol": intent.symbol,
            "side": "sell" if intent.side is OrderSide.SELL else "buy",
            "lots": round(lots, 2),
            "stop": intent.stop,
            "target": intent.target if intent.target is not None else 0.0,
            "account": intent.account_id,
        }
        # Omitted rather than sent as zero when they cannot be computed. Zero
        # is a distance the expert would have to treat as "no stop", and a
        # position with no stop is the one thing this system must never open.
        if stop_distance:
            payload["stop_distance"] = stop_distance
        if target_distance:
            payload["target_distance"] = target_distance

        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            request_path = self.directory / f"{REQUEST_PREFIX}{client_order_id}.json"
            request_path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError as problem:
            return self._report(
                client_order_id,
                OrderState.REJECTED,
                reason=f"the request could not be written: {problem}",
            )

        return self._await_result(client_order_id, requested_lots=lots)

    def status(self, client_order_id: str) -> ExecutionReport:
        """What the expert said about this order, if it has said anything."""
        found = self._read_result(client_order_id)
        if found is None:
            return self._report(
                client_order_id,
                OrderState.UNKNOWN,
                reason="no result file for this order yet",
            )
        return found

    def cancel(self, client_order_id: str) -> ExecutionReport:
        """Only an unclaimed request can be cancelled.

        Once the expert has renamed it there is no safe way to recall it: the
        order may already be live, and a cancel that races a fill is how one
        position becomes two.
        """
        request_path = self.directory / f"{REQUEST_PREFIX}{client_order_id}.json"
        if request_path.exists():
            try:
                request_path.unlink()
            except OSError as problem:
                return self._report(
                    client_order_id,
                    OrderState.UNKNOWN,
                    reason=f"the request could not be removed: {problem}",
                )
            return self._report(
                client_order_id,
                OrderState.CANCELLED,
                reason="withdrawn before the terminal claimed it",
            )

        claimed = self.directory / f"{CLAIM_PREFIX}{client_order_id}.json"
        if claimed.exists():
            return self._report(
                client_order_id,
                OrderState.UNKNOWN,
                reason=(
                    "the terminal has already claimed this request, so it may "
                    "be live. Cancelling here would race the fill"
                ),
            )
        return self.status(client_order_id)

    def reconcile(self, account_id: str) -> list[ExecutionReport]:
        """Every result the terminal has written that this side can see.

        Not "what the broker holds" - that is `positions` on the bridge, read
        from the terminal itself. This answers the narrower question the
        protocol needs: which of the orders sent from here were answered.
        """
        reports: list[ExecutionReport] = []
        if not self.directory.exists():
            return reports
        for path in sorted(self.directory.glob(f"{RESULT_PREFIX}*.json")):
            order_id = path.name[len(RESULT_PREFIX) : -len(".json")]
            found = self._read_result(order_id)
            if found is not None:
                reports.append(found)
        return reports

    def _await_result(
        self, client_order_id: str, *, requested_lots: float | None = None
    ) -> ExecutionReport:
        deadline = self.clock() + self.timeout
        while self.clock() < deadline:
            found = self._read_result(client_order_id, requested_lots)
            if found is not None:
                return found
            self.sleeper(POLL_SECONDS)

        # UNKNOWN, never REJECTED. A timeout is not a refusal, and treating one
        # as the other is how a system decides an order failed, retries it, and
        # ends up holding two.
        return self._report(
            client_order_id,
            OrderState.UNKNOWN,
            reason=(
                f"the terminal did not answer within {self.timeout:.0f}s. The "
                "order may be live - reconcile against the terminal's own "
                "positions before sending anything else for this symbol"
            ),
        )

    def _read_result(
        self, client_order_id: str, requested_lots: float | None = None
    ) -> ExecutionReport | None:
        path = self.directory / f"{RESULT_PREFIX}{client_order_id}.json"
        if not path.exists():
            return None
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A half-written file on the next poll is normal, not an error.
            return None

        filled = bool(body.get("ok"))

        # The expert answers with ok, ticket, price and reason - and no volume.
        # A filled order reported as zero quantity is internally inconsistent
        # and reads downstream as "nothing was filled", so the requested size
        # is carried through as the best number available.
        #
        # It is the *requested* size, not a confirmed executed one, and the
        # payload says so. Until the expert reports the volume it actually got,
        # a partial fill is invisible here: it would arrive as ok=true and be
        # recorded at full size. That is a real gap and naming it beats a
        # confident zero.
        quantity = float(requested_lots or 0.0) if filled else 0.0

        return ExecutionReport(
            client_order_id=client_order_id,
            state=OrderState.FILLED if filled else OrderState.REJECTED,
            at=datetime.now(UTC),
            broker_order_id=str(body.get("ticket") or "") or None,
            filled_quantity=quantity,
            average_price=float(body.get("price") or 0.0) or None,
            reason=str(body.get("reason") or ""),
            raw={
                **body,
                "volume_is_requested_not_confirmed": True,
                "note": (
                    "the expert does not report executed volume, so a partial "
                    "fill would arrive as a full one"
                ),
            },
        )

    @staticmethod
    def _report(
        client_order_id: str, state: OrderState, *, reason: str
    ) -> ExecutionReport:
        return ExecutionReport(
            client_order_id=client_order_id,
            state=state,
            at=datetime.now(UTC),
            reason=reason,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "directory": str(self.directory),
            "timeout_seconds": self.timeout,
            "note": (
                "sends orders by writing files the expert watches. The expert "
                "claims each request by renaming it before sending, so a crash "
                "can lose an order but cannot double one. A timeout reports "
                "UNKNOWN rather than rejected"
            ),
        }


def new_intent_id() -> uuid.UUID:
    """A fresh id, so a retry is never mistaken for the order it replaces."""
    return uuid.uuid4()
