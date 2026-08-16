"""Decide what happened to each recorded decision, from bars that came after it.

Without this the journal fills up and never produces a number. Every entry
stays open, `resolved` stays zero, and the comparison the whole project rests
on reports nothing forever - a failure that would look like patience for months
before anybody noticed it was silence.

The resolution is the same one the historical test used, and that is the point:
a forward series scored under different rules than the backtest is not a
confirmation of the backtest, it is a second unrelated measurement.

  stop     2.5x ATR(14) from entry, taken from what was recorded at the time
  target   1R the other way
  horizon  120 bars; unresolved after that is dropped, not counted as a loss

Three refusals matter more than the arithmetic:

**A bar that touched both is dropped, not guessed.** Within one bar there is no
way to know which came first, and the convention that picks one is a thumb on
the scale that shows up as an edge. The historical test dropped these too, so
dropping them here keeps the two comparable.

**An unresolved entry stays open rather than closing at zero.** A trade still
running is not a trade that broke even, and counting it as one makes every
measurement pessimistic exactly when the market was trending.

**Nothing is resolved from a bar at or before the entry.** The entry bar's own
high and low are not evidence about what happened next - using them is
lookahead wearing the costume of a fill.

**A decision is scored on the series it was taken on.** Both run in parallel,
and their prices differ by 33-39% of the stop distance on every major pair. A
decision whose entry, stop and target came from the public feed but whose fills
are read off the broker's bars starts a third of the way to its stop in a
random direction - which is larger than the entire edge being measured, and
would corrupt both series at once rather than telling us the difference between
them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import Timeframe
from app.models.instruments import Instrument, Provider
from app.models.journal import JournalEntry
from app.models.market_data import Bar

#: Bars to wait before giving up on an entry. The same horizon the measurement
#: used - a forward series scored over a different window is a different
#: measurement wearing the same name.
HORIZON = 120

#: The target, as a multiple of the risk. 1R, as tested.
TARGET_MULTIPLE = 1.0


def _outcome(
    bars: list[Bar], *, side: int, entry: float, stop: float, target: float
) -> tuple[str, float] | None:
    """What the bars after the entry did to it, or None if still undecided.

    None covers two different situations on purpose - not enough bars yet, and
    a bar that touched both levels - because both mean "this entry has not
    produced evidence", and the caller leaves it open either way.
    """
    reward = abs(target - entry) / abs(entry - stop)

    for bar in bars:
        high, low = float(bar.high), float(bar.low)
        if side > 0:
            hit_stop, hit_target = low <= stop, high >= target
        else:
            hit_stop, hit_target = high >= stop, low <= target

        if hit_stop and hit_target:
            # Both inside one bar. Which came first is unknowable at this
            # resolution, and the convention that picks one is a thumb on the
            # scale that shows up as an edge. The historical test dropped these
            # too, so dropping them keeps the two comparable.
            return None
        if hit_stop:
            return "loss", -1.0
        if hit_target:
            return "win", reward

    return None


def resolve_open(
    session: Session,
    *,
    timeframe: Timeframe = Timeframe.H1,
    now: datetime | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Close every open entry the market has answered.

    Bounded per pass so one cycle cannot spend an hour walking a backlog and
    starve the collection it rides on.
    """
    moment = (now or datetime.now(UTC)).astimezone(UTC)

    # `price_source` is the provider's own code, so this is a lookup rather than
    # a mapping table nobody remembers to extend when a third series arrives.
    providers = {
        code: identifier
        for code, identifier in session.execute(
            select(Provider.code, Provider.id)
        ).all()
    }

    open_entries = session.scalars(
        select(JournalEntry)
        .where(JournalEntry.closed_at.is_(None))
        .order_by(JournalEntry.opened_at)
        .limit(limit)
    ).all()

    resolved = 0
    still_open = 0
    abandoned = 0
    missing: list[str] = []
    by_source: dict[str, int] = {}

    for entry in open_entries:
        instrument = session.scalar(
            select(Instrument).where(Instrument.symbol == entry.symbol)
        )
        if instrument is None:
            # Named rather than silently skipped forever. An entry whose
            # instrument disappeared will otherwise sit open for the life of
            # the deployment and quietly shrink the sample.
            missing.append(entry.symbol)
            continue

        provider_id = providers.get(entry.price_source)
        if provider_id is None:
            # Named, not skipped quietly. An entry recorded against a series
            # this deployment cannot read will otherwise stay open forever and
            # shrink the sample without ever saying why.
            missing.append(
                f"{entry.symbol}: no provider named {entry.price_source} here, "
                "so the series it was decided on cannot be read"
            )
            continue

        # The levels as they were decided, not rebuilt from the ATR. A
        # resolver that recomputes them scores the trade against a geometry
        # the decision never had if either constant ever moves - and the two
        # are indistinguishable in the database afterwards.
        geometry = entry.before or {}
        price, stop, target = (
            geometry.get("entry"),
            geometry.get("stop"),
            geometry.get("target"),
        )
        if price is None or stop is None or target is None:
            missing.append(f"{entry.symbol}: no levels recorded with the decision")
            continue

        price, stop, target = float(price), float(stop), float(target)
        side = 1 if entry.decision == "long" else -1

        # Strictly after the entry bar. The entry bar's own high and low say
        # nothing about what happened next, and using them is lookahead
        # wearing the costume of a fill.
        bars = session.scalars(
            select(Bar)
            .where(
                Bar.instrument_id == instrument.id,
                Bar.timeframe == timeframe.value,
                # The series the decision was taken on, never the other one.
                # The two differ by a third of the stop distance, and the edge
                # being measured is a fiftieth of it.
                Bar.provider_id == provider_id,
                Bar.event_time > entry.opened_at,
                Bar.event_time <= moment,
            )
            .order_by(Bar.event_time)
            .limit(HORIZON)
        ).all()

        verdict = _outcome(list(bars), side=side, entry=price, stop=stop, target=target)

        if verdict is None:
            if len(bars) >= HORIZON:
                # The horizon ran out. Dropped rather than counted: the
                # historical test dropped these, and scoring them as breakeven
                # here would make the forward series measure something the
                # backtest never did.
                entry.closed_at = moment
                entry.outcome = "abandoned"
                entry.r_multiple = None
                entry.after = {
                    "reason": (
                        "neither the stop nor the target was reached within "
                        f"{HORIZON} bars, so this is dropped rather than scored "
                        "- the historical measurement dropped these too"
                    )
                }
                abandoned += 1
            else:
                still_open += 1
            continue

        outcome, r_multiple = verdict
        entry.closed_at = bars[-1].event_time
        entry.outcome = outcome
        entry.r_multiple = r_multiple
        entry.after = {
            "bars_to_resolve": len(bars),
            "price_source": entry.price_source,
        }
        resolved += 1
        by_source[entry.price_source] = by_source.get(entry.price_source, 0) + 1

    session.commit()
    return {
        "resolved": resolved,
        # Per series, because a pass that resolved forty on the public feed and
        # none on the broker's is not the same fact as one that resolved twenty
        # on each, and the total hides the difference.
        "resolved_by_source": by_source,
        "abandoned": abandoned,
        "still_open": still_open,
        "considered": len(open_entries),
        # Published, because an entry that can never resolve shrinks the sample
        # every measurement rests on, and does it silently.
        "unresolvable": missing,
    }
