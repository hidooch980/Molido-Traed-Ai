"""Receiving TradingView alerts: check the secret, keep the alert, act on nothing.

TradingView cannot sign a request. The only credential it can carry is text the
owner puts in the alert message, so the secret travels in the JSON body and is
compared in constant time against a stored hash. A burst limit per address
keeps a leaked URL from filling the table.

Nothing here imports execution or the pipeline; a test parses the imports.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import deque
from typing import Any

MAX_BODY_BYTES = 16_000
BURST = 30
BURST_WINDOW_SECONDS = 60.0
ACTIONS = frozenset({"buy", "sell", "long", "short", "close", "exit", "flat"})


def new_secret() -> str:
    return secrets.token_urlsafe(24)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def secret_matches(given: object, stored_hash: str) -> bool:
    if not stored_hash or not isinstance(given, str) or not given:
        return False
    return hmac.compare_digest(hash_secret(given), stored_hash)


def _text(value: object, limit: int) -> str:
    return str(value).strip()[:limit] if value is not None else ""


def parse(body: dict[str, Any]) -> dict[str, Any]:
    """The fields worth a column, and the rest kept without the secret."""
    kept = {k: v for k, v in body.items() if k != "secret"}
    action = _text(body.get("action") or body.get("side"), 16).lower()
    try:
        price: float | None = float(body["price"]) if body.get("price") is not None else None
    except (TypeError, ValueError):
        price = None
    return {
        "symbol": _text(body.get("symbol") or body.get("ticker"), 32).upper(),
        "action": action if action in ACTIONS else "",
        "price": price,
        "timeframe": _text(body.get("timeframe") or body.get("interval"), 16),
        "message": _text(body.get("message") or body.get("text"), 2000),
        "payload": kept,
    }


class BurstLimit:
    """At most `limit` requests per address in a sliding window, per process."""

    def __init__(self, limit: int = BURST, window: float = BURST_WINDOW_SECONDS) -> None:
        self.limit = limit
        self.window = window
        self._seen: dict[str, deque[float]] = {}

    def allow(self, address: str | None, now: float | None = None) -> bool:
        moment = time.monotonic() if now is None else now
        stamps = self._seen.setdefault(address or "-", deque())
        while stamps and moment - stamps[0] > self.window:
            stamps.popleft()
        if len(stamps) >= self.limit:
            return False
        stamps.append(moment)
        if len(self._seen) > 10_000:
            self._seen.clear()
        return True


LIMIT = BurstLimit()
