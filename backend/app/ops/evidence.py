"""Facts about the host, written by the host, read by the containers.

`readiness` left nine of its checks undeterminable on purpose: the API runs in
a container and cannot see the docker log driver, the restore history or the
repository. That was honest and it was also permanent - the checks stayed
"could not be determined" for months, and a check that can never pass is a
check nobody reads.

The fix is not to guess from inside the container. It is to have the host,
which can see those things, write down what it saw, and to have the container
read the note. `infra/readiness-evidence.sh` runs on the host from cron and
writes one small JSON file per fact into `/var/lib/molido/evidence/`, which
every container already mounts. This module reads them.

Three rules make the note worth trusting:

**Every file says when it was written, and a stale note is no note.** A fact
about the disk from last month is not a fact about the disk. Each reader has a
maximum age, and a file older than that returns None - undeterminable - which
`readiness` grades as a failure. Silence and staleness must never read as
"still fine".

**Only safe facts.** Nothing here carries a secret value, a backup's contents
or a log line. The secrets scan writes paths and categories; the restore drill
writes counts and timestamps. A file that is safe to `cat` on a shared screen.

**Missing means unknown, malformed means unknown.** A reader never raises and
never fills in a default. The only way to get a value out is for the host to
have written a well-formed one recently.
"""

from __future__ import annotations

import json
import os
import pathlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

#: Where the host writes, and where every container mounts it read-only.
#: Outside the checkout, like the kill switch: a redeploy must not reset what
#: the host knows about itself.
DEFAULT_DIR = pathlib.Path(
    os.environ.get("MOLIDO_EVIDENCE_DIR") or "/var/lib/molido/evidence"
)

#: How old each fact may be before it stops counting. Chosen from how fast the
#: underlying thing changes, not from how often the cron runs: the log driver
#: changes on a redeploy, the restore drill runs nightly, a secrets scan is
#: about a checkout that changes on every deploy.
MAX_AGE: dict[str, timedelta] = {
    "log-rotation": timedelta(hours=6),
    "restore-drill": timedelta(days=30),
    "secrets-scan": timedelta(hours=6),
}


@dataclass(frozen=True)
class Note:
    """One evidence file, parsed, with the age the reader judged it at."""

    name: str
    written_at: datetime
    body: dict[str, Any]
    age: timedelta

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "written_at": self.written_at.isoformat(),
            "age_seconds": self.age.total_seconds(),
            **{k: v for k, v in self.body.items() if k != "written_at"},
        }


def _parse_when(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        # A naive stamp is a stamp in somebody's local time, and "somebody's
        # local time" is how a six-hour age reads as fresh.
        return None
    return when.astimezone(UTC)


def read(
    name: str,
    *,
    directory: pathlib.Path | str | None = None,
    now: datetime | None = None,
    max_age: timedelta | None = None,
) -> Note | None:
    """Read one evidence file, or None when it is missing, malformed or stale.

    Never raises: this is consulted on the path that decides whether to trade,
    and a reader that throws takes down the caller that was about to refuse.
    """
    where = pathlib.Path(directory or DEFAULT_DIR) / f"{name}.json"
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    limit = max_age if max_age is not None else MAX_AGE.get(name, timedelta(hours=6))

    try:
        body = json.loads(where.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(body, dict):
        return None

    written = _parse_when(body.get("written_at"))
    if written is None:
        return None
    age = moment - written
    if age < -timedelta(minutes=5):
        # Written in the future is a clock problem, and a clock problem on the
        # evidence path is indistinguishable from a forged note.
        return None
    if age > limit:
        return None
    return Note(name=name, written_at=written, body=body, age=age)


# ------------------------------------------------------------ typed readers
#
# Each returns exactly the shape `readiness.Deployment` wants, or None. The
# translation from "what the host wrote" to "what the check asks" lives here so
# the API route stays a list of readers rather than a second parser.


def log_rotation_configured(**kw: Any) -> bool | None:
    """True only when every listed container has a bounded log driver."""
    note = read("log-rotation", **kw)
    if note is None:
        return None
    containers = note.body.get("containers")
    if not isinstance(containers, list) or not containers:
        return None
    for entry in containers:
        if not isinstance(entry, dict):
            return None
        if entry.get("bounded") is not True:
            return False
    return True


def last_successful_restore(**kw: Any) -> datetime | None:
    """When the last restore drill that verified rows finished, or None.

    A drill that did not succeed, or succeeded without counting anything, is
    not a restore - it is a file that decompressed.
    """
    note = read("restore-drill", **kw)
    if note is None:
        return None
    if note.body.get("succeeded") is not True:
        return None
    try:
        rows = int(note.body.get("rows_verified") or 0)
    except (TypeError, ValueError):
        return None
    if rows <= 0:
        return None
    return _parse_when(note.body.get("performed_at"))


def secrets_in_repository(**kw: Any) -> list[str] | None:
    """Paths of findings the scan graded as a secret. Empty list is a pass.

    Findings the scan graded lower - a secret-shaped filename whose contents
    turned out to be a public URL - are kept in the note for a reader but do
    not fail the check. See `secrets_scan` for the grading.
    """
    note = read("secrets-scan", **kw)
    if note is None:
        return None
    findings = note.body.get("findings")
    if not isinstance(findings, list):
        return None
    if note.body.get("complete") is not True:
        # A scan that did not finish is a scan that did not look everywhere,
        # and "looked at half and found nothing" is not "found nothing".
        return None
    return [
        str(f.get("path"))
        for f in findings
        if isinstance(f, dict) and f.get("severity") == "secret"
    ]


__all__ = [
    "DEFAULT_DIR",
    "MAX_AGE",
    "Note",
    "last_successful_restore",
    "log_rotation_configured",
    "read",
    "secrets_in_repository",
]
