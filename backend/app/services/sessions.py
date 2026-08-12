"""Trading sessions and market calendar (spec phase 6).

Milestone 1 detected missing candles with a weekday heuristic: a gap that
touched a Saturday was assumed legitimate. That is wrong in both directions —
it excuses a real Friday outage and it flags every Christmas as data loss. This
module replaces the guess with an actual calendar.

Three ideas, kept separate on purpose:

* **Trading hours** — the weekly schedule, expressed in the instrument's own
  local time. FX runs one continuous week (Sunday 17:00 New York to Friday
  17:00); crypto never closes; equities keep exchange hours.
* **Holidays** — dated exceptions loaded from `market_holidays`, supporting full
  closures, early closes and late opens.
* **Sessions** — Sydney/Tokyo/London/New York, defined in each centre's own
  local time so they follow their own DST rules instead of drifting apart twice
  a year.

All boundaries are resolved through `zoneinfo`. Doing this arithmetic in UTC
with fixed offsets is the classic way to get a one-hour error for a few weeks
each spring, which in bar-alignment terms silently shifts a whole session.
"""

from __future__ import annotations

import uuid
from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import AssetClass, HolidayKind, Timeframe, TradingSession
from app.core.errors import ValidationFailedError
from app.models.calendar import MarketHoliday
from app.models.instruments import Instrument

# --------------------------------------------------------------- session map
# (timezone, local open, local close). Windows are the commonly used liquidity
# definitions, not exchange opening times - FX has no exchange.
_SESSION_WINDOWS: dict[TradingSession, tuple[str, time, time]] = {
    TradingSession.SYDNEY: ("Australia/Sydney", time(7, 0), time(16, 0)),
    TradingSession.TOKYO: ("Asia/Tokyo", time(9, 0), time(18, 0)),
    TradingSession.LONDON: ("Europe/London", time(8, 0), time(17, 0)),
    TradingSession.NEW_YORK: ("America/New_York", time(8, 0), time(17, 0)),
}


@lru_cache(maxsize=32)
def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception as exc:  # noqa: BLE001 - bad config, not a data problem
        raise ValidationFailedError(f"Unknown timezone {name!r}", timezone=name) from exc


def active_sessions(moment: datetime) -> list[TradingSession]:
    """Which liquidity sessions are open at `moment` (UTC).

    Returns a list because sessions overlap - the London/New York overlap is
    the highest-liquidity window of the day and collapsing it to a single
    label would throw away the most informative fact about it.
    """
    if moment.tzinfo is None:
        raise ValidationFailedError("moment must be timezone-aware (UTC)")
    moment = moment.astimezone(UTC)

    open_now: list[TradingSession] = []
    for session, (tz_name, opens, closes) in _SESSION_WINDOWS.items():
        local = moment.astimezone(_zone(tz_name))
        if local.weekday() >= 5:  # sessions are weekday-defined
            continue
        if opens <= local.time() < closes:
            open_now.append(session)
    return open_now or [TradingSession.OFF]


# ---------------------------------------------------------- weekly schedules
@dataclass(frozen=True)
class TradingWindow:
    """One weekly window in local time. `day` is 0=Monday .. 6=Sunday.

    `close` may be "24:00", meaning the window runs to midnight and continues
    into the next day's window - that is how the FX week is expressed without
    inventing a 25-hour day.
    """

    day: int
    open: time
    close: time
    closes_next_day: bool = False

    @staticmethod
    def parse(raw: dict) -> TradingWindow:
        close_raw = str(raw["close"])
        closes_next_day = close_raw in ("24:00", "24:00:00")
        return TradingWindow(
            day=int(raw["day"]),
            open=_parse_time(str(raw["open"])),
            close=time(0, 0) if closes_next_day else _parse_time(close_raw),
            closes_next_day=closes_next_day,
        )


def _parse_time(raw: str) -> time:
    parts = [int(p) for p in raw.split(":")]
    while len(parts) < 3:
        parts.append(0)
    return time(parts[0], parts[1], parts[2])


# FX trades continuously from Sunday 17:00 New York to Friday 17:00 New York.
# Expressed in America/New_York so the boundary tracks US DST, which is what
# brokers actually follow.
FX_HOURS: list[dict] = [
    {"day": 6, "open": "17:00", "close": "24:00"},  # Sunday evening open
    {"day": 0, "open": "00:00", "close": "24:00"},
    {"day": 1, "open": "00:00", "close": "24:00"},
    {"day": 2, "open": "00:00", "close": "24:00"},
    {"day": 3, "open": "00:00", "close": "24:00"},
    {"day": 4, "open": "00:00", "close": "17:00"},  # Friday close
]
FX_TIMEZONE = "America/New_York"

CRYPTO_HOURS: list[dict] = [
    {"day": d, "open": "00:00", "close": "24:00"} for d in range(7)
]

EQUITY_HOURS: list[dict] = [
    {"day": d, "open": "09:30", "close": "16:00"} for d in range(5)
]


def default_hours(asset_class: AssetClass) -> tuple[list[dict], str]:
    """Fallback schedule + timezone for an instrument with none configured."""
    if asset_class == AssetClass.CRYPTO:
        return CRYPTO_HOURS, "Etc/UTC"
    if asset_class in (AssetClass.STOCK, AssetClass.INDEX):
        return EQUITY_HOURS, "America/New_York"
    return FX_HOURS, FX_TIMEZONE


def default_market_code(asset_class: AssetClass) -> str:
    if asset_class == AssetClass.CRYPTO:
        return "CRYPTO"
    if asset_class in (AssetClass.STOCK, AssetClass.INDEX):
        return "XNYS"
    return "FX"


# ------------------------------------------------------------- the calendar
@dataclass
class Holiday:
    holiday_date: date
    kind: HolidayKind
    name: str = ""
    opens_at: time | None = None
    closes_at: time | None = None


@dataclass
class SessionCalendar:
    """Resolves whether a market is open at a given instant.

    Built per instrument. Holidays are loaded once and held in a dict, because
    gap detection over a multi-year history asks this question millions of
    times and a query per bar would dominate the run.
    """

    timezone: str
    windows: list[TradingWindow]
    holidays: dict[date, Holiday] = field(default_factory=dict)

    @property
    def zone(self) -> ZoneInfo:
        return _zone(self.timezone)

    @property
    def is_always_open(self) -> bool:
        return len(self.windows) == 7 and all(
            w.open == time(0, 0) and w.closes_next_day for w in self.windows
        )

    # ------------------------------------------------------------------ query
    def is_open(self, moment: datetime) -> bool:
        """True when the market trades at `moment` (any timezone-aware instant)."""
        if moment.tzinfo is None:
            raise ValidationFailedError("moment must be timezone-aware")
        local = moment.astimezone(self.zone)
        local_date = local.date()

        holiday = self.holidays.get(local_date)
        if holiday is not None and holiday.kind == HolidayKind.CLOSED:
            return False

        if not self._in_weekly_window(local):
            return False

        if holiday is not None:
            # Early close / late open narrow an otherwise normal day.
            if holiday.closes_at is not None and local.time() >= holiday.closes_at:
                return False
            if holiday.opens_at is not None and local.time() < holiday.opens_at:
                return False
        return True

    def _in_weekly_window(self, local: datetime) -> bool:
        weekday = local.weekday()
        clock = local.time()
        for window in self.windows:
            if window.day != weekday:
                continue
            if window.closes_next_day:
                if clock >= window.open:
                    return True
            elif window.open <= clock < window.close:
                return True
        return False

    def expected_bar_times(
        self, start: datetime, end: datetime, timeframe: Timeframe
    ) -> list[datetime]:
        """Every bar open-time the market should have produced in [start, end).

        This is what makes honest gap detection possible: the difference
        between this list and the bars actually stored is the real loss, with
        weekends and holidays already removed rather than guessed at.
        """
        if timeframe.is_calendar_based:
            raise ValidationFailedError(
                "Weekly and monthly bars have no fixed grid; use a calendar rollup instead.",
                timeframe=timeframe.value,
            )
        start, end = _require_utc(start), _require_utc(end)
        step = timeframe.delta

        # Align the cursor down to the timeframe grid so slots line up with the
        # provider's own bar boundaries.
        epoch_seconds = int(start.timestamp())
        step_seconds = int(step.total_seconds())
        aligned = epoch_seconds - (epoch_seconds % step_seconds)
        cursor = datetime.fromtimestamp(aligned, tz=UTC)
        if cursor < start:
            cursor += step

        out: list[datetime] = []
        while cursor < end:
            if self.is_open(cursor):
                out.append(cursor)
            cursor += step
        return out

    def expected_bar_count(
        self, start: datetime, end: datetime, timeframe: Timeframe
    ) -> int:
        return len(self.expected_bar_times(start, end, timeframe))

    def missing_runs(
        self, observed: set[datetime], start: datetime, end: datetime, timeframe: Timeframe
    ) -> list[tuple[datetime, datetime, int]]:
        """Contiguous runs of expected-but-absent bars: (from, to, count)."""
        expected = self.expected_bar_times(start, end, timeframe)
        runs: list[tuple[datetime, datetime, int]] = []
        run_start: datetime | None = None
        previous: datetime | None = None

        for slot in expected:
            if slot in observed:
                if run_start is not None and previous is not None:
                    runs.append((run_start, previous, _count(expected, run_start, previous)))
                    run_start = None
            else:
                if run_start is None:
                    run_start = slot
                previous = slot
        if run_start is not None and previous is not None:
            runs.append((run_start, previous, _count(expected, run_start, previous)))
        return runs

    def next_open(self, moment: datetime, *, horizon_days: int = 14) -> datetime | None:
        """First minute at or after `moment` when the market is open."""
        cursor = _require_utc(moment).replace(second=0, microsecond=0)
        limit = cursor + timedelta(days=horizon_days)
        while cursor < limit:
            if self.is_open(cursor):
                return cursor
            cursor += timedelta(minutes=15)
        return None

    def next_close(self, moment: datetime, *, horizon_days: int = 14) -> datetime | None:
        """When the current or next trading session ends.

        If the market is already shut, this skips forward to the next open
        first. Returning "now" for an already-closed market would be literally
        true and operationally useless — the question a caller is asking is
        "how long do I have to trade", not "is it shut".
        """
        cursor = _require_utc(moment).replace(second=0, microsecond=0)
        if self.is_always_open and not self.holidays:
            return None  # genuinely never closes; say so rather than inventing a time

        if not self.is_open(cursor):
            opens = self.next_open(cursor, horizon_days=horizon_days)
            if opens is None:
                return None
            cursor = opens

        limit = cursor + timedelta(days=horizon_days)
        while cursor < limit:
            if not self.is_open(cursor):
                return cursor
            cursor += timedelta(minutes=15)
        return None


def _count(expected: list[datetime], first: datetime, last: datetime) -> int:
    lo = bisect_left(expected, first)
    hi = bisect_left(expected, last)
    return hi - lo + 1


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValidationFailedError("timestamp must be timezone-aware (UTC)")
    return value.astimezone(UTC)


# ------------------------------------------------------------- construction
def build_calendar(
    session: Session | None,
    instrument: Instrument,
    *,
    start: date | None = None,
    end: date | None = None,
) -> SessionCalendar:
    """Assemble the calendar for one instrument.

    Falls back to the asset-class default schedule when the instrument has no
    configured hours — an unconfigured instrument gets a sensible calendar
    rather than being treated as permanently closed.
    """
    raw_hours = list(instrument.trading_hours or [])
    timezone = instrument.timezone

    if not raw_hours:
        raw_hours, default_tz = default_hours(AssetClass(instrument.asset_class))
        # Only adopt the default timezone when the instrument still carries the
        # placeholder; an operator-set zone always wins.
        if timezone in ("", "Etc/UTC", "UTC"):
            timezone = default_tz

    windows = [TradingWindow.parse(entry) for entry in raw_hours]
    holidays = (
        load_holidays(session, instrument, start=start, end=end) if session is not None else {}
    )
    return SessionCalendar(timezone=timezone, windows=windows, holidays=holidays)


def load_holidays(
    session: Session,
    instrument: Instrument,
    *,
    start: date | None = None,
    end: date | None = None,
) -> dict[date, Holiday]:
    """Market-wide plus instrument-specific closures, the latter winning."""
    query = select(MarketHoliday).where(
        (MarketHoliday.market_code == instrument.market_code)
        | (MarketHoliday.instrument_id == instrument.id)
    )
    if start is not None:
        query = query.where(MarketHoliday.holiday_date >= start)
    if end is not None:
        query = query.where(MarketHoliday.holiday_date <= end)

    resolved: dict[date, Holiday] = {}
    for row in session.scalars(query):
        entry = Holiday(
            holiday_date=row.holiday_date,
            kind=HolidayKind(row.kind),
            name=row.name,
            opens_at=row.opens_at,
            closes_at=row.closes_at,
        )
        existing = resolved.get(row.holiday_date)
        # Instrument-specific rows override the market-wide entry.
        if existing is None or row.instrument_id is not None:
            resolved[row.holiday_date] = entry
    return resolved


def upsert_holiday(
    session: Session,
    market_code: str,
    holiday_date: date,
    *,
    name: str = "",
    kind: HolidayKind = HolidayKind.CLOSED,
    instrument_id: uuid.UUID | None = None,
    opens_at: time | None = None,
    closes_at: time | None = None,
    source: str | None = None,
) -> MarketHoliday:
    existing = session.scalar(
        select(MarketHoliday).where(
            MarketHoliday.market_code == market_code,
            MarketHoliday.instrument_id == instrument_id,
            MarketHoliday.holiday_date == holiday_date,
        )
    )
    if existing is None:
        existing = MarketHoliday(
            market_code=market_code,
            instrument_id=instrument_id,
            holiday_date=holiday_date,
        )
        session.add(existing)

    existing.kind = kind
    existing.name = name or existing.name
    existing.opens_at = opens_at
    existing.closes_at = closes_at
    if source:
        existing.source = source
    session.flush()
    return existing
