"""The last order cycle's per-account outcome, kept where the chat channel can read it.

An account refused before it looked at a single signal - kill switch, order
authorization, risk brain, a stale terminal - writes nothing to the journal,
because the journal is per decision and no decision was reached. Those
refusals lived only in the `collector.orders_complete` log line, so the
Telegram `/why_no_trade` answer, which reads the journal, saw an empty
window and said the market was probably closed while every account was
being refused on an open market.

One small JSON file, overwritten each cycle: the collector writes it, the
chat container reads it (both mount `/var/lib/molido`). A file rather than a
table, because it is one current answer, not history - the log keeps that.
"""

from __future__ import annotations

import json
import os
import pathlib
from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger

log = get_logger(__name__)

DEFAULT_FILE = "/var/lib/molido/state/last-orders-cycle.json"


def _path() -> pathlib.Path:
    return pathlib.Path(os.environ.get("MOLIDO_LAST_CYCLE_FILE") or DEFAULT_FILE)


def write(
    *,
    orders: int,
    accounts: int,
    reason: Any,
    per_account: dict[str, Any],
    at: datetime | None = None,
) -> None:
    """Record this cycle's outcome. Never fatal: the cycle has already run."""
    record = {
        "at": (at or datetime.now(UTC)).isoformat(),
        "orders": orders,
        "accounts": accounts,
        "reason": reason,
        "per_account": per_account,
    }
    path = _path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, default=str), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        log.warning("last_cycle.unwritable", path=str(path), error=str(exc))


def read() -> tuple[dict[str, Any] | None, str]:
    """The last record, or None and the reason there is none."""
    path = _path()
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "no order cycle has recorded its outcome yet"
    except (OSError, ValueError) as exc:
        return None, f"the last cycle's record could not be read: {exc}"
    if not isinstance(record, dict):
        return None, "the last cycle's record is not an object"
    return record, ""
