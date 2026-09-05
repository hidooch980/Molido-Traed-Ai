"""Execution, read-only (spec §22, §26).

This is the closest an endpoint gets to real money in this system, so what it
deliberately does *not* offer is the design:

**There is no route that places an order.** Not a disabled one, not one behind
a flag, not one that returns 501. The execution engine is importable and this
module never calls `execute`. Adding a route that did would make it a mutating
route, and `app.api.guard` refuses to let the application start with a mutating
route that has no permission dependency — so the first person to try gets a
boot failure rather than a live order.

**There is no route that disengages the kill switch.** Disengaging is a human
act performed on the server, and a switch that can be opened by anything
holding an HTTP client is not a switch. `KillSwitch.disengage` requires an
attributable actor and has no caller anywhere in this package.

What is here is the checklist: what would happen to a proposed order, and why.
`/preflight` runs the real `preflight` function against a real intent, so the
answer is the answer the engine would give rather than a description of it.
An operator asking "why would this be refused" gets the list, and every item on
it is a separate decision somebody has to make deliberately.
"""

from __future__ import annotations

import pathlib
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.core.config import get_settings
from app.core.enums import Permission
from app.core.errors import ValidationFailedError
from app.db.session import get_db
from app.execution import broker as broker_module
from app.execution import engine as engine_module
from app.execution import routing as routing_module
from app.execution import safety as safety_module
from app.execution.contracts import (
    Approval,
    OrderIntent,
    OrderSide,
    OrderType,
    can_transition,
)
from app.execution.contracts import OrderState as State

router = APIRouter(prefix="/execution", tags=["execution"])


def _get_db_for_authorization():
    """A session for the authorization route; local import keeps this file's
    import list what it was."""
    from app.db.session import get_db

    yield from get_db()

READ = Depends(require(Permission.READ))
SIMULATE = Depends(require(Permission.SIMULATE))
#: Changing what an account trades and how much it risks is a configuration
#: authority, not a trading one, and the difference matters: a key that can
#: place orders must not be able to raise its own risk limit. That is
#: privilege escalation with extra steps, and EXECUTE - the first choice
#: here - would have granted exactly it.
#:
#: BROKER_MANAGE already gates connecting a live account, which is the
#: strictly larger power: whoever may point this system at real money may
#: also say how much of it goes behind one stop.
POLICY_MANAGE = Depends(require(Permission.BROKER_MANAGE))


def _policy() -> safety_module.ExecutionPolicy:
    settings = get_settings()
    return safety_module.ExecutionPolicy(
        enabled=settings.enable_execution,
        dry_run=settings.execution_dry_run,
        require_auth=settings.require_auth,
        max_risk_r_per_order=settings.max_risk_r_per_order,
    )


@router.get("/policy")
def read_policy(_: Principal = READ) -> dict[str, Any]:
    """The four switches, and the fact that they are four rather than one.

    Turning execution on and turning simulation off are separate decisions. A
    single flag would mean the first person to enable the engine also silently
    enabled live orders.
    """
    policy = _policy()
    switch = safety_module.KillSwitch()
    return {
        "execution_enabled": policy.enabled,
        "dry_run": policy.dry_run,
        "require_auth": policy.require_auth,
        "max_risk_r_per_order": policy.max_risk_r_per_order,
        "kill_switch_default_engaged": switch.engaged,
        "kill_switch_reason": switch.reason,
        "required_approvals": list(safety_module.REQUIRED_APPROVALS),
        "max_authorisation_age_seconds": safety_module.MAX_AUTHORISATION_AGE_SECONDS,
        "broker": broker_module.PaperBroker().as_dict(),
        "api_can_place_orders": False,
        "api_can_disengage_kill_switch": False,
        "note": (
            "no route in this API places an order or opens the kill switch; "
            "the execution gate refuses to start the app if one is ever added "
            "without a permission dependency"
        ),
    }


@router.get("/preflight")
def read_preflight(
    symbol: str = Query(default="EURUSD", min_length=1),
    side: str = Query(default="buy", pattern="^(buy|sell)$"),
    risk_r: float = Query(default=1.0, gt=0),
    entry: float = Query(default=1.1000, gt=0),
    stop: float = Query(default=1.0950, gt=0),
    approvals: str = Query(
        default="risk,portfolio,challenge,stress",
        description="Comma-separated layers that approved. Omit one to see it block.",
    ),
    _: Principal = READ,
) -> dict[str, Any]:
    """Run the real checklist against a proposed order.

    The intent is constructed and passed to the same `preflight` the engine
    calls, so this reports what would happen rather than describing it. A
    description can drift from the code; this cannot.
    """
    now = datetime.now(UTC)
    granted = {a.strip() for a in approvals.split(",") if a.strip()}

    try:
        intent = OrderIntent(
            symbol=symbol.upper(),
            side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
            order_type=OrderType.MARKET,
            risk_r=risk_r,
            entry=entry,
            stop=stop,
            target=None,
            approvals=tuple(
                Approval(source, True, "supplied by the caller", now)
                for source in sorted(granted)
            ),
            authorised_at=now,
            account_id="preview",
        )
    except Exception as exc:  # noqa: BLE001 - the refusal is the answer
        return {
            "cleared": False,
            "blocks": [str(exc)],
            "note": "the intent could not be constructed, so nothing was checked",
        }

    result = safety_module.preflight(
        intent,
        policy=_policy(),
        kill_switch=safety_module.KillSwitch(),
        already_submitted=None,
        now=now,
    )
    payload = result.as_dict()
    payload["client_order_id"] = intent.client_order_id
    payload["approvals_supplied"] = sorted(granted)
    payload["approvals_required"] = list(safety_module.REQUIRED_APPROVALS)
    return payload


@router.get("/order-states")
def read_order_states(_: Principal = READ) -> dict[str, Any]:
    """The state machine, and the transitions it refuses.

    Published because UNKNOWN is the state people get wrong. A submission that
    timed out may have filled; treating that as a rejection is how a system
    opens a second position on top of one it does not know it has.
    """
    states = [s.value for s in State]
    return {
        "states": states,
        "terminal": sorted(s.value for s in engine_module.TERMINAL_STATES)
        if hasattr(engine_module, "TERMINAL_STATES")
        else ["filled", "cancelled", "rejected"],
        "transitions": {
            current.value: sorted(
                following.value for following in State if can_transition(current, following)
            )
            for current in State
        },
        "unknown_means": (
            "the broker did not answer. It is not a rejection: the order may be "
            "live, and it resolves by asking rather than by assuming"
        ),
        "note": "no terminal state has a way out; a filled order cannot become rejected",
    }


@router.get("/guardian")
def read_guardian(
    broker_positions: str = Query(
        default="",
        description="SYMBOL:side:qty:stop, comma separated. `stop` may be omitted.",
    ),
    expected_positions: str = Query(default=""),
    _: Principal = READ,
) -> dict[str, Any]:
    """Compare what a broker holds with what the system believes it holds.

    Both directions are checked and they mean different things. A position at
    the broker that this system did not open is the louder finding: every risk
    figure is understated until it is explained.
    """

    def parse(raw: str) -> list[engine_module.Position]:
        out: list[engine_module.Position] = []
        for entry in (e.strip() for e in raw.split(",") if e.strip()):
            parts = entry.split(":")
            if len(parts) < 3:
                continue
            try:
                stop = float(parts[3]) if len(parts) > 3 and parts[3] else None
                out.append(
                    engine_module.Position(
                        symbol=parts[0].upper(),
                        side="sell" if parts[1].lower().startswith("s") else "buy",
                        quantity=float(parts[2]),
                        stop=stop,
                    )
                )
            except ValueError:
                continue
        return out

    report = engine_module.supervise(
        broker_positions=parse(broker_positions),
        expected_positions=parse(expected_positions),
        log=engine_module.SubmissionLog(),
    )
    return report.as_dict()


@router.get("/accounts")
def read_accounts(_: Principal = READ) -> dict[str, Any]:
    """Which accounts exist, and the switch above all of them.

    This used to return an empty list with the sentence "registering one
    requires a broker adapter, and the only adapter here is a simulator". That
    was true when it was written and stopped being true the day a MetaTrader
    adapter existed and a connected account filled an order - at which point it
    became a false statement the site made about itself, which is the exact
    failure this project has already been caught by once.

    So the account is read from the terminal rather than from a list somebody
    has to remember to update. If the bridge reports a login, it appears here.
    If it does not, the response says nothing is connected rather than implying
    nothing can be.
    """
    from app.execution.metatrader_broker import MetaTraderBroker
    from app.providers.metatrader import MetaTraderBridge

    book = routing_module.AccountBook()
    published = MetaTraderBridge().account()
    login = str(published.get("login") or "") if published.get("available") else ""

    if login:
        # The same policy every other route here uses, not a second one
        # built beside it - two policies that agree today do not stay agreeing.
        policy = _policy()
        book.add(
            routing_module.Account(
                account_id=login,
                broker=MetaTraderBroker(),
                policy=policy,
                label=str(published.get("server") or "broker"),
            )
        )

    payload = book.as_dict()
    payload["reason"] = (
        f"account {login} is connected through the MetaTrader bridge"
        if login
        else (
            "no account is connected. The bridge publishes no login, which "
            "means the terminal is down or not signed in - not that this "
            "deployment cannot hold one"
        )
    )
    # Read from the terminal, never inferred from the server name. An absent
    # field is treated as real money everywhere else in this system and is
    # reported as unknown here rather than as a demo.
    payload["live_account"] = {
        "login": login or None,
        "server": published.get("server"),
        "trade_mode": published.get("trade_mode"),
        "is_demo": published.get("trade_mode") == 0,
        "balance": published.get("balance"),
        "equity": published.get("equity"),
        "currency": published.get("currency"),
    }
    # Every configured terminal, not just the built-in one. The single
    # `live_account` above predates the fleet and stays for the pages that
    # read it; this is the row-per-account truth the fleet pages want, read
    # from each terminal's own bridge so a disconnected one is named rather
    # than shown as zeros.
    from app.providers.metatrader import bridge_dirs

    fleet: list[dict[str, Any]] = []
    for key, directory in sorted(bridge_dirs().items()):
        seen = MetaTraderBridge(directory=directory).account()
        if not seen.get("available"):
            fleet.append(
                {
                    "terminal": key,
                    "connected": False,
                    "reason": seen.get("reason"),
                }
            )
            continue
        balance = float(seen.get("balance") or 0.0)
        equity = float(seen.get("equity") or 0.0)
        fleet.append(
            {
                "terminal": key,
                "connected": True,
                "login": str(seen.get("login") or "") or None,
                "server": seen.get("server"),
                "is_demo": seen.get("trade_mode") == 0,
                "balance": balance,
                "equity": equity,
                "floating_pl": round(equity - balance, 2),
                "margin": seen.get("margin"),
                "currency": seen.get("currency"),
            }
        )
    payload["fleet"] = fleet
    payload["global_kill_switch_defaults_engaged"] = True
    payload["note"] = (
        "exposure is tracked per account and never as a single total: 4 R on a "
        "100k account and 4 R on a 10k challenge are different money"
    )
    return payload


@router.get("/equity")
def read_equity(
    session: Session = Depends(get_db),
    limit: int = Query(default=500, ge=1, le=5000),
    _: Principal = READ,
) -> dict[str, Any]:
    """One account's recorded equity, and what it did.

    The samples have been written every fifteen minutes since the collector
    started and nothing ever read them back - the curve existed and no page
    could show it, which is the same shape of gap as an order path that could
    not place an order.

    The account is read from the terminal rather than taken as a parameter.
    There is one connected account, and letting a caller name a different one
    would return an empty curve that looks like a flat account rather than like
    a question about the wrong account.
    """
    from app.providers.metatrader import MetaTraderBridge
    from app.services import equity as equity_service

    published = MetaTraderBridge().account()
    login = str(published.get("login") or "") if published.get("available") else ""
    if not login:
        return {
            "available": False,
            "reason": (
                "no account is connected, so there is no equity to read. The "
                "bridge publishes no login - the terminal is down or not "
                "signed in"
            ),
            "points": [],
        }

    known = equity_service.series(session, login)
    points = equity_service.curve(session, login, limit=limit)

    return {
        "available": bool(points),
        "account": login,
        "points": points,
        "summary": known.as_dict(),
        "reason": (
            None
            if points
            else (
                f"account {login} is connected but has no recorded samples "
                "yet. The collector writes one every cycle, so this fills in "
                "within minutes of it running"
            )
        ),
        "note": (
            "equity below balance at a point is open positions carrying their "
            "entry spread, which is a cost rather than a result"
        ),
    }


@router.get("/realised")
def read_realised(
    session: Session = Depends(get_db),
    days: int = Query(default=30, ge=1, le=365),
    _: Principal = READ,
) -> dict[str, Any]:
    """Closed trades and what they actually earned, net of everything.

    The one figure the platform could not compute. Every page showed floating
    profit; a closed trade leaves the positions file entirely, so an account
    could be up on the day and nothing would say so.

    The broker's clock offset is measured, not assumed - the same alignment
    that fixed the bar series, because reading these stamps as UTC would put
    every close three hours in the future on this broker.
    """
    from datetime import timedelta

    from app.core.enums import Timeframe
    from app.providers.metatrader import DEFAULT_BRIDGE_DIR
    from app.services import realised as realised_service
    from app.workers import broker_bars

    # Measured from the *files* the bridge publishes, not from the stored
    # series. Those two answer different questions and the difference is not
    # cosmetic: stored broker bars have already had the offset applied, so
    # aligning them against the public feed now correctly returns 0 - while
    # the deal file still carries raw terminal stamps at +3.
    #
    # Using the stored-series figure here would have put every close three
    # hours in the future. That is the identical bug that shifted the whole
    # bar series, in a new file, and it read as a healthy zero.
    measured = broker_bars._measure_offset(
        session, pathlib.Path(DEFAULT_BRIDGE_DIR), Timeframe.H1
    )
    since = datetime.now(UTC) - timedelta(days=days)

    payload = realised_service.read(
        offset_hours=float(measured.hours or 0),
        since=since,
    )
    # Published so a reader can tell a clock nobody could measure from a
    # window that genuinely holds nothing.
    payload["clock_offset"] = measured.as_dict()
    payload["window_days"] = days
    return payload


@router.get("/autopilot")
def read_autopilot(
    _: Principal = READ,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """What the autopilot would do right now, and every gate standing in its way.

    A read, not a run. Four separate gates decide whether an order can be sent,
    and an operator looking at a system that is not trading needs to see which
    one is shut - "it is not trading" is not an answer, and a single boolean
    would make four different situations look identical.
    """
    from app.execution import autopilot, context
    from app.learning import edge as edge_registry
    from app.providers.metatrader import MetaTraderBridge

    mode, reason, override = autopilot.mode_now()
    published = MetaTraderBridge().account()
    account_ok, account_why = autopilot.account_gate(published)
    edge_ok, edge_why = edge_registry.live_trading_allowed()
    built = context.build(session)

    return {
        "mode": mode,
        "reason": reason,
        "would_send_live_orders": mode == autopilot.LIVE and account_ok,
        "gates": {
            "execution_enabled": {
                "open": mode != autopilot.HALTED,
                "detail": reason if mode == autopilot.HALTED else "execution is enabled",
            },
            "proven_edge": {"open": edge_ok, "detail": edge_why},
            "account": {"open": account_ok, "detail": account_why},
            "inputs": {
                "open": built is not None,
                "detail": (
                    "the account is readable"
                    if built
                    else "no account is connected, so no decision can be made"
                ),
            },
        },
        "edge_override_in_use": override,
        "context": built.as_dict() if built else None,
        "rejected_claims": [claim.as_dict() for claim in edge_registry.REJECTED],
        "note": (
            "paper mode runs the whole loop against live broker prices and sends "
            "nothing. It is the forward measurement the historical work could "
            "not produce, not a lesser version of live"
        ),
    }


@router.get("/positions")
def read_positions(_: Principal = READ) -> dict[str, Any]:
    """What is open at the broker right now.

    Read from the bridge rather than from anything this system believes it
    opened. The two disagree exactly when it matters - an order that filled
    without the reply arriving, a position closed by the broker's own stop -
    and the broker's answer is the one the account is judged on.
    """
    from app.providers.metatrader import MetaTraderBridge

    bridge = MetaTraderBridge()
    published = bridge.positions()
    account = bridge.account()

    return {
        **published,
        "account": {
            "login": account.get("login"),
            "server": account.get("server"),
            "equity": account.get("equity"),
            "balance": account.get("balance"),
        }
        if account.get("available")
        else None,
        "note": (
            "read from the terminal, not from this system's own record. They "
            "disagree exactly when it matters, and the broker's answer is the "
            "one the account is judged on"
        ),
    }


@router.get("/control")
def read_control(_: Principal = READ) -> dict[str, Any]:
    """The random benchmark the live results will be measured against.

    Published now rather than derived later. A benchmark chosen after the
    results are in is a benchmark chosen to make them look a particular way,
    which is the thing pre-registration exists to prevent - and this project has
    already had one CONFIRMED that was wrong for exactly that reason.
    """
    from app.learning import control as control_module

    return {
        "seed": control_module.SEED,
        "how_it_works": (
            "for every bar the brain decides on, a control entry is derived "
            "from a hash of the seed, the symbol and the instant. Same bar, "
            "same stop, same target - only the direction differs, and the "
            "direction is what the brain claims to know"
        ),
        "why": (
            "a rule that beats breakeven while not beating a coin flip on the "
            "same bars has beaten nothing. A script in this project printed "
            "CONFIRMED on a 50.84% hit rate whose control scored 50.32%"
        ),
        "sample_needed": {
            "for_a_2pp_edge": control_module.Comparison(
                rule_wins=0, rule_losses=0, control_wins=0, control_losses=0
            ).trials_needed(for_edge=0.02),
            "for_a_half_pp_edge": control_module.Comparison(
                rule_wins=0, rule_losses=0, control_wins=0, control_losses=0
            ).trials_needed(for_edge=0.005),
            "note": "per arm, at z = 1.96",
        },
    }


class AccountStatePayload(BaseModel):
    """Pausing or resuming one account."""

    active: bool
    by: str = Field(min_length=1, max_length=80)
    reason: str = Field(default="", max_length=400)


@router.get("/accounts/state")
def account_states(
    _: Principal = READ,
) -> dict[str, Any]:
    """Which accounts may trade, and why not when they may not."""
    from app.execution import account_switch
    from app.providers.metatrader import bridge_dirs

    return {"accounts": account_switch.listing(list(bridge_dirs()))}


@router.post("/accounts/{account_key}/state")
def set_account_state(
    account_key: str,
    payload: AccountStatePayload,
    _: Principal = SIMULATE,
) -> dict[str, Any]:
    """Pause or resume one account.

    Behind SIMULATE, the tier the rest of the risk configuration sits at -
    registering a challenge account and its drawdown limits is already here.

    Resuming does not place an order and cannot cause one on its own. Every
    gate still runs afterwards: the global kill switch, the autopilot mode,
    the risk brain, the rulebook, the news window, the spread ceiling. What
    this grants is permission for those gates to be *asked*, not permission
    to pass them.

    It does not touch the global kill switch, and cannot. A control that could
    quietly release a fleet-wide halt by resuming the last account would make
    the halt mean less than it says.
    """
    from app.execution import account_switch
    from app.providers.metatrader import bridge_dirs

    known = bridge_dirs()
    if account_key not in known:
        # Named rather than created. Writing a state file for an account that
        # does not exist leaves a control nothing reads, which is worse than
        # refusing: somebody would set it and believe it took.
        raise ValidationFailedError(
            f"no account {account_key!r} is configured. Known: "
            f"{', '.join(sorted(known)) or '(none)'}"
        )

    account_switch.write(
        account_key,
        active=payload.active,
        by=payload.by,
        reason=payload.reason,
    )
    allowed, why = account_switch.state(account_key)
    return {
        "account": account_key,
        "active": allowed,
        "reason": why,
        "note": (
            "the global kill switch is separate and is not affected by this. "
            "While it is engaged no account trades, however this reads"
        ),
    }


# ------------------------------------------------------------ authorization
#
# Appended below the routes it summarises. The three states this returns are
# the ones `app.ops.authorization` refuses to conflate: the engine running,
# the kill switch released, and an order authorised are three facts, and a
# dashboard that shows one and implies the others is the failure this exists
# to end.


@router.get("/authorization")
def read_authorization(
    _: Principal = READ,
    session: Session = Depends(_get_db_for_authorization),
) -> dict[str, Any]:
    """May an order go right now, and every reason it may not.

    Recomputed from live facts on every call; nothing is cached and nothing
    is inferred from the engine being on. The account and risk gates show as
    unobserved here because only the trading cycle holds a terminal's
    publication and the risk brain's verdict; the cycle's own decision is
    written to the audit trail as `execution.authorization`.
    """
    from datetime import UTC as _UTC
    from datetime import datetime as _datetime

    from app.ops import posture as posture_module

    posture = posture_module.gather(session, now=_datetime.now(_UTC))
    payload = posture.decision.as_dict()
    payload["readiness"] = {
        "safe_to_trade": posture.report.safe_to_trade,
        "blocking_failures": [c.name for c in posture.report.blocking_failures],
        "important_failures": [c.name for c in posture.report.important_failures],
    }
    payload["details"] = posture.details
    payload["reader_failures"] = posture.reader_failures
    return payload


class AccountPolicyPayload(BaseModel):
    """What one account trades and how much it risks."""

    #: Empty means "not set here" and the deployment's assignment applies. It
    #: is never a way to stop an account - that is the kill switch, and a
    #: settings field that quietly did the same would be a second halt
    #: nobody can find.
    strategies: list[str] = Field(default_factory=list, max_length=12)
    risk_percent: float | None = Field(default=None, gt=0, le=5.0)


@router.get("/accounts/{login}/policy")
def read_account_policy(login: str, _: Principal = READ) -> dict[str, Any]:
    """This account's stored settings, and what is actually in force.

    Both, because they differ: a login with nothing stored is running on the
    deployment's figures, and a page that showed only the stored row would
    render an empty form for an account that is very much trading.
    """
    from app.services import account_policy
    from app.workers.autotrade import _risk_percent, _strategy_for

    stored = account_policy.all_policies().get(str(login))
    names, refusal = _strategy_for(str(login))
    return {
        "login": login,
        "stored": stored,
        "in_force": {
            "risk_percent": _risk_percent(str(login)),
            "strategies": sorted(names) if names else [],
            "refused": None if names else refusal,
        },
        "available_strategies": _available_strategies(),
        "max_risk_percent": _max_account_risk_percent(),
    }


@router.put("/accounts/{login}/policy")
def write_account_policy(
    login: str,
    payload: AccountPolicyPayload,
    session: Session = Depends(get_db),
    principal: Principal = POLICY_MANAGE,
) -> dict[str, Any]:
    """Set what this account trades and how much it risks.

    Behind BROKER_MANAGE rather than EXECUTE. Changing a risk limit is a
    configuration authority and placing an order is a trading one, and a key
    that can do the second must not be able to raise the ceiling on itself -
    that is privilege escalation with extra steps.

    A strategy nothing registered is refused here rather than at cycle time.
    The cycle already refuses it - loudly, and by name - but an operator who
    mistypes a brain on a page should be told while the page is still open,
    not by an account that quietly stops trading.
    """
    from app.learning import rules as rules_module
    from app.models.account_policy import AccountPolicy
    from app.services import account_policy

    unknown = sorted({n for n in payload.strategies if rules_module.get(n) is None})
    if unknown:
        raise ValidationFailedError(
            "no brain is registered under "
            + ", ".join(repr(n) for n in unknown)
            + ". Known: "
            + ", ".join(sorted(rules_module.names()))
        )

    row = session.scalar(select(AccountPolicy).where(AccountPolicy.login == str(login)))
    if row is None:
        row = AccountPolicy(login=str(login))
        session.add(row)
    row.strategies = list(payload.strategies)
    row.risk_percent = payload.risk_percent
    row.changed_by = str(getattr(principal, "subject", "") or "")[:120]
    session.commit()

    # Otherwise the operator saves, sees the old figure for twenty seconds,
    # and reasonably concludes it did not save.
    account_policy.invalidate()

    from app.workers.autotrade import _risk_percent, _strategy_for

    names, refusal = _strategy_for(str(login))
    return {
        "login": login,
        "stored": row.as_dict(),
        "in_force": {
            "risk_percent": _risk_percent(str(login)),
            "strategies": sorted(names) if names else [],
            "refused": None if names else refusal,
        },
    }


def _available_strategies() -> list[str]:
    from app.learning import rules as rules_module

    return sorted(rules_module.names())


def _max_account_risk_percent() -> float:
    from app.workers.autotrade import MAX_ACCOUNT_RISK_PERCENT

    return float(MAX_ACCOUNT_RISK_PERCENT)
