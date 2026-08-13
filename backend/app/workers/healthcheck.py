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
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, func, select

from app.core.config import get_settings
from app.models.ingestion import IngestionRun

# How many missed cycles before the worker is unhealthy. Three, because one
# missed cycle is a slow provider and two is a bad minute; three in a row is
# the worker not working.
MISSED_CYCLES = 3

# Even at a long interval, a worker silent for this long is not merely late.
MAX_SILENCE = timedelta(hours=2)


def last_finished(url: str) -> datetime | None:
    engine = create_engine(url, future=True, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            value = connection.execute(
                select(func.max(IngestionRun.finished_at))
            ).scalar_one_or_none()
    finally:
        engine.dispose()
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def check(now: datetime | None = None) -> tuple[bool, str]:
    """`(healthy, why)`. Anything unanswerable is unhealthy, never assumed fine."""
    settings = get_settings()
    moment = now or datetime.now(UTC)
    allowed = min(
        MAX_SILENCE,
        timedelta(seconds=settings.collector_interval_seconds * MISSED_CYCLES),
    )

    try:
        finished = last_finished(settings.database_url)
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
