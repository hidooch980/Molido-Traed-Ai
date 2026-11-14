"""Shadow mode: run the v2 council, log the verdict, influence nothing.

`MOLIDO_AGENT_COUNCIL_LIVE` defaults off. Even when set, nothing in the
decision pipeline calls this module today - wiring it in is a separate,
owner-approved change, and the flag is reported so the state is visible.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

from app.agents.council.analysts import convene
from app.agents.council.credibility import CredibilityBook
from app.agents.council.meta import Verdict, aggregate
from app.agents.council.weights import WeightStore
from app.agents.risk_gate import RiskContext, review_council

FLAG = "MOLIDO_AGENT_COUNCIL_LIVE"
log = logging.getLogger("molido.agents.council")


def live_flag() -> bool:
    return os.environ.get(FLAG, "false").strip().lower() in {"1", "true", "yes"}


def evaluate(world: dict, *, store: WeightStore | None = None,
             book: CredibilityBook | None = None,
             sink: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    store = store or WeightStore()
    opinions = convene(world)
    verdict: Verdict = aggregate(opinions, store.current(), book)
    record = {
        "mode": "shadow",
        "live_flag": live_flag(),
        "wired_into_decisions": False,
        "symbol": world.get("symbol"),
        "timeframe": world.get("timeframe"),
        "verdict": verdict.as_dict(),
        "opinions": [o.as_dict() for o in opinions],
    }
    record["risk_review"] = review_council(record, RiskContext()).as_dict()
    log.info("agent council shadow verdict %s %s", record["symbol"], verdict.direction)
    if sink is not None:
        sink(record)
    return record
