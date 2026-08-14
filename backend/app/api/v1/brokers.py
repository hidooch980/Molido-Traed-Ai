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
from app.services import mt5_link

router = APIRouter(prefix="/brokers", tags=["brokers"])

READ = Depends(require(Permission.READ))
#: Not EXECUTE. Connecting a terminal is not placing an order, and a route that
#: asks for more authority than it needs is how the two stop being separate.
SIMULATE = Depends(require(Permission.SIMULATE))

log = structlog.get_logger(__name__)


class LinkPayload(BaseModel):
    """A broker login, on its way to the terminal and nowhere else."""

    login: str = Field(min_length=4, max_length=12, description="MetaTrader account number")
    server: str = Field(min_length=3, max_length=64, description="Broker server name")
    # No example, and never echoed back in a response or a log line.
    password: str = Field(min_length=1, max_length=256, repr=False)

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
        "metatrader": {
            "name": "MetaTrader 5",
            "installed_on_host": True,
            "reachable_from_application": False,
            "terminal_path": MT5_TERMINAL_PATH,
            "role": "prices, symbol specifications and order placement",
            "blocked_by": [
                "no account is logged in to the terminal, and MetaTrader "
                "returns no price and accepts no order until one is",
                "the MetaTrader Python package is Windows-only, so the "
                "application reaches the terminal through a bridge process "
                "rather than by importing it, and that bridge is not built yet",
            ],
        },
        "challenge_providers": rulebook_module.providers(),
        "no_broker_catalogue_here": True,
        "why": (
            "a MetaTrader server name comes with the account, from the "
            "provider, in writing. Publishing a guessed one produces a "
            "connection that never establishes and a search for the reason "
            "that goes everywhere except the list that looked authoritative"
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
    principal: Principal = SIMULATE,
) -> dict[str, Any]:
    """Hand a broker login to the host agent.

    Carries SIMULATE rather than READ, which means an unauthenticated caller is
    refused before the body is read - `require()` enforces that for every
    permission above READ regardless of whether authentication is switched on.
    It deliberately does not carry EXECUTE: this connects a terminal, it does
    not place an order, and a route that asked for more authority than it needs
    would be the first step in blurring the two.

    The password is validated, written into the request, and kept nowhere in
    this application. MetaTrader holds it in its own config, which it would do
    whatever this endpoint did.
    """
    request = mt5_link.validate(payload.login, payload.server, payload.password)
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
