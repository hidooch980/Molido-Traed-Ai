"""Read an account's own strategy and risk, with the deployment as fallback.

The settings live in a table so a page can change them without an SSH
session and a container recreate. This is the read side, and it has two jobs
that pull against each other: it is consulted dozens of times in a cycle, so
it must not be a query each time; and a change made on the page must take
effect without anybody restarting anything, so it must not be cached for
long.

A short time-to-live settles both. The table is read at most once every
`CACHE_SECONDS`, and a change is live within that - which on a cycle that
runs every fifteen minutes means the next cycle already has it.

**Absent is not zero.** A login with no row falls back to the deployment's
own figures, which is what every account did before the table existed. An
empty table therefore changes nothing, and a database that cannot be read
falls back the same way rather than refusing to size a trade - a settings
lookup must never be the reason an account stops trading.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select

#: How long a reading is reused. Long enough that a cycle does not query
#: sixty times, short enough that a change on the page is live before anybody
#: has finished wondering whether it took.
CACHE_SECONDS = 20.0

_cache: dict[str, dict[str, Any]] = {}
_read_at: float = 0.0
#: Whether `_cache` is a reading or just an absence.
#:
#: Tracked separately because an empty table is the ordinary state of a fresh
#: deployment, and testing the dict for truth meant every single call missed
#: the cache and queried - the exact behaviour the cache exists to prevent,
#: in the exact case it matters most.
_loaded: bool = False


def _load() -> dict[str, dict[str, Any]]:
    """Every stored policy, by login. Empty on any failure."""
    from app.db.session import session_scope
    from app.models.account_policy import AccountPolicy

    try:
        with session_scope() as session:
            rows = session.scalars(select(AccountPolicy)).all()
            return {str(row.login): row.as_dict() for row in rows}
    except Exception:  # noqa: BLE001 - a settings lookup never stops a trade
        return {}


def all_policies(*, now: float | None = None) -> dict[str, dict[str, Any]]:
    """The policy table, cached for `CACHE_SECONDS`."""
    global _read_at, _cache, _loaded

    moment = time.monotonic() if now is None else now
    if not _loaded or moment - _read_at >= CACHE_SECONDS:
        # Guarded here and not only inside `_load`, because the promise is
        # that a settings lookup never stops a trade - and a promise that
        # depends on one function's internals is a promise until somebody
        # edits that function.
        try:
            _cache = _load()
        except Exception:  # noqa: BLE001 - the fallback is the deployment's own figures
            _cache = {}
        _read_at = moment
        _loaded = True
    return _cache


def invalidate() -> None:
    """Forget the cache, so the next read sees a change immediately.

    Called by the route that writes a policy. Without it the operator saves a
    change, watches the page still show the old figure for twenty seconds,
    and reasonably concludes it did not save.
    """
    global _read_at, _cache, _loaded

    _cache = {}
    _read_at = 0.0
    _loaded = False


def risk_percent(login: str) -> float | None:
    """This account's own risk, or None to use the deployment's."""
    row = all_policies().get(str(login))
    if not row:
        return None
    value = row.get("risk_percent")
    if value is None:
        return None
    try:
        percent = float(value)
    except (TypeError, ValueError):
        return None
    # Zero would make R undefined and halt the account by a route that is not
    # the kill switch, which is where halting belongs.
    return percent if percent > 0 else None


def strategies(login: str) -> list[str] | None:
    """This account's own brains, or None to use the deployment's.

    An empty list reads as "not set here" rather than "trade nothing". A
    deliberate stop is the kill switch, and a settings row that silently
    means the same thing would be a second halt nobody can find.
    """
    row = all_policies().get(str(login))
    if not row:
        return None
    names = [str(name).strip() for name in (row.get("strategies") or []) if str(name).strip()]
    return names or None


__all__ = [
    "CACHE_SECONDS",
    "all_policies",
    "invalidate",
    "risk_percent",
    "strategies",
]
