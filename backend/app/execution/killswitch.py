"""Engage or release the kill switch from the host, and write down who did.

    python -m app.execution.killswitch status
    python -m app.execution.killswitch engage  --by aziz --reason "rolling the expert"
    python -m app.execution.killswitch release --by aziz --reason "expert verified on term-b"

There is no API route for this, on purpose: releasing the halt is a human
act at the host, and a route is a thing that can be called by a script. This
is the one place that writes the file, and it writes an audit event beside
it so the release is on the same timeline as everything it then allows.

Releasing does not authorise an order. It changes one of the three states
(`app.ops.authorization`); every other gate still has to pass on the next
cycle, and the decision says which did not.
"""

from __future__ import annotations

import argparse
import json
import sys

from app.execution import killswitch_store
from app.execution.safety import KillSwitch


def _audit(action: str, by: str, reason: str) -> str:
    """Record the act. Reported rather than fatal when the database is down:
    the switch must still move when nothing else works."""
    try:
        from app.db.session import SessionLocal
        from app.services import audit

        with SessionLocal() as session:
            audit.record(
                session,
                f"killswitch.{action}",
                summary=f"kill switch {action} by {by}: {reason}",
                payload={"by": by, "reason": reason, "action": action},
                service="host",
            )
            session.commit()
        return "audited"
    except Exception as problem:  # noqa: BLE001 - the switch moves regardless
        return f"not audited ({type(problem).__name__}: the database was not reachable)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="engage or release the kill switch")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    for name in ("engage", "release"):
        p = sub.add_parser(name)
        p.add_argument("--by", required=True, help="who is doing this; recorded")
        p.add_argument("--reason", required=True, help="why; recorded")
    args = parser.parse_args(argv)

    if args.command == "status":
        switch = killswitch_store.load()
        print(
            json.dumps(
                {"path": str(killswitch_store.DEFAULT_STATE_PATH), **switch.as_dict()},
                indent=2,
            )
        )
        return 0

    if not args.by.strip() or not args.reason.strip():
        print("both --by and --reason must say something", file=sys.stderr)
        return 2

    switch = KillSwitch()
    if args.command == "engage":
        switch.engage(args.reason, by=args.by)
    else:
        switch.disengage(by=args.by)
        switch.reason = f"disengaged by {args.by}: {args.reason}"
    path = killswitch_store.save(switch)
    audited = _audit(args.command, args.by, args.reason)
    print(
        json.dumps(
            {"path": str(path), "audit": audited, **killswitch_store.load(path).as_dict()},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
