"""Registering the terminals that publish into the bridge.

The directory a terminal publishes into is derived from its key and never
supplied. That is the whole security property of this module, and it is worth
stating rather than assuming: the key becomes a path segment, so a key that can
express `..` or `/` is a key that can write anywhere the process can reach -
over another account's files, or over anything else under the same root.

`KEY_PATTERN` is therefore a whitelist rather than a blacklist. A blacklist of
dangerous characters is a list somebody has to keep complete forever, against
an attacker who only has to find one that was missed; a whitelist of lowercase
letters, digits, hyphen and underscore is finished on the day it is written.

The resolved path is checked against the root afterwards anyway. Two
independent guards on the same property, because this one ends with somebody
else's money being sized from the wrong balance.
"""

from __future__ import annotations

import pathlib
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailedError
from app.models.terminals import KEY_PATTERN, Terminal

#: Where registered terminals publish. One directory per key, under a root the
#: compose file mounts so the files survive a container being replaced.
BRIDGE_ROOT = pathlib.Path("/var/molido/bridge")

#: What the holder may call a terminal. Free text, but bounded - these end up
#: in a table on a page, not in a paragraph.
MAX_LABEL = 120


def validate_key(key: str) -> str:
    """The key, or a refusal explaining what a key may be.

    Refused rather than sanitised. Silently rewriting `My Account` to
    `my-account` produces a terminal whose key is not the one somebody typed
    into their expert, and the symptom of that is a terminal publishing into a
    directory nobody is reading.
    """
    if not KEY_PATTERN.match(key):
        raise ValidationFailedError(
            "A terminal key may use lowercase letters, digits, hyphen and "
            "underscore, must start and end with a letter or digit, and may "
            "be up to 64 characters. It becomes a directory name, which is "
            "why it cannot contain a slash or a dot.",
            key=key,
        )
    return key


def directory_for(key: str) -> pathlib.Path:
    """Where a terminal publishes. Derived, never supplied."""
    validate_key(key)

    # Both sides resolved before comparing. Comparing a resolved path against
    # an unresolved one passes on Linux and fails on Windows, where `resolve`
    # prepends a drive - which would have made this guard reject every valid
    # key on a developer machine while doing nothing useful on the server.
    root = BRIDGE_ROOT.resolve()
    resolved = (root / key).resolve()

    # The second guard. `validate_key` should already make this impossible, and
    # that is exactly why it is here: the day the pattern is loosened by
    # somebody who has not read it, this is what still refuses. One directory
    # deep, exactly - `parent == root` rejects an escape and a nesting alike.
    if resolved.parent != root:
        raise ValidationFailedError(
            "that key does not resolve to a directory inside the bridge root",
            key=key,
        )
    return resolved


def register(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    key: str,
    label: str = "",
    broker: str = "",
    kind: str = "",
) -> Terminal:
    """Record a terminal and create the directory it will publish into."""
    validate_key(key)

    existing = session.scalar(
        select(Terminal).where(Terminal.tenant_id == tenant_id, Terminal.key == key)
    )
    if existing is not None:
        # Named rather than a generic conflict. With eleven accounts the usual
        # cause is somebody re-adding one they set up weeks ago, and the useful
        # answer is that it already exists rather than that something failed.
        raise ValidationFailedError(
            f"a terminal with the key {key!r} is already registered "
            f"({existing.label or 'no label'}).",
            key=key,
        )

    terminal = Terminal(
        tenant_id=tenant_id,
        key=key,
        label=label[:MAX_LABEL],
        broker=broker[:MAX_LABEL],
        kind=kind[:32],
        is_active=True,
    )
    session.add(terminal)
    session.flush()

    # Created now rather than on the first publish, so the person setting this
    # up can see the terminal appear as "registered, nothing received yet"
    # instead of as nothing at all.
    directory_for(key).mkdir(parents=True, exist_ok=True)
    return terminal


def listing(session: Session, *, tenant_id: uuid.UUID) -> list[Terminal]:
    return list(
        session.scalars(
            select(Terminal)
            .where(Terminal.tenant_id == tenant_id)
            .order_by(Terminal.key)
        )
    )


def set_active(
    session: Session, *, tenant_id: uuid.UUID, terminal_id: uuid.UUID, active: bool
) -> Terminal:
    terminal = session.scalar(
        select(Terminal).where(
            Terminal.tenant_id == tenant_id, Terminal.id == terminal_id
        )
    )
    if terminal is None:
        raise ValidationFailedError("no such terminal", terminal_id=str(terminal_id))
    terminal.is_active = active
    session.flush()
    return terminal


def registered_dirs(session: Session) -> dict[str, pathlib.Path]:
    """Every active terminal's key and directory, across tenants.

    Cross-tenant on purpose: this feeds `bridge_dirs`, which the collector and
    the execution path use outside any request, where there is no tenant in
    scope. Keys are unique per tenant rather than globally, so a collision here
    is possible in principle - and it resolves to whichever row sorts last,
    which is a real limitation of a single-tenant deployment growing a second
    tenant. It is named here rather than discovered later.
    """
    rows = session.scalars(select(Terminal).where(Terminal.is_active.is_(True)))
    return {row.key: BRIDGE_ROOT / row.key for row in rows}
