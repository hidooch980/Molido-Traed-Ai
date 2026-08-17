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

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.core.config import get_settings
from app.core.enums import Permission
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

READ = Depends(require(Permission.READ))


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

    from app.services import realised as realised_service
    from app.workers import broker_offset

    measured = broker_offset.measure(session)
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
