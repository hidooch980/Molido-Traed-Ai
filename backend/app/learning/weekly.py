"""The weekly scorecard: what every brain actually did, from the live journal.

The journal fills every fifteen minutes and nobody reads it on a schedule, so
the question the whole fleet exists to answer - which brain is earning its
vote - had no standing answer. This produces one, weekly, from the same rows
the measurement harness uses, and prints it the same way whichever direction
it comes out.

Two rules carried over from everything else here:

**Each brain is compared to its own control, never to another brain's.** The
control rides with its rule's strategy (the journal stamps both), so the
difference is paired on the same instants and the common market factor drops
out. Comparing brain A's raw R to brain B's raw R across different symbols
and instants is a comparison of their weeks, not their judgement.

**Small n is said, not smoothed.** A brain with nine resolved decisions gets
its numbers printed beside the word that they are nine decisions. The
scorecard module already learned this lesson the expensive way; this report
does not un-learn it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.journal import ARM_CONTROL, ARM_RULE, JournalEntry

#: Below this many resolved decisions, a mean R is an anecdote. The scorecard
#: threshold is 50 for a verdict; this is a weekly progress report, so it
#: labels rather than withholds - but it labels loudly.
THIN_SAMPLE = 30


@dataclass(frozen=True)
class BrainWeek:
    """One brain's week, beside its own control."""

    strategy: str
    decided: int
    resolved: int
    wins: int
    total_r: float
    control_resolved: int
    control_total_r: float

    @property
    def mean_r(self) -> float | None:
        return self.total_r / self.resolved if self.resolved else None

    @property
    def control_mean_r(self) -> float | None:
        if not self.control_resolved:
            return None
        return self.control_total_r / self.control_resolved

    @property
    def edge_r(self) -> float | None:
        """Mean R minus the control's mean R. Unpaired week-level reading -
        an indicator for the weekly page, not a substitute for `measure`."""
        if self.mean_r is None or self.control_mean_r is None:
            return None
        return self.mean_r - self.control_mean_r

    @property
    def thin(self) -> bool:
        return self.resolved < THIN_SAMPLE

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "decided": self.decided,
            "resolved": self.resolved,
            "wins": self.wins,
            "win_rate": round(self.wins / self.resolved, 3) if self.resolved else None,
            "total_r": round(self.total_r, 3),
            "mean_r": round(self.mean_r, 4) if self.mean_r is not None else None,
            "control_mean_r": (
                round(self.control_mean_r, 4)
                if self.control_mean_r is not None
                else None
            ),
            "edge_r": round(self.edge_r, 4) if self.edge_r is not None else None,
            "thin_sample": self.thin,
        }


def build_report(session: Session, *, days: int = 7) -> dict[str, Any]:
    """Every brain's week from the journal, and every account's orders.

    Reads only; the report is a view of what already happened, and a report
    that writes is a report somebody will one day be afraid to run.
    """
    since = datetime.now(UTC) - timedelta(days=days)
    rows = session.scalars(
        select(JournalEntry).where(JournalEntry.opened_at >= since)
    ).all()

    brains: dict[str, dict[str, Any]] = {}
    orders_by_login: dict[str, dict[str, Any]] = {}

    for row in rows:
        bucket = brains.setdefault(
            row.strategy,
            {
                "decided": 0,
                "resolved": 0,
                "wins": 0,
                "total_r": 0.0,
                "control_resolved": 0,
                "control_total_r": 0.0,
            },
        )
        if row.arm == ARM_RULE:
            bucket["decided"] += 1
            if row.r_multiple is not None:
                bucket["resolved"] += 1
                bucket["total_r"] += float(row.r_multiple)
                if row.r_multiple > 0:
                    bucket["wins"] += 1
        elif row.arm == ARM_CONTROL and row.r_multiple is not None:
            bucket["control_resolved"] += 1
            bucket["control_total_r"] += float(row.r_multiple)

        # Orders live on the rule rows, keyed by the account that sent them.
        for login, order in ((row.during or {}).get("orders") or {}).items():
            account = orders_by_login.setdefault(
                login, {"sent": 0, "filled": 0, "rejected": 0, "resolved_r": 0.0}
            )
            account["sent"] += 1
            state = str(order.get("state") or "")
            if "filled" in state:
                account["filled"] += 1
                if row.r_multiple is not None:
                    account["resolved_r"] += float(row.r_multiple)
            elif "rejected" in state:
                account["rejected"] += 1

    weeks = [
        BrainWeek(
            strategy=name,
            decided=b["decided"],
            resolved=b["resolved"],
            wins=b["wins"],
            total_r=b["total_r"],
            control_resolved=b["control_resolved"],
            control_total_r=b["control_total_r"],
        )
        for name, b in sorted(brains.items())
    ]

    return {
        "window_days": days,
        "since": since.isoformat(),
        "brains": [week.as_dict() for week in weeks],
        "accounts": {
            login: {**counts, "resolved_r": round(counts["resolved_r"], 3)}
            for login, counts in sorted(orders_by_login.items())
        },
        "note": (
            "edge_r here is an unpaired week-level indicator beside each "
            "brain's own control - a progress page, not a verdict. Verdicts "
            "come from `measure` and the scorecard thresholds, and a thin "
            "sample is labelled rather than smoothed"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    """Print the weekly scorecard: `python -m app.learning.weekly [--days 7]`."""
    import argparse
    import json

    from app.db.session import session_scope

    parser = argparse.ArgumentParser(description="The weekly brain scorecard.")
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args(argv)

    with session_scope() as session:
        report = build_report(session, days=args.days)

    print(json.dumps(report, indent=1, ensure_ascii=False))

    print()
    for brain in report["brains"]:
        thin = " (thin sample)" if brain["thin_sample"] else ""
        edge = brain["edge_r"]
        print(
            f"{brain['strategy']}: {brain['decided']} decided, "
            f"{brain['resolved']} resolved, "
            f"total {brain['total_r']:+.2f} R, "
            f"edge vs own control "
            f"{'unmeasured' if edge is None else f'{edge:+.4f} R'}{thin}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
