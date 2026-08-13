"""What an order is, and what has to be true before it exists (spec phase 25, §22).

Every other layer in this system answers a question. This one does something,
and the difference changes what the types have to carry.

An `OrderIntent` is not an order. It is a request that has to survive a
checklist, and it carries the evidence for its own approval: which risk
decision authorised it, which portfolio verdict left room for it, which
challenge rules it was checked against, which stress report cleared it. That
evidence is part of the object rather than something the caller passes
alongside it, because an approval that can be separated from the thing it
approves will eventually be reused for something else.

Two properties are structural rather than procedural:

**An intent carries its own identity.** `client_order_id` is derived from the
intent's own content, so the same decision submitted twice is the same order
twice — and the second submission is recognised as a duplicate rather than
becoming a second position. Retries are the normal case in this layer, not the
exceptional one: a network timeout tells you nothing about whether the broker
filled.

**Approvals expire.** `authorised_at` is on the intent, and the executor
refuses evidence older than a few seconds. A risk decision made against an
account state that has since moved is not evidence about the account the order
is about to touch.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.core.errors import ValidationFailedError


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    """Deliberately small.

    Market and limit cover what this system decides. Every exotic order type is
    a way of expressing an intention the strategy layer should have expressed
    itself, and each one is a separate set of broker-specific failure modes.
    """

    MARKET = "market"
    LIMIT = "limit"


class OrderState(StrEnum):
    """The state machine, and it only moves forward.

    UNKNOWN is the important one and the reason this enum is not a boolean. A
    submission that timed out is not a rejection: the broker may have filled it.
    Treating "we did not hear back" as "it did not happen" is how a system ends
    up with a position it does not know about, and then opens a second one.
    """

    DRAFT = "draft"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


# Which states may follow which. Absent from every value: any path out of a
# terminal state. An order that filled cannot later become rejected, and code
# that tries is confused about which order it is holding.
_TRANSITIONS: dict[OrderState, frozenset[OrderState]] = {
    OrderState.DRAFT: frozenset({OrderState.SUBMITTED, OrderState.CANCELLED}),
    OrderState.SUBMITTED: frozenset(
        {
            OrderState.ACCEPTED,
            OrderState.REJECTED,
            OrderState.PARTIALLY_FILLED,
            OrderState.FILLED,
            OrderState.UNKNOWN,
        }
    ),
    OrderState.ACCEPTED: frozenset(
        {
            OrderState.PARTIALLY_FILLED,
            OrderState.FILLED,
            OrderState.CANCELLED,
            OrderState.REJECTED,
            OrderState.UNKNOWN,
        }
    ),
    OrderState.PARTIALLY_FILLED: frozenset(
        {OrderState.FILLED, OrderState.CANCELLED, OrderState.UNKNOWN}
    ),
    # UNKNOWN resolves only by asking the broker what actually happened, which
    # is why it leads back into the live states rather than to a terminal one.
    OrderState.UNKNOWN: frozenset(
        {
            OrderState.ACCEPTED,
            OrderState.PARTIALLY_FILLED,
            OrderState.FILLED,
            OrderState.CANCELLED,
            OrderState.REJECTED,
        }
    ),
    OrderState.FILLED: frozenset(),
    OrderState.CANCELLED: frozenset(),
    OrderState.REJECTED: frozenset(),
}

TERMINAL_STATES = frozenset(
    {OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED}
)


def can_transition(current: OrderState, following: OrderState) -> bool:
    return following in _TRANSITIONS[current]


def assert_transition(current: OrderState, following: OrderState) -> None:
    if not can_transition(current, following):
        raise ValidationFailedError(
            f"an order cannot move from {current.value!r} to {following.value!r}",
            current=current.value,
            requested=following.value,
        )


@dataclass(frozen=True)
class Approval:
    """One layer's sign-off, named and timestamped.

    `source` is which layer said yes, not a free-text note. The executor checks
    that a specific set of sources is present, so a caller cannot satisfy the
    checklist by supplying four approvals from the same enthusiastic layer.
    """

    source: str
    approved: bool
    detail: str
    at: datetime

    def __post_init__(self) -> None:
        if self.at.tzinfo is None:
            raise ValidationFailedError("approval timestamps must be timezone-aware")


@dataclass(frozen=True)
class OrderIntent:
    """A request to open risk, with the evidence that it was allowed.

    `risk_r` rather than lots or units: risk is the only size that composes
    across instruments, and converting to a broker's units is the adapter's
    job because only the adapter knows the contract size.
    """

    symbol: str
    side: OrderSide
    order_type: OrderType
    risk_r: float
    entry: float | None
    stop: float
    target: float | None
    approvals: tuple[Approval, ...]
    authorised_at: datetime
    account_id: str
    intent_id: uuid.UUID = field(default_factory=uuid.uuid4)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.risk_r <= 0:
            raise ValidationFailedError(
                f"an intent must risk something; {self.risk_r} is not a size"
            )
        if self.authorised_at.tzinfo is None:
            raise ValidationFailedError("authorised_at must be timezone-aware")
        if self.order_type is OrderType.LIMIT and self.entry is None:
            raise ValidationFailedError("a limit order needs a price to be limited to")
        # A stop is what makes the risk finite. Without one the position has no
        # defined loss, so there is no R to size it in and nothing downstream
        # can say whether the account survives it.
        if self.stop <= 0:
            raise ValidationFailedError("a stop is required and must be a real price")
        self._assert_levels_make_sense()

    def _assert_levels_make_sense(self) -> None:
        reference = self.entry
        if reference is None:
            return
        if self.side is OrderSide.BUY and self.stop >= reference:
            raise ValidationFailedError(
                f"a buy stopped at {self.stop} above its {reference} entry is not a stop"
            )
        if self.side is OrderSide.SELL and self.stop <= reference:
            raise ValidationFailedError(
                f"a sell stopped at {self.stop} below its {reference} entry is not a stop"
            )
        if self.target is None:
            return
        if self.side is OrderSide.BUY and self.target <= reference:
            raise ValidationFailedError("a buy target must sit above its entry")
        if self.side is OrderSide.SELL and self.target >= reference:
            raise ValidationFailedError("a sell target must sit below its entry")

    @property
    def client_order_id(self) -> str:
        """A stable id derived from what the order *is*.

        Content-derived rather than random: a retry after a timeout has to
        produce the same id as the attempt that may already have reached the
        broker, or the retry becomes a second position. The intent_id is part
        of the hash, so two genuinely separate decisions to buy the same thing
        at the same price remain two orders.
        """
        material = "|".join(
            [
                self.account_id,
                self.symbol,
                self.side.value,
                self.order_type.value,
                f"{self.risk_r:.6f}",
                f"{self.entry:.6f}" if self.entry is not None else "market",
                f"{self.stop:.6f}",
                str(self.intent_id),
            ]
        )
        return "mld-" + hashlib.sha256(material.encode()).hexdigest()[:24]

    def approval(self, source: str) -> Approval | None:
        for item in self.approvals:
            if item.source == source:
                return item
        return None

    def age_seconds(self, now: datetime | None = None) -> float:
        return ((now or datetime.now(UTC)) - self.authorised_at).total_seconds()

    def as_dict(self) -> dict[str, Any]:
        return {
            "intent_id": str(self.intent_id),
            "client_order_id": self.client_order_id,
            "account_id": self.account_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "order_type": self.order_type.value,
            "risk_r": self.risk_r,
            "entry": self.entry,
            "stop": self.stop,
            "target": self.target,
            "authorised_at": self.authorised_at.isoformat(),
            "approvals": [
                {
                    "source": a.source,
                    "approved": a.approved,
                    "detail": a.detail,
                    "at": a.at.isoformat(),
                }
                for a in self.approvals
            ],
        }


@dataclass
class ExecutionReport:
    """What the broker said, or the fact that it said nothing.

    `state` is never inferred. An adapter that cannot reach the broker returns
    UNKNOWN with the reason; it does not return REJECTED, because it does not
    know that.
    """

    client_order_id: str
    state: OrderState
    at: datetime
    broker_order_id: str | None = None
    filled_quantity: float = 0.0
    average_price: float | None = None
    reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def opened_risk(self) -> bool:
        """Whether this report proves risk is now live.

        UNKNOWN counts. Not because it opened a position, but because it might
        have, and every caller that asks this question is deciding whether it
        is safe to send another order.
        """
        return self.state in {
            OrderState.ACCEPTED,
            OrderState.PARTIALLY_FILLED,
            OrderState.FILLED,
            OrderState.SUBMITTED,
            OrderState.UNKNOWN,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "client_order_id": self.client_order_id,
            "broker_order_id": self.broker_order_id,
            "state": self.state.value,
            "at": self.at.isoformat(),
            "filled_quantity": self.filled_quantity,
            "average_price": self.average_price,
            "reason": self.reason,
            "terminal": self.is_terminal,
        }
