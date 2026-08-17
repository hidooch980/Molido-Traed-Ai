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
from datetime import UTC, timedelta
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
    session: Session, *, symbol: str = REFERENCE_SYMBOL, timeframe: str = "H1"
) -> dict[Any, float]:
    """The public feed's closes for the reference instrument."""
    instrument = session.scalar(select(Instrument).where(Instrument.symbol == symbol))
    provider = session.scalar(select(Provider.id).where(Provider.code == "yfinance"))
    if instrument is None or provider is None:
        return {}
    rows = session.execute(
        select(Bar.event_time, Bar.close).where(
            Bar.instrument_id == instrument.id,
            Bar.timeframe == timeframe,
            Bar.provider_id == provider,
        )
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
        )
    ).all()

    return align(
        public_closes(session, symbol=symbol, timeframe=timeframe),
        {when: float(close) for when, close in rows},
    )
