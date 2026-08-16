"""Liveness for a worker that serves no port.

The collector inherited the API image's healthcheck, which curls
`localhost:8000`. The collector is an ARQ worker; it has never listened on a
port and never will, so the probe could not pass at any moment in its life. It
reported `unhealthy` continuously while writing fifty-four bars a cycle with
zero failures.

That is worse than having no healthcheck. A permanently red indicator trains
everybody to ignore the indicator, so the one time it means something, it means
nothing to anyone.

What actually matters for this worker is not whether a socket answers. It is
whether a collection cycle finished recently. That is the question here, and it
fails for the right reasons: the process wedged, the database went away, the
provider stopped answering — each of those stops cycles finishing, and each of
them should stop this returning zero.

It asks that question without importing the application, and that is not
premature optimisation. Measured inside the running container: importing the
settings cost 4.3s and the ORM models another 5.0s, against 3.2s for the query
itself - 12.5s total against a 15s probe timeout. So the probe spent four
fifths of its budget loading code it did not use, and any load spike pushed it
over. It did exactly that: the check computed a healthy answer, printed "last
cycle finished 428s ago", and was killed by the timeout before it could exit
zero. The container went unhealthy while the worker was writing bars normally.

Which is the same failure this module was written to fix, wearing different
clothes. A probe that fails on a busy machine trains everyone to ignore it,
and then it means nothing on the day it is right.

So: no settings object, no ORM, no app import. A DSN from the environment, one
SQL statement, and psycopg. The cost of the probe should be smaller than the
thing it measures.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta

#: Read straight from the environment rather than through the settings object.
#: Same variables the application reads, same defaults - see the module
#: docstring for why the settings import is not worth 4.3 seconds here.
DSN_VAR = "MOLIDO_DATABASE_URL"
INTERVAL_VAR = "MOLIDO_COLLECTOR_INTERVAL_SECONDS"
DEFAULT_DSN = "postgresql+psycopg://molido:molido@localhost:5432/molidotrade"
DEFAULT_INTERVAL = 900

# How many missed cycles before the worker is unhealthy. Three, because one
# missed cycle is a slow provider and two is a bad minute; three in a row is
# the worker not working.
MISSED_CYCLES = 3

# Even at a long interval, a worker silent for this long is not merely late.
MAX_SILENCE = timedelta(hours=2)


def last_finished(url: str) -> datetime | None:
    """When the most recent ingestion run finished, straight from the table.

    The table name is spelled out rather than reached through the model, which
    is the one real cost of not importing the ORM: a rename would break this
    silently. `tests/test_healthcheck.py` asserts the two still agree, so the
    rename breaks a test instead.
    """
    import psycopg

    with psycopg.connect(_libpq(url), connect_timeout=5) as connection:
        row = connection.execute(
            "SELECT max(finished_at) FROM ingestion_runs"
        ).fetchone()

    value = row[0] if row else None
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _libpq(url: str) -> str:
    """SQLAlchemy writes `postgresql+psycopg://`; libpq does not know the driver."""
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def check(now: datetime | None = None) -> tuple[bool, str]:
    """`(healthy, why)`. Anything unanswerable is unhealthy, never assumed fine."""
    moment = now or datetime.now(UTC)
    try:
        interval = int(os.environ.get(INTERVAL_VAR) or DEFAULT_INTERVAL)
    except ValueError:
        interval = DEFAULT_INTERVAL
    allowed = min(MAX_SILENCE, timedelta(seconds=interval * MISSED_CYCLES))

    try:
        finished = last_finished(os.environ.get(DSN_VAR) or DEFAULT_DSN)
    except Exception as exc:  # noqa: BLE001 - reported, and it fails the probe
        return False, f"could not read the run history: {exc}"

    if finished is None:
        # Before the first cycle completes there is nothing to be late. The
        # start period in the compose healthcheck covers this window; past it,
        # no cycle at all is a real failure.
        return False, "no collection cycle has ever finished"

    age = moment - finished
    if age > allowed:
        return False, (
            f"the last cycle finished {age.total_seconds() / 60:.0f} minutes ago, "
            f"beyond the {allowed.total_seconds() / 60:.0f}-minute limit"
        )
    return True, f"last cycle finished {age.total_seconds():.0f}s ago"


def main() -> int:
    healthy, why = check()
    print(why)
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
