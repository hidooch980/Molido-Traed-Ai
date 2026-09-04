"""Read a terminal's display name, with its key as the fallback.

The same shape as `account_policy`, for the same reason: these are read
whenever a page or a digest lists the fleet, so they must not be a query
each time, and a rename made on the site must show without a restart. A
short time-to-live settles both.

**Absent is not blank.** A terminal with no row displays under its key, which
is what every terminal did before this table existed - so an empty table
changes nothing, and a database that cannot be read falls back the same way
rather than rendering a fleet of unnamed rows.

Nothing here resolves a label back to a terminal, and there is deliberately
no function that does. The key is the identity; a lookup by display name is
how an order reaches the wrong account by way of a word somebody typed.
"""

from __future__ import annotations

import re
import time
from typing import Any

from sqlalchemy import select

from app.core.errors import ValidationFailedError

#: How long a reading is reused. Long enough that listing eight terminals is
#: one query rather than eight, short enough that a rename is on the page
#: before anybody has finished wondering whether it saved.
CACHE_SECONDS = 20.0

#: What a label may be. Bounded because it lands in a table column, and
#: control characters are excluded because a name containing a newline or a
#: right-to-left override renders as something other than what was typed -
#: which in a list of accounts is the one place that matters.
MAX_LABEL = 60
_FORBIDDEN = re.compile(r"[\x00-\x1f\x7f\u200e\u200f\u202a-\u202e\u2066-\u2069]")

_cache: dict[str, str] = {}
_read_at: float = 0.0
#: Whether `_cache` is a reading or just an absence. Tracked separately
#: because an empty table is the ordinary state of a fresh deployment, and
#: testing the dict for truth would miss the cache on every call in exactly
#: the case the cache matters most.
_loaded: bool = False


def _load() -> dict[str, str]:
    """Every stored label, by terminal key. Empty on any failure."""
    from app.db.session import session_scope
    from app.models.terminal_name import TerminalName

    try:
        with session_scope() as session:
            rows = session.scalars(select(TerminalName)).all()
            return {str(row.terminal): str(row.label or "") for row in rows if row.label}
    except Exception:  # noqa: BLE001 - a display name never stops a fleet listing
        return {}


def all_names(*, now: float | None = None) -> dict[str, str]:
    """The label table, cached for `CACHE_SECONDS`."""
    global _read_at, _cache, _loaded

    moment = time.monotonic() if now is None else now
    if not _loaded or moment - _read_at >= CACHE_SECONDS:
        # Guarded here as well as inside `_load`, because the promise is that
        # a name lookup never breaks a page, and a promise resting on one
        # function's internals lasts until somebody edits that function.
        try:
            _cache = _load()
        except Exception:  # noqa: BLE001
            _cache = {}
        _read_at = moment
        _loaded = True
    return _cache


def invalidate() -> None:
    """Forget the cache, so the next read sees a rename immediately."""
    global _read_at, _cache, _loaded

    _cache = {}
    _read_at = 0.0
    _loaded = False


def label_for(terminal: str) -> str | None:
    """This terminal's display name, or None if it has not been given one."""
    return all_names().get(str(terminal)) or None


def display(terminal: str) -> str:
    """What to show for this terminal. Its label, or its key.

    Used where one string is wanted - a chat message, a digest line. Where
    there is room for both, show both: the label answers "which account is
    this" and the key is what every other page, log line and directory is
    named after, and a reader who sees only the label cannot get back.
    """
    return label_for(terminal) or str(terminal)


def clean(label: str, *, terminal: str, known: dict[str, Any] | list[str]) -> str:
    """A label fit to store, or a refusal saying why not.

    Refused rather than trimmed into shape. The two rejections here are both
    about a fleet listing where two rows read the same, which is the exact
    confusion this whole feature exists to remove - silently rewriting the
    name to something unambiguous would leave the operator believing a
    different name is in force.
    """
    text = " ".join(str(label or "").split())
    if not text:
        return ""

    if _FORBIDDEN.search(text):
        raise ValidationFailedError(
            "a terminal name may not contain control or direction-override "
            "characters. They render as something other than what was typed, "
            "which in a list of accounts is where somebody acts on the wrong "
            "row",
            terminal=terminal,
        )
    if len(text) > MAX_LABEL:
        raise ValidationFailedError(
            f"a terminal name may be up to {MAX_LABEL} characters",
            terminal=terminal,
        )

    keys = {str(k) for k in (known.keys() if isinstance(known, dict) else known)}
    if text in keys - {str(terminal)}:
        raise ValidationFailedError(
            f"{text!r} is another terminal's key. A name that is somebody "
            "else's identity is a name that sends an order to the wrong "
            "account by way of a word",
            terminal=terminal,
        )

    folded = text.casefold()
    for other, existing in all_names().items():
        if str(other) != str(terminal) and existing.casefold() == folded:
            raise ValidationFailedError(
                f"{other} is already called {existing!r}. Two terminals with "
                "one name is two rows that read the same, which is the "
                "confusion this name exists to remove",
                terminal=terminal,
            )
    return text


__all__ = [
    "CACHE_SECONDS",
    "MAX_LABEL",
    "all_names",
    "clean",
    "display",
    "invalidate",
    "label_for",
]
