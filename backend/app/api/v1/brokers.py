"""What this deployment is connected to, and what it is not (spec §4, §25).

Written because "which broker is this using?" had no answer anywhere. The
market-data provider was a setting, the execution broker was a class name, and
the MetaTrader install was a directory on the host that no part of the
application could see. Three different kinds of fact, none of them reachable.

Nothing here invents a broker. The obvious version of this endpoint is a
catalogue of firms and their MetaTrader server strings, and a wrong server
string is the worst possible thing to publish: it produces a connection that
never establishes, and the search for why goes everywhere except the list that
looked authoritative. A server name comes with the account, from the provider,
in writing. So this reports connections, not candidates.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import Principal, require
from app.brain import rulebooks as rulebook_module
from app.core.config import get_settings
from app.core.enums import Permission
from app.execution import broker as broker_module
from app.providers.metatrader import MetaTraderBridge, bridge_dirs
from app.services import mt5_link

router = APIRouter(prefix="/brokers", tags=["brokers"])

READ = Depends(require(Permission.READ))
#: Not EXECUTE. Connecting a terminal is not placing an order, and a route that
#: asks for more authority than it needs is how the two stop being separate.
#: Not SIMULATE either, which an analyst holds: handing a broker login to the
#: host agent is the point at which a deployment stops being a simulator.
BROKER_MANAGE = Depends(require(Permission.BROKER_MANAGE))

log = structlog.get_logger(__name__)


class LinkPayload(BaseModel):
    """A broker login, on its way to the terminal and nowhere else."""

    login: str = Field(min_length=4, max_length=12, description="MetaTrader account number")
    server: str = Field(min_length=3, max_length=64, description="Broker server name")
    # No example, and never echoed back in a response or a log line.
    password: str = Field(min_length=1, max_length=256, repr=False)
    #: Which terminal to apply it to. Blank lets the agent pick the first one
    #: that has never held an account, which is what "add my next account"
    #: almost always means.
    terminal: str | None = Field(default=None, max_length=32)


class ClearPayload(BaseModel):
    """Log one terminal out. Names its terminal, carries no credential."""

    terminal: str = Field(min_length=2, max_length=32)

#: Where MetaTrader lives on the host. The application runs in a container and
#: cannot see it, which is itself worth reporting rather than hiding: a bridge
#: has to cross that boundary, and until one does, "installed" and "reachable"
#: are separate facts.
MT5_TERMINAL_PATH = "~/.mt5/drive_c/Program Files/MetaTrader 5/terminal64.exe"


@router.get("")
def read_brokers(_: Principal = READ) -> dict[str, Any]:
    """Every connection this deployment has, and its state.

    Split by what each one actually does. A market-data provider and an
    execution broker are both "a broker" in conversation and are entirely
    different risks: one can only be wrong about the past, the other can lose
    money in the present.
    """
    settings = get_settings()
    # Read through as_dict rather than off the object: `simulated` is published
    # by the broker's own payload and is not an attribute, and reaching for it
    # directly is how this endpoint 500'd the first time it ran.
    paper = broker_module.PaperBroker().as_dict()

    return {
        "market_data": {
            "name": settings.collector_provider,
            "connected": True,
            "role": "prices and history",
            "note": (
                "free end-of-interval data. Good enough to measure structure, "
                "not good enough to model a spread: it carries no bid/ask, so "
                "every cost figure derived from it is an assumption"
            ),
        },
        "execution": {
            "name": paper["name"],
            "connected": True,
            "simulated": paper["simulated"],
            "role": "order placement",
            "note": (
                "a simulator. It fills against the price it is given and always "
                "charges slippage, so it cannot flatter a strategy - but it "
                "cannot reject an order for margin either, which a real broker "
                "will"
            ),
        },
        "metatrader": _metatrader_summary(),
        "challenge_providers": rulebook_module.providers(),
        "no_broker_catalogue_here": True,
        "why": (
            "a MetaTrader server name comes with the account, from the "
            "provider, in writing. Publishing a guessed one produces a "
            "connection that never establishes and a search for the reason "
            "that goes everywhere except the list that looked authoritative"
        ),
    }


def _metatrader_summary() -> dict[str, Any]:
    """Every terminal's live state, read from what its expert publishes.

    This block was once a hardcoded "no account, bridge not built yet" - true
    on the day it was written and false ever after, which meant the site's own
    brokers page denied eight running terminals. Everything here is now read
    from the bridge files at request time; when a terminal stops publishing,
    its row says so instead of the page saying nothing exists.
    """
    terminals: dict[str, Any] = {}
    connected = 0
    for key, path in sorted(bridge_dirs().items()):
        each = MetaTraderBridge(directory=path)
        account = each.account()
        terminals[key] = account
        # `connected` lives inside the bridge state, not beside the balance.
        if account.get("available") and account.get("state", {}).get("connected"):
            connected += 1

    return {
        "name": "MetaTrader 5",
        "installed_on_host": True,
        "reachable_from_application": connected > 0,
        "terminal_path": MT5_TERMINAL_PATH,
        "role": "prices, symbol specifications and order placement",
        "terminals": terminals,
        "connected_terminals": connected,
        "blocked_by": (
            []
            if connected
            else [
                "no terminal is currently publishing a connected account - "
                "add one on this page and the host agent applies it"
            ]
        ),
    }


@router.get("/link")
def read_link_state(_: Principal = READ) -> dict[str, Any]:
    """Whether a broker login can be applied at all right now.

    Published because the queue is a seam between two machines, and a seam
    nobody can see is one that fails silently. A queue directory that is not
    mounted looks exactly like a queue with nothing in it, so the depth is
    reported rather than summarised.
    """
    state = mt5_link.agent_state()
    return {
        **state,
        "how_it_works": (
            "the API writes a request here and a host agent applies it. The "
            "application cannot write MetaTrader's config or restart it "
            "directly: it runs in a container and the terminal runs on the "
            "host under Wine, and closing that gap by handing the container "
            "the host's systemd would be worse than the gap"
        ),
        "password_is_stored": False,
    }


@router.get("/link/{request_id}")
def read_link_result(request_id: str, _: Principal = READ) -> dict[str, Any]:
    """What the agent did with one request.

    "Not applied yet" and "applied and failed" are returned differently. A
    stopped agent and a rejected login need different fixes, and one answer for
    both sends the reader to the wrong one.
    """
    return mt5_link.result_for(request_id)


@router.post("/link")
def create_link(
    payload: LinkPayload,
    principal: Principal = BROKER_MANAGE,
) -> dict[str, Any]:
    """Hand a broker login to the host agent.

    Carries a permission above READ, which means an unauthenticated caller is
    refused before the body is read - `require()` enforces that for every
    permission above READ regardless of whether authentication is switched on.
    It deliberately does not carry EXECUTE: this connects a terminal, it does
    not place an order, and a route that asked for more authority than it needs
    would be the first step in blurring the two.

    `BROKER_MANAGE` rather than SIMULATE, which every analyst holds. Handing
    over a broker login is the moment a deployment stops being a simulator,
    and the roles that may do it are the ones whose accounts they are.

    The password is validated, written into the request, and kept nowhere in
    this application. MetaTrader holds it in its own config, which it would do
    whatever this endpoint did.
    """
    request = mt5_link.validate(payload.login, payload.server, payload.password)
    terminal = mt5_link.validate_terminal(payload.terminal)
    if terminal is not None:
        request = mt5_link.LinkRequest(
            login=request.login,
            server=request.server,
            password=request.password,
            terminal=terminal,
        )
    result = mt5_link.submit(request)
    body = result.as_dict()
    body["applied_by"] = "host agent"
    body["next"] = f"/api/v1/brokers/link/{result.request_id}"
    # Recorded so a connection attempt is never invisible afterwards. The login
    # and server are in it; the password is not, here or anywhere else.
    log.info(
        "broker.link_requested",
        request_id=result.request_id,
        login=result.login,
        server=result.server,
        queued=result.queued,
        tenant_id=str(principal.tenant_id) if principal.tenant_id else None,
    )
    return body


@router.post("/unlink")
def unlink_account(
    payload: ClearPayload,
    principal: Principal = BROKER_MANAGE,
) -> dict[str, Any]:
    """Log a terminal out and forget its login.

    The startup config is deleted and the terminal restarted with nothing to
    log into; the saved session inside its prefix goes too, or it would
    quietly log back in with remembered credentials and report itself cleared
    while trading the same account. Deactivate and delete are the same
    mechanical act here - what differs is bookkeeping, and the accounts table
    on the challenge page owns that.

    `BROKER_MANAGE`, exactly like linking. Disconnecting a terminal mid-trade
    is as much an act on the account as connecting it was.
    """
    request = mt5_link.validate_clear(payload.terminal)
    result = mt5_link.submit(request)
    body = result.as_dict()
    body["applied_by"] = "host agent"
    body["next"] = f"/api/v1/brokers/link/{result.request_id}"
    log.info(
        "broker.unlink_requested",
        request_id=result.request_id,
        terminal=payload.terminal,
        queued=result.queued,
        tenant_id=str(principal.tenant_id) if principal.tenant_id else None,
    )
    return body


@router.post("/disconnect")
def disconnect_account(
    payload: ClearPayload,
    principal: Principal = BROKER_MANAGE,
) -> dict[str, Any]:
    """Stop a terminal without forgetting the account it holds.

    The startup config stays, so connecting again is a start rather than a
    fresh registration and needs no password - which is the whole point,
    because this application stores none and any reconnect that needed one
    would have to begin keeping them.

    Distinct from `/unlink`, which forgets. Those were the same call until
    parking an account for an afternoon meant re-typing its credentials to
    get it back, and a system that makes people re-type passwords is a system
    that trains them to keep passwords somewhere convenient.

    `BROKER_MANAGE`: stopping a terminal mid-trade is as much an act on the
    account as starting it.
    """
    request = mt5_link.validate_power(payload.terminal, "stop")
    result = mt5_link.submit(request)
    body = result.as_dict()
    body["applied_by"] = "host agent"
    body["next"] = f"/api/v1/brokers/link/{result.request_id}"
    log.info(
        "broker.disconnect_requested",
        request_id=result.request_id,
        terminal=payload.terminal,
        queued=result.queued,
        tenant_id=str(principal.tenant_id) if principal.tenant_id else None,
    )
    return body


@router.post("/connect")
def connect_account(
    payload: ClearPayload,
    principal: Principal = BROKER_MANAGE,
) -> dict[str, Any]:
    """Start a terminal that still holds a login.

    Not a registration - that is `/link`, and it is the one that carries a
    password. This only turns on a terminal whose account is already in its
    own config, which is what makes it the counterpart to `/disconnect`.

    A terminal whose login was cleared will start and connect to nothing,
    which the metatrader endpoint already reports as its own state rather
    than as a failure.
    """
    request = mt5_link.validate_power(payload.terminal, "start")
    result = mt5_link.submit(request)
    body = result.as_dict()
    body["applied_by"] = "host agent"
    body["next"] = f"/api/v1/brokers/link/{result.request_id}"
    log.info(
        "broker.connect_requested",
        request_id=result.request_id,
        terminal=payload.terminal,
        queued=result.queued,
        tenant_id=str(principal.tenant_id) if principal.tenant_id else None,
    )
    return body


@router.get("/metatrader")
def read_metatrader(_: Principal = READ) -> dict[str, Any]:
    """What the terminal is actually reporting, right now.

    Three states, kept apart. Not running, running with nothing behind it, and
    running with a live account - the middle one is where this deployment sat
    for hours looking healthy, because the terminal was up and Market Watch was
    full of quotes cached from a session that had ended.
    """
    bridge = MetaTraderBridge()
    state = bridge.state()
    payload: dict[str, Any] = {"state": state.as_dict()}

    # Every terminal, not just the built-in one. The bridge map grew to eight
    # directories while this endpoint kept reporting the first, which read on
    # the site as seven connected accounts not existing.
    terminals: dict[str, Any] = {}
    for key, path in sorted(bridge_dirs().items()):
        each = MetaTraderBridge(directory=path)
        each_state = each.state()
        terminals[key] = {
            "state": each_state.as_dict(),
            "account": (
                each.account()
                if each_state.usable
                else {"available": False, "reason": each_state.reason}
            ),
        }
    payload["terminals"] = terminals

    if not state.usable:
        payload["account"] = {"available": False, "reason": state.reason}
        payload["symbols"] = {"available": False, "reason": state.reason}
        payload["next_step"] = (
            "add the account on this page. The terminal reads the login from "
            "its own config on start, so it stays connected across restarts "
            "once it is set"
        )
        return payload

    payload["account"] = bridge.account()
    payload["symbols"] = bridge.symbols()
    payload["positions"] = bridge.positions()
    payload["next_step"] = None
    return payload
