"""The loop that trades without being asked, and the four gates it passes.

Everything this needs already existed and was never wired together: `decide()`
walks one instrument through every risk, portfolio and challenge gate;
`execute()` sends an order past preflight; `supervise()` watches what is open.
What was missing was the thing that calls them on a clock. This is that.

Four gates stand between a proposal and a live order, and they are separate on
purpose - collapsing any two means the person who opens the first also opens
the second without noticing:

  1. `decide()`      is this trade worth taking at all
  2. ExecutionPolicy is this deployment allowed to trade
  3. the edge gate   has anything been proven worth trading on
  4. preflight       is this specific order safe to send right now

The third is the one this file adds, and it is the one that matters most here.
A pipeline of refusals is not a strategy: every gate in `decide()` can only
stop a bad trade, and none of them produces a good one. What proposes a trade
is the brain, and the brain's edge over a random control currently measures
z = 1.10 against a required 1.96 - which is to say, not measurably different
from entering at random. Trading that live pays the spread on every round trip
for a return indistinguishable from zero, and the resulting slow bleed looks
exactly like an execution problem for months.

So paper mode is the default and needs no permission. It runs the whole loop
against live broker prices with live spreads, records what it would have done,
and never sends anything. That is not a lesser mode: it is the forward
measurement that would settle the question, on data nobody has searched
through, which is the one thing the historical work could not produce.

The edge gate can be overridden - it is the account holder's money and their
decision - but only through a setting whose name says what it does, and the
override is reported in every response so it cannot be forgotten once flipped.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import Timeframe
from app.learning import edge as edge_registry

#: What the loop is doing on this pass, and why it is doing that.
PAPER = "paper"
LIVE = "live"
HALTED = "halted"


@dataclass
class Intent:
    """One instrument's outcome on one pass."""

    symbol: str
    acted: bool
    stage: str
    reason: str
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "acted": self.acted,
            "stopped_at": self.stage,
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass
class Pass:
    """What one full sweep did, and what stopped it where."""

    mode: str
    at: datetime
    reason: str
    intents: list[Intent] = field(default_factory=list)
    edge_override: bool = False

    def as_dict(self) -> dict[str, Any]:
        acted = [i for i in self.intents if i.acted]
        return {
            "mode": self.mode,
            "at": self.at.isoformat(),
            "reason": self.reason,
            "considered": len(self.intents),
            "acted": len(acted),
            # Reported every time, not only when it is on. A switch that goes
            # quiet once flipped is a switch nobody remembers flipping.
            "edge_override_in_use": self.edge_override,
            "intents": [i.as_dict() for i in self.intents],
            "note": (
                "paper mode runs the whole loop against live broker prices and "
                "sends nothing. It is the forward measurement the historical "
                "work could not produce, not a lesser version of live"
                if self.mode == PAPER
                else None
            ),
        }


def mode_now() -> tuple[str, str, bool]:
    """Decide paper, live or halted before any instrument is looked at.

    Returns the mode, the reason, and whether the edge gate was overridden.
    Computed once per pass rather than per instrument: a mode that could change
    halfway through a sweep would send some orders and not others for reasons
    nobody could reconstruct afterwards.
    """
    settings = get_settings()

    if not getattr(settings, "enable_execution", False):
        return (
            HALTED,
            "execution is switched off for this deployment (MOLIDO_ENABLE_EXECUTION)",
            False,
        )

    if getattr(settings, "execution_dry_run", True):
        return (
            PAPER,
            "the deployment is in dry-run, so orders are recorded and not sent",
            False,
        )

    allowed, why = edge_registry.live_trading_allowed()
    override = bool(getattr(settings, "trade_without_proven_edge", False))

    if not allowed and not override:
        return PAPER, why, False

    if not allowed and override:
        # Permitted, and named for what it is on every single response. The
        # account holder may decide their own risk; they may not do it by
        # accident, and they may not forget they did.
        return (
            LIVE,
            (
                "live, with MOLIDO_TRADE_WITHOUT_PROVEN_EDGE set. No registered "
                f"edge clears the bar: {why}. Every order sent under this "
                "setting is a deliberate bet that the measurement is wrong"
            ),
            True,
        )

    return LIVE, why, False


def account_gate(account: dict[str, Any] | None) -> tuple[bool, str]:
    """Whether live orders may reach *this* account, whatever the mode says.

    Checked against what MetaTrader reports, never against the server name.
    "RoboForex-Pro" is a demo server and "…-Demo" is not a naming rule any
    broker is obliged to follow, so a guess from the name is how a funded
    account gets treated as practice.

    An account the bridge cannot describe is treated as real money. If the
    system does not know what it is about to trade, the safe assumption is the
    one that refuses: treating an unknown account as practice is the mistake
    that costs money, and the opposite costs a confirmation.
    """
    settings = get_settings()

    if not account or not account.get("available"):
        return False, (
            "the bridge cannot describe the account, so it is treated as real "
            "money and refused. An unknown account is the one case where "
            "guessing wrong costs something"
        )

    if not account.get("is_real_money"):
        mode = account.get("trade_mode")
        described = (
            _MODE_WORDS.get(mode, "not real money")
            if isinstance(mode, int)
            else "not real money"
        )
        return True, f"the terminal reports this account as {described}"

    if getattr(settings, "allow_real_money_orders", False):
        return True, (
            "real-money orders are permitted for this deployment "
            "(MOLIDO_ALLOW_REAL_MONEY_ORDERS). Every order sent is real"
        )

    return False, (
        "MetaTrader reports this as a real-money account, and real-money orders "
        "are switched off. This is deliberately a separate switch from the ones "
        "that enable execution: those are decisions about the deployment, this "
        "is a decision about the account, and the difference between practising "
        "and losing money should not ride on a flag set weeks ago for a demo"
    )


_MODE_WORDS = {0: "a demo", 1: "a contest", 2: "real money"}


def run_once(
    session: Session,
    *,
    instruments: list[tuple[uuid.UUID, str]] | None = None,
    timeframe: Timeframe = Timeframe.H1,
    now: datetime | None = None,
    decide_fn: Any = None,
    execute_fn: Any = None,
) -> Pass:
    """One sweep. Never raises for one instrument's failure.

    `decide_fn` and `execute_fn` are injected so a test exercises this loop's
    control flow - the order of the gates, what happens when one refuses - with
    the real functions in production and recording ones in a test. A loop that
    can only be tested by placing orders is a loop that is never tested.

    An instrument that raises is recorded and the sweep continues. One bad
    symbol must not stop the other fifty: a loop that dies on the first error
    trades nothing all day and reports nothing about why.
    """
    moment = now or datetime.now(UTC)
    mode, reason, override = mode_now()
    result = Pass(mode=mode, at=moment, reason=reason, edge_override=override)

    if mode == HALTED:
        return result

    if decide_fn is None:
        # Refused rather than defaulted, because mypy caught the alternative:
        # `decide` requires the account, the data health, the calibration and
        # the measured history, and it requires them because it must be
        # runnable over historical bars with the account state of that moment.
        # A loop that fetched "now" inside itself could never be backtested.
        #
        # Wiring those together is `context.build`, and passing it explicitly
        # is what keeps this loop testable: a version that quietly constructed
        # its own inputs would only be exercisable by placing real orders.
        result.reason = (
            "no decision function was supplied. `decide` needs the account, "
            "the data health, the calibration and the measured history for the "
            "moment being decided - see app.execution.context.build"
        )
        return result

    decide = decide_fn
    watchlist = instruments or []

    for instrument_id, symbol in watchlist:
        try:
            trace = decide(session, instrument_id, timeframe, as_of=moment)
        except Exception as problem:  # noqa: BLE001 - recorded, sweep continues
            result.intents.append(
                Intent(
                    symbol=symbol,
                    acted=False,
                    stage="decide",
                    reason=f"{type(problem).__name__} while deciding",
                )
            )
            continue

        cleared = bool(getattr(trace, "cleared", False))
        if not cleared:
            result.intents.append(
                Intent(
                    symbol=symbol,
                    acted=False,
                    stage=str(getattr(trace, "stopped_at", "decide")),
                    reason=str(getattr(trace, "reason", "a gate refused")),
                )
            )
            continue

        if mode == PAPER:
            # Recorded in full. The point of paper mode is the record: an
            # intent with no detail cannot be scored later, which would make
            # the whole forward measurement worthless.
            result.intents.append(
                Intent(
                    symbol=symbol,
                    acted=True,
                    stage="paper",
                    reason="would have traded; nothing was sent",
                    detail=_trace_detail(trace),
                )
            )
            continue

        if execute_fn is None:
            from app.execution import engine as engine_module

            execute_fn = engine_module.execute
        try:
            outcome = execute_fn(session, trace, as_of=moment)
        except Exception as problem:  # noqa: BLE001
            result.intents.append(
                Intent(
                    symbol=symbol,
                    acted=False,
                    stage="execute",
                    reason=f"{type(problem).__name__} while sending",
                )
            )
            continue

        result.intents.append(
            Intent(
                symbol=symbol,
                acted=bool(getattr(outcome, "submitted", False)),
                stage="execute",
                reason=str(getattr(outcome, "reason", "sent")),
                detail=_trace_detail(trace),
            )
        )

    return result


def _trace_detail(trace: Any) -> dict[str, Any]:
    """The numbers worth keeping from one decision.

    Deliberately small and deliberately fixed. A paper record that stores
    whatever the trace happened to expose changes shape whenever the trace does,
    and a forward measurement whose fields move cannot be scored across the
    period it was measuring.
    """
    return {
        "side": str(getattr(trace, "side", "") or ""),
        "entry": getattr(trace, "entry", None),
        "stop": getattr(trace, "stop", None),
        "target": getattr(trace, "target", None),
        "risk_r": getattr(trace, "risk_r", None),
        "conviction": getattr(trace, "conviction", None),
    }


@dataclass
class FleetPass:
    """One sweep across every account.

    The number that makes this possible on two cores: reading the market is
    done once and reused, and only the per-account gates run per account. A
    naive loop over 200 accounts x 51 instruments is 10,200 full analyses per
    pass, which this machine cannot do in a lifetime, let alone before the next
    bar. The market does not look different to account 7 than to account 143 -
    only the risk headroom, the open positions and the challenge rules differ,
    and those are cheap.
    """

    at: datetime
    mode: str
    reason: str
    accounts_considered: int = 0
    accounts_acted: int = 0
    shared_analyses: int = 0
    per_account: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "at": self.at.isoformat(),
            "mode": self.mode,
            "reason": self.reason,
            "accounts": {
                "considered": self.accounts_considered,
                "acted": self.accounts_acted,
                "skipped": len(self.skipped),
            },
            # Published because it is the whole argument for this design: one
            # analysis serves every account, so the cost of the pass grows with
            # the watchlist and barely at all with the number of accounts.
            "shared_analyses": self.shared_analyses,
            "per_account": self.per_account,
            "skipped_detail": self.skipped,
        }


def run_fleet(
    session: Session,
    *,
    instruments: list[tuple[uuid.UUID, str]] | None = None,
    timeframe: Timeframe = Timeframe.H1,
    now: datetime | None = None,
    analyse_fn: Any = None,
    apply_fn: Any = None,
    execute_fn: Any = None,
    max_accounts: int | None = None,
) -> FleetPass:
    """One pass over every active account, sharing the market analysis.

    Two stages, and the split is the point:

      `analyse_fn`  once per instrument. The expensive half - indicators,
                    regime, levels, conviction. Identical for every account.
      `apply_fn`    once per account per instrument. The cheap half - this
                    account's risk headroom, its open positions, its challenge
                    rulebook, its distance to its own daily floor.

    An account that raises is skipped and recorded; the fleet continues. One
    account with a bad rulebook must not stop the other hundred and ninety-nine.
    """
    moment = now or datetime.now(UTC)
    mode, reason, override = mode_now()
    result = FleetPass(at=moment, mode=mode, reason=reason)

    if mode == HALTED:
        return result

    from app.services import challenge_accounts

    # Unwrapped from their AccountView wrappers, which carry neither
    # `is_active` nor `label`: filtering the wrapper counts a switched-off
    # account as active, and labelling it names every account "".
    accounts = [
        view.account
        for view in challenge_accounts.listing(
            session, tenant_id=challenge_accounts.default_tenant(session)
        )
        if view.account.is_active
    ]
    if max_accounts is not None:
        accounts = accounts[:max_accounts]

    watchlist = instruments or []

    # ------------------------------------------------------- shared analysis
    shared: dict[uuid.UUID, Any] = {}
    failed_analyses: list[dict[str, str]] = []
    for instrument_id, _symbol in watchlist:
        if analyse_fn is None:
            break
        try:
            shared[instrument_id] = analyse_fn(session, instrument_id, timeframe, moment)
        except Exception as problem:  # noqa: BLE001 - one symbol, not the pass
            # Recorded rather than swallowed. A symbol that silently drops out
            # of every pass looks identical to one the market gave no signal
            # on, and the two need opposite responses.
            failed_analyses.append(
                {"symbol": _symbol, "reason": f"{type(problem).__name__} while analysing"}
            )
            continue
    result.skipped.extend(failed_analyses)
    result.shared_analyses = len(shared)

    # ---------------------------------------------------------- per account
    for account in accounts:
        result.accounts_considered += 1
        label = account.label or str(account.id)
        acted_here = 0
        intents: list[dict[str, Any]] = []

        try:
            for instrument_id, symbol in watchlist:
                analysis = shared.get(instrument_id)
                if analysis is None:
                    continue
                verdict = (
                    apply_fn(session, account, analysis, moment)
                    if apply_fn
                    else None
                )
                if verdict is None or not getattr(verdict, "cleared", False):
                    intents.append(
                        {
                            "symbol": symbol,
                            "acted": False,
                            "reason": str(getattr(verdict, "reason", "no verdict")),
                        }
                    )
                    continue

                if mode == PAPER:
                    intents.append(
                        {
                            "symbol": symbol,
                            "acted": True,
                            "reason": "would have traded; nothing was sent",
                            "detail": _trace_detail(verdict),
                        }
                    )
                    acted_here += 1
                    continue

                outcome = execute_fn(session, verdict, as_of=moment) if execute_fn else None
                sent = bool(getattr(outcome, "submitted", False))
                acted_here += 1 if sent else 0
                intents.append(
                    {
                        "symbol": symbol,
                        "acted": sent,
                        "reason": str(getattr(outcome, "reason", "sent")),
                    }
                )
        except Exception as problem:  # noqa: BLE001 - one account, not the fleet
            result.skipped.append(
                {"account": label, "reason": f"{type(problem).__name__} while applying"}
            )
            continue

        if acted_here:
            result.accounts_acted += 1
        result.per_account.append(
            {"account": label, "acted": acted_here, "intents": intents}
        )

    return result
