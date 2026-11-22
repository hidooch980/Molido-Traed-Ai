"""Shared fixtures for V2 engines: NY-session H1 bars plus bull/bear spikes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.agents.analyzers.bars import Candle

NY = ZoneInfo("America/New_York")
H = timedelta(hours=1)


def h1(ny_open: datetime, o: float, h: float, low: float, c: float, volume: float = 100) -> Candle:
    if ny_open.tzinfo is None:
        raise ValueError("ny_open must be timezone-aware")
    return Candle(ny_open.astimezone(UTC), float(o), float(h), float(low), float(c), volume)


def ny(year, month, day, hour, minute=0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=NY)


def weekday_h1_session(day: datetime, base: float, high: float, low: float) -> list[Candle]:
    """24 H1 bars from 17:00 NY the previous calendar day to 16:00 NY this day.

    `day` is the calendar date of the 17:00 close (a weekday). The first bar
    opens at the previous 17:00. High is placed on the 10:00 bar, low on the
    03:00 bar, so the completed H/L are known and unique.
    """
    close = ny(day.year, day.month, day.day, 17)
    start = close - timedelta(hours=24)
    bars: list[Candle] = []
    mid = (high + low) / 2
    for i in range(24):
        open_t = start + i * H
        local = open_t.astimezone(NY)
        if local.hour == 10:
            o, c, hi, lo = mid, high - 0.2, high, mid - 0.5
        elif local.hour == 3:
            o, c, hi, lo = mid, low + 0.2, mid + 0.5, low
        else:
            o = base + (i % 3) * 0.1
            c = o + 0.1
            hi, lo = max(o, c) + 0.2, min(o, c) - 0.2
        bars.append(h1(open_t, o, hi, lo, c))
    return bars


def three_weekdays_oct2026() -> list[Candle]:
    """Mon 19 – Wed 21 Oct 2026 (EDT). Distinct H/L each day."""
    days = [
        (ny(2026, 10, 19, 17), 2000.0, 2010.0, 1990.0),
        (ny(2026, 10, 20, 17), 2005.0, 2020.0, 1995.0),
        (ny(2026, 10, 21, 17), 2010.0, 2030.0, 2000.0),
    ]
    out: list[Candle] = []
    for close, base, high, low in days:
        out.extend(weekday_h1_session(close, base, high, low))
    return out


def dst_spring_weekend() -> list[Candle]:
    """Bars covering Friday 6 Mar 2026 17:00 EST through Monday 9 Mar 17:00 EDT."""
    # Friday session ending 6 Mar 17:00, then Monday session ending 9 Mar 17:00.
    friday = weekday_h1_session(ny(2026, 3, 6, 17), 1.10, 1.12, 1.08)
    monday = weekday_h1_session(ny(2026, 3, 9, 17), 1.11, 1.13, 1.09)
    return friday + monday


def bull_spike_bars() -> list[Candle]:
    """Quiet range, prior high, gapped bull spike, second-leg correction, HL retest."""
    t0 = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    rows: list[tuple[float, float, float, float]] = []
    for i in range(20):
        o = 2000 + (i % 4) * 0.3
        rows.append((o, o + 1.0, o - 1.0, o + 0.2))
    # Climb to a unique swing high then a low, then the spike.
    rows.extend([
        (2002, 2012, 2001, 2011),
        (2011, 2016, 2010, 2015),
        (2015, 2022, 2014, 2020),  # prior swing high ~2022
        (2020, 2021, 2014, 2015),
        (2015, 2016, 2008, 2009),
        (2009, 2010, 2002, 2003),
        (2003, 2004, 1996, 1998),  # start of spike window
        (1998, 2008, 1997, 2007),
        (2020, 2035, 2019, 2034),  # P-Gap (open 2020 > prior high 2008) + impulse
        (2034, 2046, 2033, 2045),
    ])
    # Second leg: correction takes the previous low (2045 bar low 2033).
    rows.append((2044, 2045, 2030, 2032))
    # Retest of a higher low (touch 2033 area) after leaving it.
    rows.extend([
        (2032, 2040, 2031, 2039),
        (2039, 2042, 2033, 2041),  # trades back to 2033
    ])
    return [
        Candle(t0 + i * H, o, h, low, c, 100)
        for i, (o, h, low, c) in enumerate(rows)
    ]


def bear_spike_bars() -> list[Candle]:
    pivot = 2000.0
    bull = bull_spike_bars()
    out = []
    for b in bull:
        out.append(Candle(
            b.open_time,
            pivot - b.open, pivot - b.low, pivot - b.high, pivot - b.close, b.volume,
        ))
    return out


def fvg_then_fill() -> list[Candle]:
    """A bullish 3-candle FVG that is later mitigated, plus an open bearish FVG."""
    t0 = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    rows = [
        (2000, 2002, 1999, 2001),
        (2001, 2003, 2000, 2002),  # i-2 for the first gap
        (2002, 2004, 2001, 2003),
        (2010, 2012, 2009, 2011),  # bull FVG between 2004 and 2009
        (2011, 2013, 2010, 2012),
        (2012, 2013, 2003, 2005),  # mitigates the bull gap (low 2003 <= 2004)
        (2005, 2006, 2000, 2001),
        (2001, 2002, 1999, 2000),
        (1990, 1991, 1988, 1989),  # bear FVG between 1999 and 1991, left open
    ]
    return [Candle(t0 + i * H, o, h, low, c, 100) for i, (o, h, low, c) in enumerate(rows)]
