"""What happened today, said once a day without being asked.

The question that started this was "where is my 196,000 account?" - and the
answer was that it had been in a restart loop for twenty minutes and nothing
had said so. `systemctl` read "active" throughout, because a service being
restarted every ten seconds is active. The operator found out by asking.

That question should not have started with the operator.

So this composes one message a day from the live system: what each account
traded, what closed and for how much, which gate refused the most, whether
any terminal has gone quiet, and how much the forward record grew. Five
things, because a digest nobody finishes reading is a digest nobody reads.

**It reports and never acts.** Nothing here closes a position, changes a
setting or restarts anything. A daily summary that could also intervene is
two features sharing one schedule, and the one that intervenes would run at
whatever hour the summary happened to be set to.

**Silence is a finding.** An account that sent no orders gets a line saying
so, and a terminal that stopped publishing gets a line before anything else.
A digest that only listed activity would be shortest on exactly the day the
fleet stopped working.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

#: A terminal quieter than this has stopped publishing rather than paused.
#: The expert refreshes every twenty seconds; two minutes is six missed in a
#: row, which is not a slow cycle.
SILENT_AFTER_SECONDS = 120

#: How many refusal reasons to name. The point is which gate dominated, not
#: a census - and a message nobody finishes is a message nobody reads.
TOP_REASONS = 3


@dataclass
class Digest:
    """One day, in the order somebody needs to read it."""

    at: datetime
    silent_terminals: list[str] = field(default_factory=list)
    accounts: list[dict[str, Any]] = field(default_factory=list)
    closed: list[dict[str, Any]] = field(default_factory=list)
    refusals: list[tuple[str, int]] = field(default_factory=list)
    decisions_recorded: int = 0
    resolved_today: int = 0

    @property
    def has_trouble(self) -> bool:
        return bool(self.silent_terminals)

    def as_dict(self) -> dict[str, Any]:
        return {
            "at": self.at.isoformat(),
            "silent_terminals": self.silent_terminals,
            "accounts": self.accounts,
            "closed": self.closed,
            "refusals": [{"reason": r, "count": n} for r, n in self.refusals],
            "decisions_recorded": self.decisions_recorded,
            "resolved_today": self.resolved_today,
        }

    def as_text(self) -> str:
        """The message a person reads on a phone."""
        lines: list[str] = []

        def named(key: str) -> str:
            """`term-e` with whatever the operator calls it, if anything.

            Both, not either. The label is what tells a half-awake reader
            which account this is; the key is what every page, log line and
            directory is named after, and a message giving only the label
            leaves them with nothing to search for.
            """
            try:
                from app.services import terminal_names

                label = terminal_names.label_for(key)
            except Exception:  # noqa: BLE001 - a digest never raises at 6am
                label = None
            return f"{label} ({key})" if label else str(key)

        # Trouble first. A digest that led with yesterday's profit while a
        # terminal was down would bury the only line worth acting on.
        if self.silent_terminals:
            lines.append(
                "⚠ not publishing: "
                + ", ".join(named(key) for key in sorted(self.silent_terminals))
            )
            lines.append("")

        if self.accounts:
            lines.append("accounts")
            for row in self.accounts:
                orders = row.get("orders", 0)
                what = f"{orders} order(s)" if orders else "no orders"
                lines.append(
                    f"  {named(row['terminal'])}  equity {row['equity']:,.2f}"
                    f"  {row['positions']} open  {what}"
                )
            lines.append("")

        if self.closed:
            net = sum(float(d.get("net") or 0) for d in self.closed)
            lines.append(f"closed today: {len(self.closed)}, net {net:+,.2f}")
            for deal in self.closed[:5]:
                lines.append(
                    f"  {deal['symbol']}  {float(deal.get('net') or 0):+,.2f}"
                )
            lines.append("")

        if self.refusals:
            lines.append("most common refusal")
            for reason, count in self.refusals:
                lines.append(f"  {count}x {reason[:70]}")
            lines.append("")

        lines.append(
            f"forward record: {self.decisions_recorded} decision(s) recorded, "
            f"{self.resolved_today} resolved"
        )
        return "\n".join(lines).strip()


def _silent(now: datetime) -> list[str]:
    """Terminals with an account that have stopped publishing."""
    from app.providers.metatrader import MetaTraderBridge, bridge_dirs

    quiet: list[str] = []
    for key, path in sorted(bridge_dirs().items()):
        bridge = MetaTraderBridge(directory=path)
        state = bridge.state()
        account = bridge.account() if state.usable else {}
        # A terminal nobody logged into is meant to be silent, and reporting
        # it every morning would train the reader to ignore the line that
        # matters.
        if not account.get("available"):
            continue
        age = state.age_seconds if hasattr(state, "age_seconds") else None
        if age is not None and age > SILENT_AFTER_SECONDS:
            quiet.append(key)
    return quiet


def build(session: Any, *, now: datetime | None = None) -> Digest:
    """Compose today's digest from the running system."""
    from collections import Counter

    from sqlalchemy import select

    from app.models.journal import ARM_RULE, JournalEntry
    from app.providers.metatrader import MetaTraderBridge, bridge_dirs

    moment = now or datetime.now(UTC)
    since = moment - timedelta(days=1)
    digest = Digest(at=moment)

    try:
        digest.silent_terminals = _silent(moment)
    except Exception:  # noqa: BLE001 - a digest never raises at 6am
        digest.silent_terminals = []

    # Accounts, from what each terminal publishes rather than from what this
    # system believes it opened.
    for key, path in sorted(bridge_dirs().items()):
        try:
            bridge = MetaTraderBridge(directory=path)
            account = bridge.account()
            if not account.get("available"):
                continue
            positions = bridge.positions().get("positions") or []
            login = str(account.get("login") or "")
            traded = 0
            if login:
                rows = (
                    session.execute(
                        select(JournalEntry.during).where(
                            JournalEntry.arm == ARM_RULE,
                            JournalEntry.opened_at >= since,
                        )
                    )
                    .scalars()
                    .all()
                )
                traded = sum(
                    1
                    for during in rows
                    if isinstance(during, dict)
                    and isinstance(during.get("orders"), dict)
                    and login in during["orders"]
                )
            digest.accounts.append(
                {
                    "terminal": key,
                    "login": login,
                    "equity": float(account.get("equity") or 0.0),
                    "positions": len(positions),
                    "orders": traded,
                }
            )
        except Exception:  # noqa: BLE001, S112 - one unreadable bridge is not the day
            continue

    # What closed, from the terminal's own deal history.
    for key, path in sorted(bridge_dirs().items()):
        try:
            published = MetaTraderBridge(directory=path).deals()
        except Exception:  # noqa: BLE001, S112 - one unreadable bridge is not the day
            continue
        for deal in published.get("deals") or []:
            closed_at = str(deal.get("closed_at") or "")
            if closed_at and closed_at[:10] != moment.strftime("%Y-%m-%d"):
                continue
            digest.closed.append(
                {
                    "terminal": key,
                    "symbol": deal.get("symbol"),
                    "net": deal.get("net") or deal.get("profit") or 0,
                }
            )

    # Which gate refused the most - readable only because the reason is now
    # written onto the decision rather than into a log line that rotates.
    counts: Counter[str] = Counter()
    recorded = 0
    resolved = 0
    for entry in (
        session.execute(
            select(JournalEntry).where(
                JournalEntry.arm == ARM_RULE, JournalEntry.opened_at >= since
            )
        )
        .scalars()
        .all()
    ):
        recorded += 1
        if entry.outcome:
            resolved += 1
        during = entry.during if isinstance(entry.during, dict) else {}
        book = during.get("refused")
        if isinstance(book, dict):
            for record in book.values():
                reason = str((record or {}).get("reason") or "").strip()
                if reason:
                    # Collapse the varying counts in "5 brains want the other
                    # side against 2" so the gate is what is counted, not the
                    # arithmetic of one cycle.
                    counts[_family(reason)] += 1
    digest.refusals = counts.most_common(TOP_REASONS)
    digest.decisions_recorded = recorded
    digest.resolved_today = resolved
    return digest


def _family(reason: str) -> str:
    """The gate a refusal belongs to, with the day's numbers taken out.

    Without this the top reasons are "5 brains want the other side against 2"
    and "4 brains want the other side against 3" as separate findings, and
    the council - which is one gate - never appears as the answer.
    """
    lowered = reason.lower()
    if "brains want the other side" in lowered:
        return "the council outvoted it"
    if "cannot be split into currencies" in lowered:
        return "news exposure could not be checked"
    if "rounds to zero lots" in lowered:
        return "the size rounds to zero at this risk"
    if "already holds a position" in lowered:
        return "the account already holds it"
    if "spread and slippage" in lowered:
        return "cost exceeded the measured edge"
    if "no contract specification" in lowered:
        return "the terminal publishes no specification"
    if "currency-count" in lowered or "concentration" in lowered:
        return "too many positions on one currency"
    return reason[:70]


__all__ = ["SILENT_AFTER_SECONDS", "TOP_REASONS", "Digest", "build"]


def send(*, now: datetime | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Build today's digest and hand it to the chat channel.

    Returns what happened rather than raising. This runs unattended at six in
    the morning: an exception here is a traceback in a journal nobody reads,
    and the failure it would report is almost always "the channel is not
    configured yet" - which is a state, not a fault.
    """
    from app.db.session import session_scope
    from app.integrations import notify, telegram

    with session_scope() as session:
        report = build(session, now=now)
        text = report.as_text()
        if dry_run:
            return {"sent": False, "dry_run": True, "digest": report.as_dict(), "text": text}

        message = notify.Message(
            # WARNING only when a terminal has gone quiet. The enum's own
            # docstring says why: a channel where everything is urgent is a
            # channel where nothing is, and this arrives every single day.
            urgency=notify.Urgency.WARNING
            if report.has_trouble
            else notify.Urgency.INFO,
            title="MolidoTrade — today",
            body=text,
            at=report.at,
        )
        # No fingerprint: this is a message a person asked for on a schedule,
        # not a checker's alert. Deduplicating it would suppress the digest on
        # exactly the quiet week where it is the only sign the system is
        # still running.
        delivery = telegram.send(message, session=session)

    return {
        "sent": bool(getattr(delivery, "sent", False)),
        "reason": getattr(delivery, "reason", None),
        "digest": report.as_dict(),
    }


def main() -> int:
    """`python -m app.ops.digest [--dry-run]`."""
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(description="Today's digest.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="compose and print it without sending",
    )
    args = parser.parse_args()

    outcome = send(dry_run=args.dry_run)
    if args.dry_run:
        print(outcome["text"])
        return 0
    print(_json.dumps({k: v for k, v in outcome.items() if k != "digest"}))
    # Zero even when unsent: an unconfigured channel is a state the operator
    # already knows about, and a timer that reports failure every morning
    # trains them to ignore it.
    return 0


if __name__ == "__main__":  # pragma: no cover - the entry point
    raise SystemExit(main())
