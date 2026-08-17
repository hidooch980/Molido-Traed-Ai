"""Store what the brain decided, and compare the two arms afterwards.

`app/brain/journal.py` decides what a decision is and refuses to score one it
cannot; this puts those decisions somewhere they survive a restart, and answers
the one question the whole forward measurement exists for: **did the rule beat
the coin flip on the same bars?**

Two arms in one table. A comparison is then a filter rather than a join between
two shapes that drift apart, and - more importantly - it is impossible to build
the rule's series while forgetting the control's, which is exactly the mistake
that produced a CONFIRMED on a result with no edge.

Nothing here invents a value. A decision with no probability is stored with
none, because 0.5 is a forecast the system never made and is indistinguishable
afterwards from one it did. An open entry has no outcome rather than a
placeholder outcome. Every count this module returns is a count of things that
actually happened.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.learning import control as control_module
from app.learning import readiness as readiness_module
from app.models.journal import (
    ARM_CONTROL,
    ARM_RULE,
    SOURCE_PUBLIC,
    JournalEntry,
)

#: When the forward measurement begins. Entries before it are excluded from the
#: comparison and kept in the table.
#:
#: Everything recorded before this came from code with three bugs in it: the
#: cross-section's instant was the newest bar anywhere, which on a weekend is a
#: crypto bar; two frozen duplicates of live symbols were still being ranked;
#: and every series was read up to *now* rather than up to the instant, so a
#: Friday ranking carried Saturday prices.
#:
#: They are not deleted. They are the record of what the system did while it
#: was being debugged, and a table that quietly loses its own history is worse
#: evidence than one with a stated cut. But they are not measurements of
#: anything, and a series that proves or kills an edge cannot contain them.
#:
#: The date is the Monday the markets reopen after those fixes shipped. Written
#: here rather than passed in, so the window is a fact about the deployment
#: that a reader can check, not an argument somebody chose at reporting time.
MEASUREMENT_STARTS_AT = datetime(2026, 8, 17, 0, 0, tzinfo=UTC)


@dataclass(frozen=True)
class Recorded:
    """What was written, and whether it was new."""

    entry_id: uuid.UUID | None
    arm: str
    new: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "entry_id": str(self.entry_id) if self.entry_id else None,
            "arm": self.arm,
            "new": self.new,
        }


def record_decision(
    session: Session,
    *,
    symbol: str,
    decision: str,
    at: datetime,
    arm: str = ARM_RULE,
    price_source: str = SOURCE_PUBLIC,
    account_key: str | None = None,
    probability: float | None = None,
    before: dict[str, Any] | None = None,
    during: dict[str, Any] | None = None,
) -> Recorded:
    """Write one decision. Idempotent on (symbol, bar, arm).

    The loop republishes the same decision whenever one cycle overlaps the
    previous, and a duplicated entry inflates the very sample the measurement
    rests on - so the constraint decides, not the caller's care.
    """
    moment = at.astimezone(UTC)
    existing = session.scalar(
        select(JournalEntry).where(
            JournalEntry.symbol == symbol,
            JournalEntry.opened_at == moment,
            JournalEntry.arm == arm,
            JournalEntry.price_source == price_source,
        )
    )
    if existing is not None:
        return Recorded(entry_id=existing.id, arm=arm, new=False)

    entry = JournalEntry(
        symbol=symbol,
        decision=decision,
        account_key=account_key,
        opened_at=moment,
        probability=probability,
        arm=arm,
        price_source=price_source,
        before=before or {},
        during=during or {},
    )
    session.add(entry)
    session.flush()
    return Recorded(entry_id=entry.id, arm=arm, new=True)


def record_with_control(
    session: Session,
    *,
    symbol: str,
    decision: str,
    at: datetime,
    price: float,
    stop_distance: float,
    price_source: str = SOURCE_PUBLIC,
    account_key: str | None = None,
    probability: float | None = None,
    before: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write the decision and its control together, or neither.

    One call, because the two must never diverge. A rule series built over
    months beside a control series that was skipped on the days somebody was
    debugging is a comparison with a hole in it, and the hole is invisible
    afterwards.
    """
    rule = record_decision(
        session,
        symbol=symbol,
        decision=decision,
        at=at,
        arm=ARM_RULE,
        price_source=price_source,
        account_key=account_key,
        probability=probability,
        before=before,
    )

    entry = control_module.entry_for(
        symbol=symbol, at=at, price=price, stop_distance=stop_distance
    )
    if entry is None:
        # The control could not be formed, so the rule's row is marked as
        # having no partner rather than left looking like a matched pair. An
        # unmatched entry silently included in a comparison is a bias.
        return {
            "rule": rule.as_dict(),
            "control": None,
            "reason": (
                "the geometry was unusable, so no control was formed - this "
                "decision is excluded from the comparison rather than counted "
                "against a partner that does not exist"
            ),
        }

    control_row = record_decision(
        session,
        symbol=symbol,
        decision="long" if entry.side > 0 else "short",
        at=at,
        arm=ARM_CONTROL,
        price_source=price_source,
        account_key=account_key,
        # The series is stamped on the control's reasoning as well as the
        # rule's. The control is a decision on a price series too, and one
        # whose row says which series it came from beside a partner whose row
        # does not is a pair that cannot be checked afterwards.
        #
        # The timeframe rides along for the same reason and a sharper one. The
        # control is the only benchmark the rule is measured against, so any
        # grouping applied to one has to reach the other: group the rule by
        # timeframe while its control carries none and every bucket compares
        # against an empty set - which does not read as an error, it reads as
        # a rule with no control, and the honest-looking answer is silence.
        before={
            **entry.as_dict(),
            "price_source": price_source,
            **(
                {"timeframe": (before or {}).get("timeframe")}
                if (before or {}).get("timeframe")
                else {}
            ),
        },
    )
    return {"rule": rule.as_dict(), "control": control_row.as_dict()}


def close(
    session: Session,
    entry_id: uuid.UUID,
    *,
    outcome: str,
    r_multiple: float | None = None,
    after: dict[str, Any] | None = None,
    at: datetime | None = None,
) -> bool:
    """Resolve one entry. Returns whether it changed anything.

    An entry already closed is left alone rather than overwritten. A late
    duplicate resolution would rewrite a result that has already been counted.
    """
    entry = session.get(JournalEntry, entry_id)
    if entry is None or entry.closed_at is not None:
        return False

    entry.closed_at = (at or datetime.now(UTC)).astimezone(UTC)
    entry.outcome = outcome
    entry.r_multiple = r_multiple
    entry.after = after or {}
    session.flush()
    return True


def comparison(
    session: Session,
    *,
    since: datetime | None = None,
    price_source: str = SOURCE_PUBLIC,
) -> control_module.Comparison:
    """The rule against the control, over resolved entries only.

    Open entries are excluded from both arms. Counting an open position as a
    loss because it has not closed yet would make every measurement pessimistic
    in exactly the periods the system was most active.

    `since` defaults to `MEASUREMENT_STARTS_AT` rather than to the beginning of
    the table. Everything before that was recorded by code with three known
    bugs in it, and a comparison that silently included them would be a
    comparison of the debugging period.
    """
    if since is None:
        since = MEASUREMENT_STARTS_AT

    def tally(arm: str) -> tuple[int, int]:
        query = select(
            func.count().filter(JournalEntry.r_multiple > 0),
            func.count().filter(JournalEntry.r_multiple <= 0),
        ).where(
            JournalEntry.arm == arm,
            JournalEntry.price_source == price_source,
            JournalEntry.closed_at.is_not(None),
            JournalEntry.r_multiple.is_not(None),
        )
        if since is not None:
            query = query.where(JournalEntry.opened_at >= since)
        wins, losses = session.execute(query).one()
        return int(wins or 0), int(losses or 0)

    rule_wins, rule_losses = tally(ARM_RULE)
    control_wins, control_losses = tally(ARM_CONTROL)

    return control_module.Comparison(
        rule_wins=rule_wins,
        rule_losses=rule_losses,
        control_wins=control_wins,
        control_losses=control_losses,
    )


def summary(session: Session) -> dict[str, Any]:
    """What the journal holds, on both price series.

    Two comparisons, because the two answer different questions. The public
    feed carries the universe the rule was tested on and is a market nobody can
    trade in; the broker carries the prices that actually fill. The gap between
    the two results is the measurement neither gives alone: how much of the edge
    the difference between quoted and filled prices eats.
    """
    from app.models.journal import SOURCE_BROKER

    totals = session.execute(
        select(
            JournalEntry.price_source,
            JournalEntry.arm,
            func.count(JournalEntry.id),
            func.count(JournalEntry.closed_at),
            func.min(JournalEntry.opened_at),
            func.max(JournalEntry.opened_at),
        ).group_by(JournalEntry.price_source, JournalEntry.arm)
    ).all()

    by_arm: dict[str, dict[str, Any]] = {}
    for source, arm, recorded, resolved, first, last in totals:
        by_arm.setdefault(source, {})[arm] = {
            "recorded": int(recorded or 0),
            "resolved": int(resolved or 0),
            # Stated rather than left to subtraction. "40 recorded, 12
            # resolved" reads as two unrelated numbers until the third is
            # spelled out.
            "still_open": int(recorded or 0) - int(resolved or 0),
            "first_at": first.isoformat() if first else None,
            "last_at": last.isoformat() if last else None,
        }

    public = comparison(session, price_source=SOURCE_PUBLIC)
    broker = comparison(session, price_source=SOURCE_BROKER)

    slippage = None
    if public.edge is not None and broker.edge is not None:
        # What the gap between quoted and filled prices costs. Positive means
        # the edge survived the move to real prices; negative means it did not.
        slippage = round(broker.edge - public.edge, 4)

    return {
        "arms": by_arm,
        "comparison": public.as_dict(),
        "by_source": {
            SOURCE_PUBLIC: public.as_dict(),
            SOURCE_BROKER: broker.as_dict(),
        },
        "edge_lost_to_real_prices": slippage,
        "why_two_series": (
            "the broker's prices and the public feed's differ by 33-39% of the "
            "stop distance on every major pair, measured over 490 shared hourly "
            "bars, and the edge being looked for is 0.021 R. The public series "
            "has the universe the rule was tested on and is a market nobody can "
            "trade in; the broker series has the prices that actually fill"
        ),
        # Stated, so nobody has to guess which entries the numbers above cover.
        "measurement_starts_at": MEASUREMENT_STARTS_AT.isoformat(),
        "why_it_starts_there": (
            "everything recorded before that came from code with three bugs: "
            "the cross-section's instant was the newest bar anywhere, which on "
            "a weekend is a crypto bar; two frozen duplicates of live symbols "
            "were still ranked; and every series was read up to now rather than "
            "up to the instant, so a Friday ranking carried Saturday prices. "
            "Those entries are kept and excluded"
        ),
        "note": (
            "the comparison counts resolved entries only. An open position "
            "counted as a loss would make every measurement pessimistic in "
            "exactly the periods the system was most active"
        ),
    }


#: How long the measurement must have been running before a rate is published.
#:
#: Three instants in the first two hours is 180 a week, and a projected date
#: built on it would be confident and meaningless. A week is the shortest
#: window that contains a weekend - the thing that most changes the rate.
MIN_OBSERVATION = timedelta(days=7)


def readiness_of(
    session: Session,
    *,
    price_source: str = SOURCE_PUBLIC,
    now: datetime | None = None,
) -> readiness_module.Readiness:
    """How far this series is from being able to answer the question.

    Counts instants, not decisions. The rule takes both tails of one
    cross-section at one moment, so the eight rows written at one instant are
    one piece of evidence about one market move. Counting rows would report
    eight times the progress that exists, and the historical measurement has
    already shown what that does to a significance figure.
    """
    moment = (now or datetime.now(UTC)).astimezone(UTC)

    instants, decisions = session.execute(
        select(
            func.count(func.distinct(JournalEntry.opened_at)),
            func.count(JournalEntry.id),
        ).where(
            JournalEntry.arm == ARM_RULE,
            JournalEntry.price_source == price_source,
            JournalEntry.closed_at.is_not(None),
            JournalEntry.r_multiple.is_not(None),
            JournalEntry.opened_at >= MEASUREMENT_STARTS_AT,
        )
    ).one()

    elapsed = moment - MEASUREMENT_STARTS_AT
    rate: float | None = None
    if elapsed >= MIN_OBSERVATION and instants:
        rate = int(instants) / (elapsed.total_seconds() / 604800.0)

    return readiness_module.assess(
        instants_resolved=int(instants or 0),
        decisions_resolved=int(decisions or 0),
        instants_per_week=rate,
        today=moment.date(),
        open_requirements=_open_requirements(),
        met_requirements=_met_requirements(),
    )


def _open_requirements() -> tuple[str, ...]:
    """What still stands between the current state and a connected account.

    Read from the edge registry rather than restated here. A second copy of
    these conditions is a second thing to update, and the one nobody updates
    becomes a claim the system makes about itself that is no longer true.
    """
    from app.learning import edge as edge_module

    if edge_module.PROVEN:
        return ()

    open_now: list[str] = []
    for claim in edge_module.PENDING_FORWARD:
        verdict = edge_module.assess(claim.evidence, pre_registered=claim.pre_registered)
        open_now.extend(verdict.failures)
    return tuple(open_now)


def _met_requirements() -> tuple[str, ...]:
    from app.learning import edge as edge_module

    met: list[str] = []
    for claim in edge_module.PENDING_FORWARD:
        verdict = edge_module.assess(claim.evidence, pre_registered=claim.pre_registered)
        met.extend(verdict.passes)
    return tuple(met)
