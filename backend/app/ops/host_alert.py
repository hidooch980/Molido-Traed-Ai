"""A host script's alert, delivered through the same Telegram channel as everything else.

The host timers (autoheal, backup, updater guard) can see what no container
can, but they wrote only to /var/log - evidence nobody reads until something
has been down for days. This gives them one sentence of Python to reach a
person:

    docker exec molidotrade-api-1 python -m app.ops.host_alert "title" "body" [fingerprint]

With a fingerprint the same fault alerts once per cooldown; without one every
call sends. Exits zero even when nothing was delivered, so a quiet channel
never turns a host timer red every few minutes.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from typing import Any


def send(title: str, body: str, fingerprint: str | None = None) -> dict[str, Any]:
    from app.db.session import session_scope
    from app.integrations import notify, telegram

    with session_scope() as session:
        delivery = telegram.send(
            notify.Message(
                urgency=notify.Urgency.WARNING,
                title=f"MolidoTrade — {title}",
                body=body,
                at=datetime.now(UTC),
            ),
            session=session,
            fingerprint=f"host:{fingerprint}" if fingerprint else None,
        )
    return {"sent": delivery.sent, "reason": delivery.reason}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: python -m app.ops.host_alert TITLE BODY [FINGERPRINT]")
        return 2
    result = send(argv[0], argv[1], argv[2] if len(argv) > 2 else None)
    print(result)
    return 0


if __name__ == "__main__":  # pragma: no cover - a command, not a code path
    raise SystemExit(main(sys.argv[1:]))
