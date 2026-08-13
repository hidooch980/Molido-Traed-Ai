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

from fastapi import APIRouter, Depends

from app.api.deps import Principal, require
from app.brain import rulebooks as rulebook_module
from app.core.config import get_settings
from app.core.enums import Permission
from app.execution import broker as broker_module

router = APIRouter(prefix="/brokers", tags=["brokers"])

READ = Depends(require(Permission.READ))

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
