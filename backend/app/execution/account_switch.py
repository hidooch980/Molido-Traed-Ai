"""Turning one account off without turning the others off.

The global kill switch is a fleet-wide halt and is deliberately blunt: it
stops everything, and a halt that leaves some accounts trading is not what
anybody reaches for it to do. This is the other thing - one account paused
while the rest carry on, because a terminal is being reconnected, a challenge
has been failed, or that broker is having a bad afternoon.

Kept apart from the global switch on purpose. Two controls that can both stop
trading are easier to reason about than one control with a scope argument,
and the failure they guard against is different: the global one guards against
*anything* being wrong, this one against one account being wrong.

**Files, not the database.** Same reasoning as the kill switch: a control that
cannot be read when the database is unreachable is a control that fails when
it is most likely to be wanted. One small file per account, in the directory
the kill switch already lives in.

**A configured account defaults to on.** Unlike the global switch, which
starts engaged because nobody has said trading is allowed yet. Adding an
account to the bridge map is already a deliberate act by somebody with shell
access; requiring a second deliberate act to make the first one mean anything
would be ceremony rather than safety. What is not automatic is *un*pausing:
that writes a file with a name on it, the same as the kill switch.

**A file that cannot be read pauses the account.** Missing means on, because
missing is the ordinary state. Present-but-unreadable means something wrote
something unexpected there, and the safe reading of an unexpected control is
not "carry on".
"""

from __future__ import annotations

import json
import os
import pathlib
import tempfile
from datetime import UTC, datetime
from typing import Any

#: Where the per-account files live. Beside the kill switch, on the host, so a
#: redeploy cannot quietly resume an account somebody paused.
DEFAULT_STATE_DIR = pathlib.Path(
    os.environ.get("MOLIDO_ACCOUNT_STATE_DIR") or "/var/lib/molido/accounts"
)

PAUSED = "paused"
ACTIVE = "active"


def _path(account_key: str, directory: pathlib.Path | str | None = None) -> pathlib.Path:
    root = pathlib.Path(directory or DEFAULT_STATE_DIR)
    # Only the characters a filename can carry without surprising anybody.
    # An account key is chosen by whoever edits the bridge map, and a key with
    # a slash in it would write outside this directory.
    safe = "".join(c for c in account_key if c.isalnum() or c in "-_.")
    if not safe:
        safe = "unnamed"
    return root / f"{safe}.json"


def state(
    account_key: str, directory: pathlib.Path | str | None = None
) -> tuple[bool, str]:
    """Whether this account may trade, and why not when it may not.

    Never raises. A control that can throw on the read path takes down the
    caller that was about to consult it.
    """
    where = _path(account_key, directory)
    try:
        body = json.loads(where.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return True, ""
    except (OSError, ValueError) as problem:
        return False, (
            f"the state file for {account_key} could not be read "
            f"({type(problem).__name__}), and an unreadable control pauses "
            "rather than carries on"
        )

    if not isinstance(body, dict):
        return False, f"the state file for {account_key} is not an object, so it pauses"

    said = body.get("state")
    if said == ACTIVE:
        return True, ""
    if said == PAUSED:
        reason = str(body.get("reason") or "").strip()
        by = str(body.get("by") or "").strip()
        who = f" by {by}" if by else ""
        return False, f"account paused{who}" + (f": {reason}" if reason else "")
    return False, (
        f"the state {said!r} for {account_key} is not recognised, so it pauses"
    )


def write(
    account_key: str,
    *,
    active: bool,
    by: str,
    reason: str = "",
    directory: pathlib.Path | str | None = None,
) -> pathlib.Path:
    """Pause or resume one account, attributably and atomically.

    `by` is required in both directions. Pausing is the safe direction and
    could be anonymous, but then the record of who stopped an account and the
    record of who started it would be different kinds of record - and the one
    worth reading later is usually the pause.
    """
    if not by.strip():
        raise ValueError("changing an account's state must be attributable")

    where = _path(account_key, directory)
    where.parent.mkdir(parents=True, exist_ok=True)

    body: dict[str, Any] = {
        "state": ACTIVE if active else PAUSED,
        "by": by,
        "reason": reason,
        "at": datetime.now(UTC).isoformat(),
    }

    handle, temporary = tempfile.mkstemp(dir=str(where.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as writer:
            json.dump(body, writer, indent=2)
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(temporary, where)
    except BaseException:
        pathlib.Path(temporary).unlink(missing_ok=True)
        raise
    return where


def listing(
    account_keys: list[str], directory: pathlib.Path | str | None = None
) -> list[dict[str, Any]]:
    """Every account and whether it may trade, for a dashboard to render."""
    out: list[dict[str, Any]] = []
    for key in sorted(account_keys):
        allowed, why = state(key, directory)
        out.append({"account": key, "active": allowed, "reason": why})
    return out
