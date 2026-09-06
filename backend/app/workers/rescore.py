"""Retract the verdicts that were reached on the wrong bars, and re-open them.

`resolve_open` took its timeframe from a parameter with an H1 default, and the
collector calls it once. From the day the fleet began recording on more than
one timeframe until 6 September, every M5, M15, M1 and D1 decision was
therefore scored against H1 bars: prices those decisions never saw, and a
horizon between twelve and sixty times too wide. 11,028 entries carry a win or
a loss reached that way, and the weekly scorecard reads them.

A wrong number is worse than a missing one, because afterwards nothing
distinguishes it from a measured one. So they are re-opened and left to the
fixed resolver, which will score them from their own timeframe's bars - the
bars exist back to 2 July, well before any of these decisions.

**The decision is not touched.** Only the claim about how it turned out is,
and the retracted claim is kept in `after.retracted` rather than deleted: this
project does not rewrite history, it adds a correction beside it. An entry
re-scored from the right bars can be compared with what the wrong bars said,
which is the only way anybody can check this repair later.

**Dry run by default.** It prints what it would change and changes nothing
until `--apply`, because a command that edits eleven thousand rows on the way
to answering "how many?" is a command nobody should have to be brave to run.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import Timeframe
from app.models.journal import JournalEntry

#: When the fixed resolver reached production. A verdict recorded before this
#: was reached on H1 bars whatever the entry's own timeframe; one recorded
#: after it was reached on the entry's own bars and is left alone.
FIXED_AT = datetime(2026, 9, 6, 6, 0, tzinfo=UTC)

WHY = (
    "scored against H1 bars because the resolver took its timeframe from a "
    "parameter rather than from the entry. Re-opened on 6 September 2026 to "
    "be scored on its own timeframe's bars. The decision is unchanged; only "
    "the claim about how it turned out was withdrawn"
)


def candidates(session: Session, *, fixed_at: datetime = FIXED_AT) -> list[JournalEntry]:
    """Every entry whose verdict was reached on bars of the wrong timeframe."""
    return list(
        session.scalars(
            select(JournalEntry).where(
                JournalEntry.timeframe.is_not(None),
                JournalEntry.timeframe != Timeframe.H1.value,
                JournalEntry.outcome.is_not(None),
                JournalEntry.closed_at < fixed_at,
            )
        ).all()
    )


def rescore(
    session: Session,
    *,
    apply: bool = False,
    fixed_at: datetime = FIXED_AT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Re-open the mis-scored entries, keeping what was withdrawn."""
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    rows = candidates(session, fixed_at=fixed_at)

    by_timeframe: dict[str, int] = {}
    by_outcome: dict[str, int] = {}
    for entry in rows:
        scale = entry.timeframe or "?"
        by_timeframe[scale] = by_timeframe.get(scale, 0) + 1
        verdict = entry.outcome or "?"
        by_outcome[verdict] = by_outcome.get(verdict, 0) + 1

        if not apply:
            continue

        after = dict(entry.after or {})
        entry.after = {
            "retracted": {
                "outcome": entry.outcome,
                "r_multiple": entry.r_multiple,
                "closed_at": entry.closed_at.isoformat() if entry.closed_at else None,
                "detail": after,
            },
            "reason": WHY,
            "retracted_at": moment.isoformat(),
        }
        entry.outcome = None
        entry.r_multiple = None
        entry.closed_at = None
        # Ahead of the rest of the backlog in the resolver's rotation: these
        # are the entries this deployment broke, and they are the ones the
        # scorecard is currently reading.
        entry.updated_at = datetime(2000, 1, 1, tzinfo=UTC)

    if apply:
        session.commit()

    return {
        "found": len(rows),
        "by_timeframe": by_timeframe,
        "by_outcome": by_outcome,
        "applied": apply,
    }


def main(argv: list[str] | None = None) -> int:
    """Print what would change; change it only when asked.

        docker exec molidotrade-collector-1 python -m app.workers.rescore
        docker exec molidotrade-collector-1 python -m app.workers.rescore --apply
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the change; without it nothing is modified",
    )
    args = parser.parse_args(argv)

    from app.db.session import session_scope

    with session_scope() as session:
        report = rescore(session, apply=args.apply)

    print(f"mis-scored entries: {report['found']:,}")
    for scale, count in sorted(report["by_timeframe"].items()):
        print(f"  {scale:<4} {count:>8,}")
    for verdict, count in sorted(report["by_outcome"].items()):
        print(f"  {verdict:<10} {count:>8,}")
    print("applied" if report["applied"] else "dry run - nothing was changed")
    return 0


if __name__ == "__main__":  # pragma: no cover - a command, not a code path
    raise SystemExit(main())
