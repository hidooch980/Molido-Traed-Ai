"""Send the week's brain scorecard, once, to the channel that reaches a person.

The daily digest says what the machine did. This says what the *evidence*
did, and it is the one number worth looking at weekly: not the week's profit,
which on a fleet this size is noise, but how many independent instants each
brain has accumulated against the fifty at which its question becomes
answerable at all.

**It existed and it went nowhere.** `checkpoint.sh --scorecard` has run on
cron three times a week since 2026-09-06, writing to
`/var/log/molido-checkpoint.log` on a machine nobody logs into. The daily
digest goes to Telegram; the weekly one, which is the one that changes a
decision, did not.

Deliberately short. A weekly message that opens with eight tables is a weekly
message nobody reads by the third week, and the whole point of a schedule is
that it survives being ignored once.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

#: Brains to name individually before the rest are summarised. Ordered by
#: independent instants, so the ones nearest an answer come first.
NAMED = 4


def compose(payload: dict[str, Any], *, now: datetime | None = None) -> str:
    """The message text from `weekly.verdicts`."""
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    cards = sorted(
        payload.get("cards") or [],
        key=lambda c: -(c.get("effective_trials") or 0),
    )

    lines = [f"MolidoTrade — the week to {moment:%Y-%m-%d}", ""]

    if payload.get("any_edge"):
        lines.append(f"An edge is claimed for: {', '.join(payload['with_edge'])}")
    else:
        # Said plainly every week. A scorecard that only speaks when it has
        # news trains everybody to read silence as good news.
        lines.append("No brain has an edge on the forward record.")
    lines.append("")

    lines.append("Independent instants, against the 50 an answer needs:")
    for card in cards[:NAMED]:
        effective = card.get("effective_trials") or 0
        trials = card.get("trials") or 0
        together = card.get("trials_per_instant")
        crowd = (
            f" ({trials} decisions, {together} at a time)"
            if together and together > 1.2
            else ""
        )
        lines.append(f"  {card['strategy']}: {effective}{crowd}")

    rest = cards[NAMED:]
    if rest:
        quiet = sum(1 for c in rest if not (c.get("effective_trials") or 0))
        lines.append(f"  and {len(rest)} more, {quiet} of them with nothing yet")

    if payload.get("retracted_excluded"):
        lines.append("")
        lines.append(
            f"{payload['retracted_excluded']} withdrawn decisions are excluded"
        )

    lines.append("")
    lines.append(
        "Instants, not decisions: trades opened together on one move are one "
        "piece of evidence."
    )
    return "\n".join(lines)


def send(*, now: datetime | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Build the week's scorecard and hand it to the chat channel.

    Returns what happened rather than raising, for the same reason the daily
    digest does: this runs unattended, and a traceback in a journal nobody
    reads is not a report.
    """
    from app.db.session import session_scope
    from app.integrations import notify, telegram
    from app.learning.weekly import verdicts

    with session_scope() as session:
        payload = verdicts(session)
        text = compose(payload, now=now)
        if dry_run:
            return {"sent": False, "dry_run": True, "text": text, "verdicts": payload}

        message = notify.Message(
            # INFO always. Nothing here is urgent by construction - it is a
            # weekly reading of how much evidence exists - and a channel
            # where everything is a warning is a channel where nothing is.
            urgency=notify.Urgency.INFO,
            title="MolidoTrade — the week",
            body=text,
            at=(now or datetime.now(UTC)).astimezone(UTC),
        )
        # No fingerprint, like the daily one: a message somebody asked for on
        # a schedule is not a checker's alert, and deduplicating it would
        # suppress it on exactly the quiet week where it is the only sign the
        # measurement is still running.
        delivery = telegram.send(message, session=session)

    return {
        "sent": bool(getattr(delivery, "sent", False)),
        "reason": getattr(delivery, "reason", None),
        "verdicts": payload,
    }


def main() -> int:
    """`python -m app.ops.weekly_digest [--dry-run]`."""
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(description="The week's brain scorecard.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="compose and print it without sending",
    )
    args = parser.parse_args()

    outcome = send(dry_run=args.dry_run)
    if args.dry_run:
        print(outcome["text"])
    else:
        print(_json.dumps({"sent": outcome["sent"], "reason": outcome["reason"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
