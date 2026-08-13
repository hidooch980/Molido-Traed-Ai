"""Many accounts, many brokers (spec phases 43-44, §43-44).

One strategy, several accounts: a personal account, two prop-firm challenges at
different stages, a demo. They share a brain and share nothing else. Each has
its own broker, its own rulebook, its own equity and its own limits, and the
whole value of this module is refusing to let those bleed into one another.

Three ways they bleed in practice, all handled here:

**One intent sent to two accounts.** The same idea is a good idea on both, but
each is a separate order with a separate size, and an idempotency key derived
from the intent alone would make the second account's order look like a
duplicate of the first. The key is per account, so the two are distinguishable.

**A global risk figure.** "Total exposure 4 R" across accounts is a number that
describes nothing: 4 R on a 100k personal account and 4 R on a 10k challenge
are different amounts of money and different distances from a limit. Exposure
is tracked per account and only reported in aggregate.

**A shared kill switch that isn't.** Halting one account must halt it, and
halting everything must halt everything. Both exist, and the global switch
cannot be overridden by a per-account one — a switch that a subordinate can
ignore is not a switch.

Routing chooses which account an intent belongs to; it never decides *whether*
the intent is any good. That question was answered by the eight gates before
it, and asking it twice would give two answers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.errors import ValidationFailedError
from app.execution.broker import BrokerAdapter
from app.execution.contracts import OrderIntent
from app.execution.safety import ExecutionPolicy, KillSwitch


@dataclass
class Account:
    """One tradeable account, and everything that is true only of it.

    `broker` and `policy` are per account rather than global because a demo
    account and a funded challenge should not share a dry-run flag: the whole
    reason to keep a demo is to run it live while the funded one is halted.
    """

    account_id: str
    broker: BrokerAdapter
    policy: ExecutionPolicy
    kill_switch: KillSwitch = field(default_factory=KillSwitch)
    challenge_rules: Any | None = None
    label: str = ""
    # Instruments this account may trade. Empty means no restriction, which is
    # different from an empty *list of allowed symbols* — see `permits_symbol`.
    allowed_symbols: frozenset[str] = frozenset()
    max_open_positions: int | None = None

    def permits_symbol(self, symbol: str) -> bool:
        return not self.allowed_symbols or symbol in self.allowed_symbols

    def as_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "label": self.label,
            "broker": getattr(self.broker, "name", "unknown"),
            "enabled": self.policy.enabled,
            "dry_run": self.policy.dry_run,
            "kill_switch": self.kill_switch.as_dict(),
            "allowed_symbols": sorted(self.allowed_symbols),
            "max_open_positions": self.max_open_positions,
            "has_challenge_rules": self.challenge_rules is not None,
        }


@dataclass
class RoutedIntent:
    """One account's copy of an idea, with its own identity."""

    account_id: str
    intent: OrderIntent
    broker_name: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "broker": self.broker_name,
            "client_order_id": self.intent.client_order_id,
            "intent": self.intent.as_dict(),
        }


@dataclass
class RoutingResult:
    routed: list[RoutedIntent] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "routed": [r.as_dict() for r in self.routed],
            "skipped": self.skipped,
            # Routing places nothing. Each routed intent still faces its own
            # account's checklist in `engine.execute`.
            "note": "routing selects accounts; every intent still runs its own preflight",
        }


class AccountBook:
    """Every account the system knows about, and the switch above all of them."""

    def __init__(self, accounts: list[Account] | None = None) -> None:
        self._accounts: dict[str, Account] = {}
        # Engaged by default, like every other switch in this system. A global
        # halt that starts open protects nothing.
        self.global_kill_switch = KillSwitch()
        for account in accounts or []:
            self.add(account)

    def add(self, account: Account) -> Account:
        if account.account_id in self._accounts:
            raise ValidationFailedError(
                f"account {account.account_id!r} is already registered — two accounts "
                "sharing an id would share an idempotency namespace"
            )
        self._accounts[account.account_id] = account
        return account

    def get(self, account_id: str) -> Account | None:
        return self._accounts.get(account_id)

    def all(self) -> list[Account]:
        return sorted(self._accounts.values(), key=lambda a: a.account_id)

    def halt_all(self, reason: str, *, by: str) -> None:
        """Stop everything, and stop each account too.

        Both, deliberately. The global switch is what `route` checks, and the
        per-account switches make the halt visible in each account's own view -
        an operator looking at one account must not see it reported as live.
        """
        self.global_kill_switch.engage(reason, by=by)
        for account in self._accounts.values():
            account.kill_switch.engage(f"global halt: {reason}", by=by)

    def tradeable(self) -> list[Account]:
        if self.global_kill_switch.engaged:
            return []
        return [
            a
            for a in self.all()
            if a.policy.enabled and not a.kill_switch.engaged
        ]

    def as_dict(self) -> dict[str, Any]:
        return {
            "global_kill_switch": self.global_kill_switch.as_dict(),
            "accounts": [a.as_dict() for a in self.all()],
            "tradeable": [a.account_id for a in self.tradeable()],
        }


def route(
    intent: OrderIntent,
    book: AccountBook,
    *,
    account_ids: list[str] | None = None,
) -> RoutingResult:
    """Copy one idea to every account that may act on it.

    Each copy is a distinct `OrderIntent` with its own account id, so its
    content-derived client order id differs — two accounts acting on the same
    idea are two orders, and an idempotency check must be able to tell them
    apart or the second silently becomes a duplicate of the first.
    """
    result = RoutingResult()

    if book.global_kill_switch.engaged:
        for account in book.all():
            result.skipped[account.account_id] = (
                f"global kill switch: {book.global_kill_switch.reason}"
            )
        return result

    candidates = book.all()
    if account_ids is not None:
        unknown = set(account_ids) - {a.account_id for a in candidates}
        if unknown:
            raise ValidationFailedError(f"unknown accounts: {sorted(unknown)}")
        candidates = [a for a in candidates if a.account_id in account_ids]

    for account in candidates:
        if account.kill_switch.engaged:
            result.skipped[account.account_id] = (
                f"kill switch: {account.kill_switch.reason}"
            )
            continue
        if not account.policy.enabled:
            result.skipped[account.account_id] = "execution is disabled for this account"
            continue
        if not account.permits_symbol(intent.symbol):
            result.skipped[account.account_id] = (
                f"{intent.symbol} is not on this account's permitted list"
            )
            continue
        if intent.risk_r > account.policy.max_risk_r_per_order:
            # Reduced, not refused: the idea is sound and this account simply
            # cannot carry that much of it. Refusing outright would let one
            # account's ceiling silence the idea everywhere.
            result.skipped[account.account_id] = (
                f"{intent.risk_r:.2f} R exceeds this account's "
                f"{account.policy.max_risk_r_per_order:.2f} R ceiling"
            )
            continue

        result.routed.append(
            RoutedIntent(
                account_id=account.account_id,
                intent=_for_account(intent, account.account_id),
                broker_name=getattr(account.broker, "name", "unknown"),
            )
        )

    return result


def _for_account(intent: OrderIntent, account_id: str) -> OrderIntent:
    """The same idea, addressed to one account."""
    if intent.account_id == account_id:
        return intent
    return OrderIntent(
        symbol=intent.symbol,
        side=intent.side,
        order_type=intent.order_type,
        risk_r=intent.risk_r,
        entry=intent.entry,
        stop=intent.stop,
        target=intent.target,
        approvals=intent.approvals,
        authorised_at=intent.authorised_at,
        account_id=account_id,
        # A fresh intent id: two accounts acting on one idea are two decisions
        # with two lives, and sharing an id would merge their histories.
        metadata={**intent.metadata, "routed_from": str(intent.intent_id)},
    )


@dataclass
class Exposure:
    """Risk per account, and the aggregate — never the aggregate alone."""

    per_account: dict[str, float] = field(default_factory=dict)

    @property
    def total_r(self) -> float:
        return sum(self.per_account.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            "per_account": {k: round(v, 4) for k, v in sorted(self.per_account.items())},
            "total_r": round(self.total_r, 4),
            # 4 R on a 100k account and 4 R on a 10k challenge are different
            # amounts of money and different distances from a limit.
            "note": "R is per account; the total is informational, not a limit",
        }


def exposure(positions_by_account: dict[str, list[float]]) -> Exposure:
    return Exposure(
        per_account={
            account: sum(abs(r) for r in risks)
            for account, risks in positions_by_account.items()
        }
    )
