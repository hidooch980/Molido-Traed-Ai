"""Let a terminal somewhere else publish into the bridge.

The file bridge was written for a terminal on this host: an expert inside
MetaTrader writes to a folder and the platform reads it. That shape assumes one
terminal, on one machine, with a shared filesystem - and it stops working the
moment somebody has eleven accounts, which is the ordinary situation for
anybody running funded accounts alongside a challenge.

Eleven terminals will not fit on this box beside the platform, and they should
not have to: nothing about the bridge needs the writer to be local. It needs
the files to exist. This route accepts the same payload over HTTPS and writes
them here, so the terminals can live wherever they already run - a trading VPS,
a desktop, several of each - and reach the platform outbound, through any
firewall, without a sync daemon or a shared drive.

**The account key is checked against configuration, never trusted.** The
provider's own docstring is blunt about why: the files carry no account
identity, so the directory *is* the account, and picking the wrong one sends an
order to the wrong money. A publish naming an account this deployment has not
been configured for is refused rather than filed somewhere plausible.

**The heartbeat is written last.** Every reader gates on it - a fresh heartbeat
means the data beside it is fresh. Writing it first, or writing it in the same
pass as the data, opens a window where a reader sees a current heartbeat over
half-written positions and believes them.

**Every file lands atomically.** A publish interrupted mid-write must leave the
previous state intact rather than a truncated JSON document, because a reader
that cannot parse positions reports "unreadable" and a reader that parses a
truncated list reports fewer positions than exist.

**It writes; it does not order.** Same rule the expert follows: this is the
inbound half of the bridge only. The outbound queue is a separate path with its
own gate, and the two do not meet here.
"""

from __future__ import annotations

import json
import os
import pathlib
import tempfile
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.core.enums import Permission
from app.core.errors import ValidationFailedError
from app.core.logging import get_logger
from app.db.session import get_db
from app.providers.metatrader import (
    DEFAULT_ACCOUNT_KEY,
    STAMP_FORMAT,
    bridge_dirs,
)

log = get_logger(__name__)

router = APIRouter(prefix="/bridge", tags=["bridge"])

#: Publishing is broker state, so it sits behind the broker permission rather
#: than behind READ. It mutates - the execution gate would refuse the
#: application's startup if it did not say so.
BROKER = Depends(require(Permission.BROKER_MANAGE))

#: Bars are the bulky part and a terminal with a long Market Watch can publish
#: a great many. Capped so one misconfigured expert cannot fill the disk.
MAX_SYMBOLS = 500
MAX_POSITIONS = 500


class BridgePublish(BaseModel):
    """One terminal's state, as its expert sees it."""

    #: Which account this is. Must already be configured; see the module note.
    account_key: str = Field(default=DEFAULT_ACCOUNT_KEY, min_length=1, max_length=64)

    #: The account block, written verbatim to `molido_account.json`. Left as a
    #: free mapping because the reader coerces every field it needs and
    #: tolerates the rest - a stricter model here would reject a terminal that
    #: publishes one extra key, which is a worse failure than an ignored field.
    account: dict[str, Any] = Field(default_factory=dict)
    symbols: list[dict[str, Any]] = Field(default_factory=list, max_length=MAX_SYMBOLS)
    positions: list[dict[str, Any]] = Field(
        default_factory=list, max_length=MAX_POSITIONS
    )

    #: What the terminal says about itself. Copied into the heartbeat, where
    #: the reader uses `connected` and `login` to tell "running but nobody
    #: logged in" from "running with an account" - the state this deployment
    #: once sat in for hours looking healthy.
    connected: bool = False
    login: int = 0


def _write_atomically(path: pathlib.Path, payload: str) -> None:
    """Replace `path` in one step, or leave it exactly as it was.

    A reader can open this directory at any moment, so a file must never be
    observable half-written. `os.replace` is atomic within a filesystem, and
    the temporary file is created in the same directory to guarantee that.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    try:
        with handle as tmp:
            tmp.write(payload)
            tmp.flush()
            # Durable before the rename. Without this a crash between the two
            # can leave the name pointing at a file whose contents never
            # reached the disk.
            os.fsync(tmp.fileno())
        os.replace(handle.name, path)
    except BaseException:
        pathlib.Path(handle.name).unlink(missing_ok=True)
        raise


@router.post("/publish")
def publish(
    body: BridgePublish,
    principal: Principal = BROKER,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Accept one terminal's published state and write it into its directory."""
    # The session is passed so terminals registered through the interface
    # resolve here too. Without it this route only knows the environment
    # variable, and a terminal somebody had just added on screen would be
    # refused by the endpoint the screen had told them to point it at.
    known = bridge_dirs(session=session)
    directory = known.get(body.account_key)
    if directory is None:
        # Named, with the alternatives, because the usual cause is a typo in
        # one expert's inputs and the usual symptom without this is a terminal
        # that appears to publish into silence.
        raise ValidationFailedError(
            f"no bridge directory is configured for account "
            f"{body.account_key!r}. Configured accounts are: "
            f"{', '.join(sorted(known)) or 'none'}.",
            account_key=body.account_key,
            configured=sorted(known),
        )

    published_at = datetime.now(UTC)
    written: list[str] = []

    # `connected` and `login` are read out of the *account* file, not the
    # heartbeat - the heartbeat carries only a timestamp. Publishing them at
    # the top level and nowhere else produced a bridge the reader called
    # "running but nobody logged in", which is a real state it reports for a
    # real reason and would have been completely wrong here.
    #
    # Merged rather than imposed: what the terminal put in its own account
    # block wins, because that block is the terminal's view of itself and the
    # top-level fields exist only so a simple expert can supply them once.
    account = dict(body.account)
    account.setdefault("login", body.login)
    account.setdefault("connected", body.connected)

    # Data first, heartbeat last. See the module note: the heartbeat is what
    # every reader gates on, so it must never be newer than what it vouches for.
    _write_atomically(
        directory / "molido_account.json",
        json.dumps(account, ensure_ascii=False),
    )
    written.append("account")

    _write_atomically(
        directory / "molido_symbols.json",
        json.dumps({"symbols": body.symbols}, ensure_ascii=False),
    )
    written.append("symbols")

    _write_atomically(
        directory / "molido_positions.json",
        json.dumps({"positions": body.positions}, ensure_ascii=False),
    )
    written.append("positions")

    _write_atomically(
        directory / "molido_heartbeat.json",
        json.dumps(
            {
                # MetaTrader's own stamp format, not ISO 8601, because the
                # reader parses it with `strptime(STAMP_FORMAT)` and an ISO
                # string raises there. Imported rather than retyped: the two
                # halves of this contract live in different files, and a format
                # copied by hand is one that drifts silently - the symptom
                # being a terminal that publishes perfectly into a directory
                # the platform reports as having no heartbeat at all.
                "published_at": published_at.strftime(STAMP_FORMAT),
                "connected": body.connected,
                "login": body.login,
                # Recorded so a reader can tell a terminal that wrote these
                # files locally from one that posted them, which matters the
                # first time somebody debugs why a directory stopped updating.
                "transport": "http",
            },
            ensure_ascii=False,
        ),
    )
    written.append("heartbeat")

    log.info(
        "bridge.published",
        account_key=body.account_key,
        login=body.login,
        connected=body.connected,
        symbols=len(body.symbols),
        positions=len(body.positions),
        # Who published, so a directory that stops updating can be traced to a
        # key rather than to "something out there".
        role=principal.role.value,
        user_id=str(principal.user_id) if principal.user_id else None,
    )

    return {
        "accepted": True,
        "account_key": body.account_key,
        "published_at": published_at.isoformat(),
        "written": written,
        "note": (
            "this route writes what the terminal published and sends no "
            "orders; the outbound queue is a separate path"
        ),
    }
