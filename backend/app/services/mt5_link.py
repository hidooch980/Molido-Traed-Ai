"""Hand a broker login to the host agent that can apply it (spec §26, §46).

The API runs in a container and MetaTrader runs on the host, under Wine, owned
by another user and driven by systemd units the container cannot see. So this
module does not write MetaTrader's config and does not restart anything. It
writes a request into a shared directory and reports what the agent did with
it, which keeps the web-facing process exactly as privileged as it was.

Nothing here stores the password. It goes into the request, the agent puts it
into MetaTrader's own config - where the terminal would keep it regardless -
and the request file is deleted. A second copy in this application's database
would buy an attack surface and a key to manage in exchange for nothing.

`login` and `server` are not secret and are reported freely. The password is
never returned, never logged, and never placed in an exception message.
"""

from __future__ import annotations

import json
import pathlib
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.config import get_settings
from app.core.errors import ValidationFailedError

#: MetaTrader account numbers are digits, and server names are the broker's own
#: identifiers. Both are checked before they reach a config file the terminal
#: parses, because a newline in either would let a caller write arbitrary
#: sections into that file.
LOGIN_RE = re.compile(r"^\d{4,12}$")
SERVER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\- ]{2,63}$")

#: A password may contain almost anything, but not the two characters that
#: would break out of the ini line it is written to.
FORBIDDEN_IN_PASSWORD = ("\n", "\r")


@dataclass(frozen=True)
class LinkRequest:
    """A broker login on its way to the terminal."""

    login: str
    server: str
    password: str

    def as_payload(self) -> dict[str, str]:
        return {"login": self.login, "server": self.server, "password": self.password}


@dataclass(frozen=True)
class LinkResult:
    """What happened, with no secret in it."""

    queued: bool
    request_id: str
    login: str
    server: str
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "queued": self.queued,
            "request_id": self.request_id,
            "login": self.login,
            "server": self.server,
            "reason": self.reason,
            "password_stored": False,
            "note": (
                "the password is written to MetaTrader's own config by the host "
                "agent and kept nowhere in this application"
            ),
        }


def queue_dir() -> pathlib.Path:
    return pathlib.Path(get_settings().mt5_queue_dir)


def validate(login: str, server: str, password: str) -> LinkRequest:
    """Refuse anything that could not be a real login before it is written.

    The checks are about the file, not about the broker. A newline in `login`
    or `server` would let a caller add sections to an ini file the terminal
    reads at startup, which is a configuration injection with a terminal on the
    other end of it.
    """
    login = login.strip()
    server = server.strip()

    if not LOGIN_RE.match(login):
        raise ValidationFailedError("A MetaTrader login is 4 to 12 digits.")
    if not SERVER_RE.match(server):
        raise ValidationFailedError(
            "A server name is 3 to 64 characters of letters, digits, dot, dash, "
            "underscore or space."
        )
    if not password:
        raise ValidationFailedError("A password is required.")
    if any(ch in password for ch in FORBIDDEN_IN_PASSWORD):
        # Deliberately does not echo the password back in the message.
        raise ValidationFailedError("A password cannot contain a line break.")

    return LinkRequest(login=login, server=server, password=password)


def submit(request: LinkRequest, *, now: datetime | None = None) -> LinkResult:
    """Write the request for the host agent to pick up.

    Written to a temporary name and renamed into place. The agent globs for
    finished requests, and a rename is atomic on the same filesystem, so it
    cannot read half a file and log into half an account.
    """
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%S")
    request_id = f"{stamp}-{uuid.uuid4().hex[:8]}"
    directory = queue_dir()

    try:
        directory.mkdir(parents=True, exist_ok=True)
        partial = directory / f"{request_id}.partial"
        partial.write_text(json.dumps(request.as_payload()), encoding="utf-8")
        partial.chmod(0o600)
        partial.rename(directory / f"{request_id}.request.json")
    except OSError as exc:
        return LinkResult(
            queued=False,
            request_id=request_id,
            login=request.login,
            server=request.server,
            reason=f"the request could not be written: {exc.strerror or exc}",
        )

    return LinkResult(
        queued=True,
        request_id=request_id,
        login=request.login,
        server=request.server,
    )


def result_for(request_id: str) -> dict[str, Any]:
    """What the agent reported, or that it has not reported yet.

    "Not applied yet" and "applied and failed" are different answers and this
    returns them differently. Collapsing them would make a stopped agent look
    like a rejected login, and the fix for those two is not the same.
    """
    path = queue_dir() / f"{request_id}.result.json"
    if not path.exists():
        pending = (queue_dir() / f"{request_id}.request.json").exists()
        return {
            "known": False,
            "pending": pending,
            "reason": (
                "the host agent has not picked this up yet"
                if pending
                else "no request or result exists with that id"
            ),
        }
    try:
        return {"known": True, **json.loads(path.read_text(encoding="utf-8"))}
    except (OSError, json.JSONDecodeError) as exc:
        return {"known": False, "pending": False, "reason": f"unreadable result: {exc}"}


def agent_state() -> dict[str, Any]:
    """Whether the queue is reachable and how much is waiting in it.

    A queue nobody is draining looks exactly like a queue with nothing in it
    from the API's side, so the depth is published rather than summarised.
    """
    directory = queue_dir()
    try:
        exists = directory.is_dir()
        pending = len(list(directory.glob("*.request.json"))) if exists else 0
        results = len(list(directory.glob("*.result.json"))) if exists else 0
    except OSError as exc:
        return {"reachable": False, "reason": str(exc), "queue": str(directory)}

    return {
        "reachable": exists,
        "queue": str(directory),
        "pending_requests": pending,
        "results_waiting": results,
        "reason": None if exists else "the shared queue directory is not mounted",
    }
