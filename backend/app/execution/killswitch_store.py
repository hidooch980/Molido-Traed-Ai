"""Where the kill switch remembers what it was set to.

`KillSwitch` is engaged by default and correct in every other respect, but it
lived only in whatever object happened to be holding it. Every request built a
fresh `AccountBook`, so the switch was always engaged there and never anywhere
that traded - the API reported `engaged: true` while `autotrade` sent orders,
because `autotrade` never asked.

**A file, not a table.** The moment a kill switch matters most is the moment
something is badly wrong, and "the database is unreachable" is squarely inside
that moment. A switch that cannot be read when the database is down is a
switch that fails exactly when it is needed. This reads one small file.

**Unreadable means engaged.** Missing, truncated, wrong shape, bad permissions
- all of them halt trading. The alternative is a corrupt byte deciding to
trade, and there is no reading of that byte that should. The only state that
lets orders through is a file that says so, in full, and parses.

**Disengaging stays a human act.** The store persists attribution and refuses
to write a disengaged state without it, the same rule `KillSwitch.disengage`
already enforces in memory. Nothing here gives an automated path a way to
re-arm the system: a halt that can undo itself is not a halt.
"""

from __future__ import annotations

import json
import os
import pathlib
import tempfile
from datetime import UTC, datetime
from typing import Any

from app.execution.safety import KillSwitch

#: Outside the checkout. A switch that lives in the deployment directory is a
#: switch a redeploy can reset, and a redeploy is a moment when somebody is
#: already changing things and not thinking about the halt they set yesterday.
DEFAULT_STATE_PATH = pathlib.Path(
    os.environ.get("MOLIDO_KILL_SWITCH_FILE") or "/var/lib/molido/kill-switch.json"
)

#: What a file has to say before orders are allowed through. Written in full
#: and checked in full, so a truncated write cannot read as permission.
DISENGAGED = "disengaged"
ENGAGED = "engaged"


def _engaged(reason: str) -> KillSwitch:
    switch = KillSwitch()
    switch.engaged = True
    switch.reason = reason
    return switch


def load(path: pathlib.Path | str | None = None) -> KillSwitch:
    """Read the switch. Anything unexpected returns an engaged one.

    Never raises. A kill switch that can throw on the read path is a kill
    switch that can take down the caller that was about to consult it, and the
    caller consults it in order to decide whether to trade.
    """
    where = pathlib.Path(path or DEFAULT_STATE_PATH)

    try:
        body = json.loads(where.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _engaged(
            "no kill switch state has been written, so trading is halted until "
            "somebody deliberately allows it"
        )
    except (OSError, ValueError) as problem:
        return _engaged(
            f"the kill switch state could not be read ({type(problem).__name__}), "
            "and an unreadable switch halts rather than allows"
        )

    if not isinstance(body, dict):
        return _engaged("the kill switch state is not an object, so it halts")

    state = body.get("state")
    if state == DISENGAGED:
        by = str(body.get("by") or "").strip()
        if not by:
            # The in-memory switch refuses to disengage without attribution and
            # the file must not be a way around that rule.
            return _engaged(
                "the kill switch state says disengaged but names nobody, and "
                "an unattributable release halts"
            )
        switch = KillSwitch()
        switch.engaged = False
        switch.reason = f"disengaged by {by}"
        switch.engaged_at = None
        switch.engaged_by = by
        return switch

    if state == ENGAGED:
        return _engaged(str(body.get("reason") or "the kill switch is engaged"))

    return _engaged(
        f"the kill switch state {state!r} is not recognised, so it halts"
    )


def save(switch: KillSwitch, path: pathlib.Path | str | None = None) -> pathlib.Path:
    """Persist the switch, atomically.

    Written to a temporary file in the same directory and renamed over the
    target, because a half-written file is one of the shapes `load` has to
    treat as engaged - correct, but it would halt trading for a reason nobody
    chose. A rename on the same filesystem does not have a half-way state.
    """
    where = pathlib.Path(path or DEFAULT_STATE_PATH)
    where.parent.mkdir(parents=True, exist_ok=True)

    if not switch.engaged and not (switch.engaged_by or "").strip():
        raise ValueError(
            "a disengaged kill switch must record who disengaged it - this is "
            "a human act and the file is not a way around that"
        )

    body: dict[str, Any] = {
        "state": ENGAGED if switch.engaged else DISENGAGED,
        "reason": switch.reason,
        "by": switch.engaged_by,
        "at": (switch.engaged_at or datetime.now(UTC)).isoformat(),
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
