"""The chat channel, on a process of its own.

It began as a job on the collector's schedule, and that was the wrong place
for it. One collection cycle takes minutes - 150 instruments, their features,
four broker timeframes, two price series, orders and resolution - and while it
runs the queue behind it waits. The chat job was arriving twenty-five minutes
after it was due, so an operator asking a question got silence and then nine
answers at once.

A channel that goes quiet whenever the system is busy is worse than no
channel: it is quiet exactly when somebody is asking *because* the system is
busy. So this is its own process, with nothing else on it, and the only work
it does is wait for a question.

It shares the database and the settings with everything else and owns no
state beyond the update offset. Nothing here can place an order - the replies
come from the same read-only allowlist a typed command goes through.
"""

from __future__ import annotations

import pathlib
import signal
import sys
import time
from typing import Any

from app.core.logging import configure_logging, get_logger
from app.db.session import session_scope

log = get_logger(__name__)

#: How long one long poll waits for an update before returning empty. Long
#: enough that the loop is not spinning through requests, short enough that a
#: stop signal is honoured promptly.
WAIT_SECONDS = 25

#: How long to wait after an error before trying again. A misconfigured token
#: or an unreachable API should not become a request flood.
BACKOFF_SECONDS = 30

#: Touched once per pass, so something outside this process can tell a loop
#: that is turning from one that is wedged inside a poll that will never
#: return. Beside the offset, in the one directory this process can write.
#:
#: The container's healthcheck was `pgrep -f app.workers.chat`, and the image
#: has no procps - so it exited 127 every minute and the channel was marked
#: unhealthy for its entire life while answering every question put to it. A
#: check that cannot pass is worse than no check: it trains whoever reads the
#: status to ignore the column.
#:
#: This says the loop is turning, which is the honest claim. A channel that
#: is running but refused by Telegram logs `chat.idle` and says why - that is
#: a different question and a restart is not its answer.
HEARTBEAT_FILE = "/var/lib/molido/state/chat-heartbeat"


def _beat() -> None:
    """Record that the loop came round again. Never fatal.

    An unwritable state directory is what put the offset in a loop replaying
    the same ten messages every minute, so this refuses to be the reason the
    channel stops: the worst an unwritable heartbeat can do is make the
    healthcheck pessimistic.
    """
    try:
        path = pathlib.Path(HEARTBEAT_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    except OSError:
        pass

_running = True


def _stop(_signum: int, _frame: Any) -> None:
    global _running
    _running = False


def run() -> int:
    """Answer questions until told to stop.

    Each pass opens its own session rather than holding one for the process's
    life: a connection kept open across a twenty-five second wait is a
    connection the pool cannot reuse, and the answers below are short reads.
    """
    configure_logging()
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    from app.integrations.telegram_bot import poll

    log.info("chat.started", wait_seconds=WAIT_SECONDS)
    while _running:
        _beat()
        try:
            with session_scope() as session:
                report = poll(session, wait=WAIT_SECONDS)
        except Exception as problem:  # noqa: BLE001 - reported, never fatal
            # The loop is the product. An exception that ends it takes the
            # channel down until somebody notices, which is the failure this
            # process exists to avoid.
            log.warning("chat.poll_failed", error=f"{type(problem).__name__}: {problem}")
            time.sleep(BACKOFF_SECONDS)
            continue

        if report.get("answered") or report.get("refused"):
            log.info("chat.answered", **report)
        if report.get("reason"):
            # A configuration problem does not improve by being retried at
            # full speed.
            log.warning("chat.idle", reason=report["reason"])
            time.sleep(BACKOFF_SECONDS)

    log.info("chat.stopped")
    return 0


if __name__ == "__main__":
    sys.exit(run())
