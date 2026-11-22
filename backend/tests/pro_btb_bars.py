"""Shared bull/bear (and invalid) bar fixtures for Pro BTB stage tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.agents.analyzers.bars import Candle

H = timedelta(hours=1)
T0 = datetime(2026, 11, 2, 0, 0, tzinfo=UTC)


def ohlc(rows: list[tuple[float, float, float, float]], volume: float = 100) -> list[Candle]:
    out: list[Candle] = []
    for i, (o, h, low, c) in enumerate(rows):
        if h < max(o, c) or low > min(o, c):
            raise ValueError(f"inconsistent OHLC at {i}: {(o, h, low, c)}")
        out.append(Candle(T0 + i * H, float(o), float(h), float(low), float(c), volume=volume))
    return out


def _mirror(rows: list[tuple[float, float, float, float]], pivot: float = 2000.0):
    flipped = []
    for o, h, low, c in rows:
        fo, fh, fl, fc = pivot - o, pivot - low, pivot - h, pivot - c
        flipped.append((fo, fh, fl, fc))
    return flipped


def _bull_rows() -> list[tuple[float, float, float, float]]:
    """Hand-built path: range, swing high, swing low, gapped BO, FT, pullback into BTB."""
    rows: list[tuple[float, float, float, float]] = []
    # 0-12: quiet range so ATR stays modest.
    base = [
        (2000, 2004, 1998, 2001),
        (2001, 2005, 1999, 2002),
        (2002, 2006, 2000, 2001),
        (2001, 2003, 1997, 1999),
        (1999, 2002, 1996, 1998),
        (1998, 2003, 1997, 2001),
        (2001, 2004, 1999, 2000),
        (2000, 2003, 1998, 1999),
        (1999, 2002, 1997, 2000),
        (2000, 2005, 1999, 2003),
        (2003, 2006, 2001, 2002),
        (2002, 2004, 1999, 2000),
        (2000, 2003, 1998, 2001),
    ]
    rows.extend(base)
    # 13-16: climb into a unique swing high at 16 (high=2020), confirmed by 17-18.
    rows.extend([
        (2001, 2008, 2000, 2007),
        (2007, 2012, 2006, 2011),
        (2011, 2016, 2010, 2015),
        (2015, 2020, 2014, 2018),  # 16 swing high
        (2018, 2019, 2012, 2013),
        (2013, 2015, 2008, 2009),
    ])
    # 19-22: decline into a unique swing low at 22 (low=1980), confirmed by 23-24.
    rows.extend([
        (2009, 2010, 2002, 2003),
        (2003, 2004, 1994, 1995),
        (1995, 1996, 1986, 1987),
        (1987, 1988, 1980, 1982),  # 22 swing low, start of bull leg
        (1982, 1989, 1981, 1988),
        (1988, 1996, 1987, 1995),
    ])
    # 25: last bar still below the 2020 reference, high <= 2020.
    rows.append((1995, 2010, 1994, 2008))
    # 26: BO with a gap (open 2021 > prior high 2010) and close near the high.
    rows.append((2021, 2034, 2020, 2032))
    # 27: follow-through, close beyond the BO high 2034.
    rows.append((2032, 2046, 2031, 2045))
    # 28-30: continue the impulse; swing high at 30 (high=2068), confirmed 31-32.
    rows.extend([
        (2045, 2054, 2044, 2053),
        (2053, 2061, 2052, 2060),
        (2060, 2068, 2059, 2066),  # 30
        (2066, 2067, 2060, 2061),
        (2061, 2063, 2054, 2055),
    ])
    # 33-36: pullback into the BTB zone (~2020-2034). Weak, overlapping.
    rows.extend([
        (2055, 2057, 2046, 2048),
        (2048, 2050, 2038, 2040),
        (2040, 2042, 2030, 2032),
        (2032, 2036, 2024, 2028),  # 36 intersects 2020-2034
    ])
    # 37-39: microchannel of rising lows (bull).
    rows.extend([
        (2028, 2035, 2025, 2033),
        (2033, 2038, 2027, 2036),
        (2036, 2041, 2029, 2039),
    ])
    return rows


def bull_bars() -> list[Candle]:
    return ohlc(_bull_rows())


def bear_bars() -> list[Candle]:
    return ohlc(_mirror(_bull_rows()))


def chop_bars(n: int = 30) -> list[Candle]:
    """Overlapping two-sided range: should not yield a strong leg."""
    rows = []
    for i in range(n):
        mid = 2000 + (1 if i % 2 == 0 else -1)
        o, c = mid - 0.5, mid + 0.5 if i % 2 == 0 else mid - 1.5
        rows.append((o, max(o, c) + 2, min(o, c) - 2, c))
    return ohlc(rows)


def bull_bars_no_gap() -> list[Candle]:
    rows = _bull_rows()
    # Replace the BO bar (26): open inside the prior bar, still closes beyond 2020.
    rows[26] = (2009, 2034, 2008, 2032)
    return ohlc(rows)


def bull_bars_no_ft() -> list[Candle]:
    rows = _bull_rows()
    # Replace the FT bar (27): closes back below the BO high.
    rows[27] = (2032, 2033, 2018, 2020)
    return ohlc(rows)


def bull_impulse_bars() -> list[Candle]:
    """Bull path cut after the impulse high is confirmed (no deep pullback)."""
    return bull_bars()[:33]


def bear_impulse_bars() -> list[Candle]:
    return bear_bars()[:33]
