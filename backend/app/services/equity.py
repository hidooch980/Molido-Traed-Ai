"""Keep the account's equity series, and answer the questions it exists for.

Two questions, and they are not the same one:

  `peak_equity`      the highest equity ever recorded. What a peak-trailing
                     floor is measured from.
  `peak_day_open`    the highest balance recorded at a day boundary. What
                     FTMO's floor is actually written against: "the highest
                     account balance achieved at 00:00 CE(S)T of any preceding
                     trading day".

Reading one where the provider means the other moves the floor by however far
equity ran intraday, which on a good day is the whole of that day's profit.
They are separate functions so a caller has to pick, and the rulebook says
which.

Every function here returns None when there is no data rather than a number
standing in for one. None means nobody was watching. That is not the same fact
as "the peak is today's equity", and the second one places a floor at today's
level and reports rope the account does not have.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.equity import EquitySample

#: FTMO recalculates at 00:00 CE(S)T. Recorded as the offset rather than a
#: timezone name so the boundary is explicit in the query, and so a reader can
#: see immediately that it is not UTC midnight.
DAY_BOUNDARY_OFFSET = timedelta(hours=2)

#: How close to the boundary a sample must be to count as that day's open. The
#: bridge publishes every twenty seconds, so anything inside a few minutes is
#: the same snapshot for this purpose - and requiring an exact 00:00:00 match
#: would mean no day ever has an open.
DAY_OPEN_WINDOW = timedelta(minutes=10)


@dataclass(frozen=True)
class Series:
    """What is known about one account's history, and over what span."""

    account_key: str
    samples: int
    first_at: datetime | None
    last_at: datetime | None
    peak_equity: float | None
    peak_day_open_balance: float | None

    @property
    def measured(self) -> bool:
        return self.samples > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "account_key": self.account_key,
            "samples": self.samples,
            "first_at": self.first_at.isoformat() if self.first_at else None,
            "last_at": self.last_at.isoformat() if self.last_at else None,
            "peak_equity": self.peak_equity,
            "peak_day_open_balance": self.peak_day_open_balance,
            "note": (
                "peak equity is the highest ever seen; the day-open peak is the "
                "highest balance at a day boundary, which is what FTMO's "
                "trailing floor is written against. They differ by however far "
                "equity ran intraday"
                if self.samples
                else "nothing has been recorded for this account, so no "
                "trailing floor can be placed"
            ),
        }


def record(
    session: Session,
    *,
    account_key: str,
    equity: float,
    balance: float,
    margin: float = 0.0,
    open_positions: int = 0,
    currency: str = "USD",
    at: datetime | None = None,
) -> bool:
    """Store one snapshot. Returns whether it was new.

    Idempotent on (account, instant). The bridge republishes the same snapshot
    whenever this runs faster than the terminal does, and a duplicated peak is
    harmless while a duplicated count is not - it makes a quiet hour look busy
    to anything measuring how often the account was actually sampled.
    """
    moment = (at or datetime.now(UTC)).astimezone(UTC)

    statement = (
        pg_insert(EquitySample)
        .values(
            id=uuid.uuid4(),
            account_key=account_key,
            recorded_at=moment,
            equity=equity,
            balance=balance,
            margin=margin,
            open_positions=open_positions,
            currency=currency,
        )
        .on_conflict_do_nothing(
            index_elements=["account_key", "recorded_at"],
        )
    )
    # `returning` rather than rowcount: a CursorResult exposes rowcount but the
    # generic Result type does not, and mypy is right to object - the attribute
    # is only there on some drivers. Asking the statement to return the id makes
    # "was it new" a value rather than a driver detail.
    inserted = session.execute(statement.returning(EquitySample.id)).first()
    return inserted is not None


def peak_equity(
    session: Session, account_key: str, *, since: datetime | None = None
) -> float | None:
    """The highest equity ever recorded, or None if nothing was recorded."""
    query = select(func.max(EquitySample.equity)).where(
        EquitySample.account_key == account_key
    )
    if since is not None:
        query = query.where(EquitySample.recorded_at >= since)
    value = session.scalar(query)
    return float(value) if value is not None else None


def peak_day_open_balance(
    session: Session, account_key: str, *, before: datetime | None = None
) -> float | None:
    """The highest balance recorded at a day boundary, or None.

    This is the number FTMO's floor trails, and it is deliberately not the
    highest balance overall: a balance that peaked at noon and fell back before
    midnight never raised the floor, and treating it as though it had reports
    less rope than the account really has.

    `before` excludes the current day, because the rule says "any preceding
    trading day" - including today would let a floor rise on the same session
    it is being checked against.
    """
    cutoff = (before or datetime.now(UTC)).astimezone(UTC)
    rows = session.execute(
        select(EquitySample.recorded_at, EquitySample.balance)
        .where(
            EquitySample.account_key == account_key,
            EquitySample.recorded_at < cutoff,
        )
        .order_by(EquitySample.recorded_at)
    ).all()
    if not rows:
        return None

    best: float | None = None
    seen_days: set[date] = set()
    for recorded_at, balance in rows:
        stamped = recorded_at.astimezone(UTC) + DAY_BOUNDARY_OFFSET
        # The first sample at or just after each day boundary is that day's
        # open. Taken from the series rather than requiring an exact 00:00:00
        # row, because the bridge publishes on its own clock and no sample
        # lands precisely on the boundary.
        boundary_day = stamped.date()
        if boundary_day in seen_days:
            continue
        seen_days.add(boundary_day)
        midnight = datetime.combine(boundary_day, datetime.min.time(), tzinfo=UTC)
        if stamped - midnight > DAY_OPEN_WINDOW and best is not None:
            # The first sample of this day arrived well after the boundary -
            # the writer was down over midnight. Skipped rather than used: a
            # mid-morning balance is not a day-open balance, and using it would
            # raise the floor on a number the rule never looked at.
            continue
        value = float(balance)
        best = value if best is None else max(best, value)
    return best


def series(session: Session, account_key: str) -> Series:
    """Everything known about one account's recorded history."""
    row = session.execute(
        select(
            func.count(EquitySample.id),
            func.min(EquitySample.recorded_at),
            func.max(EquitySample.recorded_at),
        ).where(EquitySample.account_key == account_key)
    ).one()
    count, first_at, last_at = row

    return Series(
        account_key=account_key,
        samples=int(count or 0),
        first_at=first_at,
        last_at=last_at,
        peak_equity=peak_equity(session, account_key),
        peak_day_open_balance=peak_day_open_balance(session, account_key),
    )
