"""What the broker's clock actually reads, measured rather than assumed.

MetaTrader stamps bars in the terminal's own timezone and publishes no offset.
`broker_bars.py` assumed GMT+0 and said so in a comment. It was wrong: aligning
EURUSD against the public feed puts the best match at +3, and the assumption
cost more than a shifted series.

    lag  0h   8.67 pips mean absolute difference
    lag +3h   3.99 pips                            <- less than half

Three things followed from the wrong assumption, and two of them were reported
as findings before anybody checked:

  The "33-39% of a stop distance" gap between the broker and the public feed -
  the number that justified running the whole measurement on two price series -
  was substantially this bug. Comparing bars three hours apart and calling the
  difference a venue spread.

  The cross-section's instant differed by an hour between the two series and
  that was explained as a real difference in session boundaries. It was not.

  Every broker bar sat three hours in the future, so the newest one was stamped
  02:00 while the clock read 00:32.

The offset is derived here rather than written down, because most brokers move
with daylight saving - RoboForex runs GMT+2 in winter and GMT+3 in summer - and
a constant would be right for six months and silently wrong for the other six.
That is the same shape of failure it is replacing.

It is derived by alignment, not by asking the terminal. The terminal could be
asked, and should be one day, but a value the platform can check itself beats a
value it is told: this one is verified against prices that already exist here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.instruments import Instrument, Provider
from app.models.market_data import Bar

#: Offsets to try, in hours. Wide enough to cover every broker convention from
#: New York to Auckland, so a broker change is measured rather than missed.
CANDIDATES = tuple(range(-12, 15))

#: Bars that must overlap before an offset is believed. Below this the winner
#: is noise, and a wrong offset applied confidently is worse than none.
MIN_OVERLAP = 100

#: How much better the winner must be than the runner-up, as a ratio of mean
#: error. A flat curve means the alignment found nothing and the answer should
#: be "unknown" rather than "whichever was marginally lowest".
MIN_MARGIN = 1.15

#: The instrument to align on. The most liquid pair, so the two feeds agree
#: most closely when they are aligned and disagree most visibly when not.
REFERENCE_SYMBOL = "EURUSD"


def _aware(moment: Any) -> Any:
    """A timestamp that can be compared with another timestamp."""
    if getattr(moment, "tzinfo", None) is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


@dataclass(frozen=True)
class Offset:
    """The measured offset, and whether it is trustworthy."""

    hours: int | None
    overlap: int
    error_pips: float | None
    runner_up_pips: float | None
    reason: str | None = None
    #: Broker-stamped first bar this offset is true for, or None for the whole
    #: file. Set when the broker's clock moved (daylight saving) inside the
    #: published window: bars before it were on the old clock and are already
    #: stored at the right instants, so they must not be re-filed at the new one.
    valid_from: datetime | None = None

    @property
    def known(self) -> bool:
        return self.hours is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "hours": self.hours,
            "known": self.known,
            "overlap": self.overlap,
            "error_pips": self.error_pips,
            "runner_up_pips": self.runner_up_pips,
            "reason": self.reason,
            "valid_from": None if self.valid_from is None else self.valid_from.isoformat(),
            "note": (
                "measured by aligning the broker series against the public one, "
                "not read from a constant. Most brokers move with daylight "
                "saving, so a written-down offset is right for six months and "
                "silently wrong for the other six"
            ),
        }


def align(
    public: dict[Any, float], broker: dict[Any, float]
) -> Offset:
    """The lag that best matches two price series, or why there isn't one.

    Pure, and separate from the database read for a reason that only appeared
    when the first ingest ran: on a fresh deployment the broker has no stored
    bars yet, so measuring from the database can never succeed on the first
    pass and the ingest would refuse forever. The ingest aligns the rows it is
    holding instead.
    """
    if not public or not broker:
        return Offset(None, 0, None, None, "one of the two series is empty")

    # Both sides normalised to aware UTC before anything is compared.
    #
    # The database hands back naive datetimes and the file parser hands back
    # aware ones, so an aware key never equals a naive one and the overlap is
    # zero at every lag - which this reports as "not enough shared history",
    # a true statement about a comparison that never happened.
    #
    # Which is this module's own subject matter, in the module itself: two
    # clocks that look the same and are not.
    public = {_aware(when): value for when, value in public.items()}
    broker = {_aware(when): value for when, value in broker.items()}

    scored: list[tuple[float, int, int]] = []
    for lag in CANDIDATES:
        shift = timedelta(hours=lag)
        pairs = [
            (value, public[when - shift])
            for when, value in broker.items()
            if (when - shift) in public
        ]
        if len(pairs) < MIN_OVERLAP:
            continue
        error = sum(abs(a - b) for a, b in pairs) / len(pairs)
        scored.append((error, lag, len(pairs)))

    if not scored:
        return Offset(
            None,
            0,
            None,
            None,
            f"no candidate offset overlapped {MIN_OVERLAP} bars, so there is "
            "not enough shared history to align on",
        )

    scored.sort()
    best_error, best_lag, overlap = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else None

    # A flat curve means the alignment found nothing. Saying "unknown" is the
    # honest answer; picking the marginally lowest is how a wrong offset gets
    # applied with confidence.
    #
    # Zero needs care in both directions, and I got it wrong twice writing
    # this. A constant price series scores zero at *every* lag, so a ratio test
    # guarded by `best_error > 0` skips itself and returns whichever candidate
    # sorted first. But zero at the best lag with a non-zero runner-up is the
    # opposite: a perfect match. The distinction is whether the runner-up is
    # also zero.
    if runner_up is None:
        ambiguous = False
    elif best_error <= 0:
        ambiguous = runner_up <= 0
    else:
        ambiguous = runner_up / best_error < MIN_MARGIN

    if ambiguous:
        return Offset(
            None,
            overlap,
            round(best_error * 10_000, 2),
            round((runner_up or 0.0) * 10_000, 2),
            f"the best offset ({best_lag:+d}h) is not clearly better than the "
            "next one, so the two series cannot be aligned on this evidence",
        )

    return Offset(
        hours=best_lag,
        overlap=overlap,
        error_pips=round(best_error * 10_000, 2),
        # `is not None`, not truthiness: an error of exactly 0.0 is a real
        # measurement and reporting it as "no runner-up" hides the tie that
        # should have made this unknown in the first place.
        runner_up_pips=(
            round(runner_up * 10_000, 2) if runner_up is not None else None
        ),
    )


def public_closes(
    session: Session,
    *,
    symbol: str = REFERENCE_SYMBOL,
    timeframe: str = "H1",
    since: datetime | None = None,
) -> dict[Any, float]:
    """The public feed's closes for the reference instrument.

    `since` bounds the read. Alignment only ever pairs a broker bar with a
    public bar a few hours either side of it, so nothing older than the
    broker's first bar can count - and an unbounded read planned across every
    chunk of the table, four seconds each time, several times a cycle.
    """
    instrument = session.scalar(select(Instrument).where(Instrument.symbol == symbol))
    provider = session.scalar(select(Provider.id).where(Provider.code == "yfinance"))
    if instrument is None or provider is None:
        return {}
    conditions = [
        Bar.instrument_id == instrument.id,
        Bar.timeframe == timeframe,
        Bar.provider_id == provider,
    ]
    if since is not None:
        conditions.append(Bar.event_time >= since)
    rows = session.execute(
        select(Bar.event_time, Bar.close)
        .where(*conditions)
        .order_by(Bar.event_time, Bar.revision)
    ).all()
    return {when: float(close) for when, close in rows}


def measure(
    session: Session,
    *,
    symbol: str = REFERENCE_SYMBOL,
    timeframe: str = "H1",
) -> Offset:
    """Find the lag that best aligns the broker's bars with the public feed.

    Returns an Offset with `hours=None` rather than a guess whenever the
    evidence is thin or the curve is flat. An unknown offset stops the ingest;
    a wrong one corrupts every bar it touches and looks completely normal.
    """
    broker_provider = session.scalar(
        select(Provider.id).where(Provider.code == "metatrader")
    )
    instrument = session.scalar(select(Instrument).where(Instrument.symbol == symbol))
    if instrument is None or broker_provider is None:
        return Offset(None, 0, None, None, "both providers must have bars to align")

    rows = session.execute(
        select(Bar.event_time, Bar.close).where(
            Bar.instrument_id == instrument.id,
            Bar.timeframe == timeframe,
            Bar.provider_id == broker_provider,
        ).order_by(Bar.event_time, Bar.revision)
    ).all()

    return align(
        public_closes(session, symbol=symbol, timeframe=timeframe),
        {when: float(close) for when, close in rows},
    )


#: How far the newest closed bar may sit from a whole-hour offset of the wall
#: clock and still count as a live reading. Wider than the bridge's publish lag
#: (seconds to about a minute), far narrower than half an hour. Narrow is not
#: enough on its own: a stale bar still lands on a whole hour for ten minutes
#: of every hour, which is what `market_shut` and `DST_STEP_HOURS` are for.
LIVE_TOLERANCE = timedelta(minutes=5)

#: A broker clock moves by one hour at a daylight-saving change and by nothing
#: else in normal operation.
DST_STEP_HOURS = 1

#: FX is shut from Friday's New York close to Sunday's reopen. The close is
#: 21:00 UTC in US summer time and 22:00 UTC in winter, the reopen the same
#: hours on Sunday; the window starts an hour early and ends at the later
#: reopen so both seasons are covered.
#:
#: Why it matters (2026-10-30/31): after Friday's close the newest M1 bar stays
#: put while the wall clock runs on. Once an hour, for ten minutes, the stale
#: close sits within LIVE_TOLERANCE of a whole hour, and live_hours read that as
#: the broker's clock: +1h at 21:54 UTC Friday, then -4h ... -12h through
#: Saturday morning. Every bar ingested in those minutes was written at the
#: wrong instant - 167 XAUUSD M5 bars on a Saturday, 38 symbols in all.
FRIDAY, SATURDAY, SUNDAY = 4, 5, 6
WEEKEND_FROM_HOUR = 20  # Friday, UTC
WEEKEND_UNTIL_HOUR = 22  # Sunday, UTC


def market_shut(now: datetime) -> bool:
    """True while FX is closed for the weekend, when no bar is a clock."""
    moment = _aware(now)
    day, hour = moment.weekday(), moment.hour
    return (
        (day == FRIDAY and hour >= WEEKEND_FROM_HOUR)
        or day == SATURDAY
        or (day == SUNDAY and hour < WEEKEND_UNTIL_HOUR)
    )


def in_fx_weekend(moment: datetime) -> bool:
    """True from Friday 21:00 UTC to Sunday 21:00 UTC.

    Covers the FX close in both summer (21:00 UTC) and winter (22:00 UTC) and
    ends before either Sunday open. A live reading implying a newest close in
    this window can only come from a frozen Friday bar, so it is refused; the
    alignment stands, and that offset only re-files bars already stored.
    """
    moment = _aware(moment).astimezone(UTC)
    day, hour = moment.weekday(), moment.hour
    return (day == 4 and hour >= 21) or day == 5 or (day == 6 and hour < 21)


def live_hours(latest_close: Any, now: datetime) -> int | None:
    """The offset the terminal's clock shows right now, or None.

    `latest_close` is the broker-stamped close of the newest closed bar (its
    open plus one bar). While the market trades that close is a few seconds
    behind the wall clock in the broker's zone, so the gap rounds to a whole
    hour. When it does not - market shut, terminal stalled - there is no
    reading, and the alignment stands.
    """
    if latest_close is None or market_shut(now):
        return None
    gap = _aware(latest_close) - _aware(now)
    hours = round(gap / timedelta(hours=1))
    if abs(gap - timedelta(hours=hours)) > LIVE_TOLERANCE:
        return None
    if hours not in CANDIDATES:
        return None
    return hours


def current(aligned: Offset, latest_close: Any, now: datetime) -> Offset:
    """The aligned offset, corrected by the live clock when the two disagree.

    Alignment fits the whole published window, usually ten days of H1. On the
    weekend a broker moves with daylight saving (RoboForex: GMT+3 summer,
    GMT+2 winter) most of that window still carries the old offset, so the fit
    keeps returning it for days and every fresh bar looks an hour old. The live
    clock sees the change on the first bar after the switch.
    """
    live = live_hours(latest_close, now)
    if live is None or live == aligned.hours:
        return aligned
    if aligned.hours is not None and abs(live - aligned.hours) != DST_STEP_HOURS:
        # A daylight-saving move is one hour. Any other disagreement is a stale
        # bar that happens to sit a whole number of hours behind the wall
        # clock (a holiday, a stalled terminal), not a new broker clock.
        return aligned
    if in_fx_weekend(_aware(latest_close) - timedelta(hours=live)):
        return aligned
    was = "unknown" if aligned.hours is None else f"{aligned.hours:+d}h"
    return Offset(
        hours=live,
        overlap=aligned.overlap,
        error_pips=aligned.error_pips,
        runner_up_pips=aligned.runner_up_pips,
        reason=(
            f"live clock reads {live:+d}h while the window alignment reads {was}; "
            "the live clock wins (daylight-saving change or broker move)"
        ),
    )
