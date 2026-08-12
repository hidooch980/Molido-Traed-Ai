"""Session calendar tests (phase 6).

The point of this phase is that gap detection stops guessing. These tests pin
the behaviour that makes that true: DST-correct boundaries, real holidays, and
expected-bar grids that exclude closures instead of apologising for them.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest

from app.core.enums import AssetClass, HolidayKind, Timeframe, TradingSession
from app.core.errors import ValidationFailedError
from app.models.instruments import Instrument
from app.services.sessions import (
    CRYPTO_HOURS,
    FX_HOURS,
    FX_TIMEZONE,
    SessionCalendar,
    TradingWindow,
    active_sessions,
    build_calendar,
    default_market_code,
    load_holidays,
    upsert_holiday,
)


def fx_calendar(holidays=None) -> SessionCalendar:
    return SessionCalendar(
        timezone=FX_TIMEZONE,
        windows=[TradingWindow.parse(w) for w in FX_HOURS],
        holidays=holidays or {},
    )


def crypto_calendar() -> SessionCalendar:
    return SessionCalendar(
        timezone="Etc/UTC",
        windows=[TradingWindow.parse(w) for w in CRYPTO_HOURS],
    )


# ------------------------------------------------------------ weekly schedule
class TestForexWeek:
    def test_open_midweek(self):
        # Wednesday noon UTC
        assert fx_calendar().is_open(datetime(2024, 3, 6, 12, 0, tzinfo=UTC)) is True

    def test_closed_saturday(self):
        assert fx_calendar().is_open(datetime(2024, 3, 9, 12, 0, tzinfo=UTC)) is False

    def test_closed_after_friday_new_york_close(self):
        """Friday 17:00 New York = 22:00 UTC in March (EDT)."""
        calendar = fx_calendar()

        assert calendar.is_open(datetime(2024, 3, 8, 20, 0, tzinfo=UTC)) is True
        assert calendar.is_open(datetime(2024, 3, 8, 22, 0, tzinfo=UTC)) is False

    def test_opens_sunday_evening(self):
        """Sunday 17:00 New York = 21:00 UTC in March."""
        calendar = fx_calendar()

        assert calendar.is_open(datetime(2024, 3, 10, 20, 0, tzinfo=UTC)) is False
        assert calendar.is_open(datetime(2024, 3, 10, 22, 0, tzinfo=UTC)) is True

    def test_boundary_follows_dst_not_a_fixed_offset(self):
        """The whole reason for zoneinfo: the UTC boundary moves with DST.

        US DST began on 10 March 2024. Before it New York is UTC-5, so the
        Friday close lands at 22:00 UTC; after it New York is UTC-4 and the
        same local close lands at 21:00 UTC. A hard-coded offset would be
        wrong for one of these two Fridays.
        """
        calendar = fx_calendar()

        # 5 Jan, EST: 21:00 UTC = 16:00 New York -> still open
        assert calendar.is_open(datetime(2024, 1, 5, 21, 0, tzinfo=UTC)) is True
        # 15 Mar, EDT: the same 21:00 UTC is now 17:00 New York -> closed
        assert calendar.is_open(datetime(2024, 3, 15, 21, 0, tzinfo=UTC)) is False
        # ...and an hour earlier it is still open, pinning the boundary itself
        assert calendar.is_open(datetime(2024, 3, 15, 20, 0, tzinfo=UTC)) is True


class TestCrypto:
    def test_never_closes(self):
        calendar = crypto_calendar()
        moments = [
            datetime(2024, 3, 9, 3, 0, tzinfo=UTC),  # Saturday
            datetime(2024, 3, 10, 12, 0, tzinfo=UTC),  # Sunday
            datetime(2024, 12, 25, 0, 0, tzinfo=UTC),  # Christmas
        ]

        assert all(calendar.is_open(m) for m in moments)
        assert calendar.is_always_open is True

    def test_next_close_is_null_not_invented(self):
        """A market that never closes reports null, not a far-future guess."""
        assert crypto_calendar().next_close(datetime(2024, 3, 6, 12, 0, tzinfo=UTC)) is None


# -------------------------------------------------------------------- holidays
class TestHolidays:
    def test_full_closure_shuts_an_otherwise_normal_day(self):
        christmas = date(2024, 12, 25)  # a Wednesday
        calendar = fx_calendar(
            {christmas: _holiday(christmas, HolidayKind.CLOSED, "Christmas")}
        )

        assert calendar.is_open(datetime(2024, 12, 25, 15, 0, tzinfo=UTC)) is False
        assert calendar.is_open(datetime(2024, 12, 24, 15, 0, tzinfo=UTC)) is True

    def test_early_close_narrows_the_day(self):
        eve = date(2024, 12, 24)
        calendar = fx_calendar(
            {
                eve: _holiday(
                    eve, HolidayKind.EARLY_CLOSE, "Christmas Eve", closes_at=time(13, 0)
                )
            }
        )

        # 16:00 UTC = 11:00 New York -> before the 13:00 early close
        assert calendar.is_open(datetime(2024, 12, 24, 16, 0, tzinfo=UTC)) is True
        # 20:00 UTC = 15:00 New York -> after it
        assert calendar.is_open(datetime(2024, 12, 24, 20, 0, tzinfo=UTC)) is False

    def test_late_open_delays_the_day(self):
        day = date(2024, 12, 26)
        calendar = fx_calendar(
            {day: _holiday(day, HolidayKind.LATE_OPEN, "Boxing Day", opens_at=time(12, 0))}
        )

        assert calendar.is_open(datetime(2024, 12, 26, 14, 0, tzinfo=UTC)) is False  # 09:00 NY
        assert calendar.is_open(datetime(2024, 12, 26, 18, 0, tzinfo=UTC)) is True  # 13:00 NY

    def test_instrument_specific_holiday_overrides_the_market(self, session, instrument):
        day = date(2024, 7, 4)
        upsert_holiday(session, "FX", day, name="Market-wide", kind=HolidayKind.CLOSED)
        upsert_holiday(
            session,
            "FX",
            day,
            name="Instrument-specific",
            kind=HolidayKind.EARLY_CLOSE,
            instrument_id=instrument.id,
            closes_at=time(12, 0),
        )

        holidays = load_holidays(session, instrument)

        assert holidays[day].name == "Instrument-specific"
        assert holidays[day].kind == HolidayKind.EARLY_CLOSE

    def test_upsert_is_idempotent(self, session):
        day = date(2024, 1, 1)
        first = upsert_holiday(session, "FX", day, name="New Year")
        second = upsert_holiday(session, "FX", day, name="New Year")

        assert first.id == second.id


def _holiday(day, kind, name, opens_at=None, closes_at=None):
    from app.services.sessions import Holiday

    return Holiday(
        holiday_date=day, kind=kind, name=name, opens_at=opens_at, closes_at=closes_at
    )


# ------------------------------------------------------------- expected grids
class TestExpectedBars:
    def test_weekend_is_excluded_from_expected_bars(self):
        """The core fix: a weekend produces no expected bars at all."""
        calendar = fx_calendar()
        friday = datetime(2024, 3, 8, 0, 0, tzinfo=UTC)
        monday = datetime(2024, 3, 11, 0, 0, tzinfo=UTC)

        slots = calendar.expected_bar_times(friday, monday, Timeframe.H1)

        assert all(s.weekday() != 5 for s in slots), "no Saturday bars are expected"
        # 8 March is still EST, so the 17:00 New York close is 22:00 UTC and
        # the last expected Friday bar opens at 21:00.
        assert max(s for s in slots if s.weekday() == 4).hour == 21

    def test_holiday_is_excluded_from_expected_bars(self):
        christmas = date(2024, 12, 25)
        calendar = fx_calendar(
            {christmas: _holiday(christmas, HolidayKind.CLOSED, "Christmas")}
        )

        slots = calendar.expected_bar_times(
            datetime(2024, 12, 25, 0, 0, tzinfo=UTC),
            datetime(2024, 12, 26, 0, 0, tzinfo=UTC),
            Timeframe.H1,
        )

        # 00:00-05:00 UTC on the 25th is still the 24th in New York, so those
        # hours legitimately trade; the New York calendar day itself does not.
        assert all(s.astimezone(calendar.zone).date() != christmas for s in slots)

    def test_crypto_expects_every_slot(self):
        calendar = crypto_calendar()
        start = datetime(2024, 3, 9, 0, 0, tzinfo=UTC)  # Saturday

        slots = calendar.expected_bar_times(start, start + timedelta(days=1), Timeframe.H1)

        assert len(slots) == 24

    def test_missing_runs_finds_a_real_hole(self):
        calendar = crypto_calendar()
        start = datetime(2024, 3, 6, 0, 0, tzinfo=UTC)
        end = start + timedelta(hours=24)
        observed = {start + timedelta(hours=i) for i in range(24)}
        for i in (5, 6, 7):
            observed.discard(start + timedelta(hours=i))

        runs = calendar.missing_runs(observed, start, end, Timeframe.H1)

        assert len(runs) == 1
        assert runs[0][0] == start + timedelta(hours=5)
        assert runs[0][2] == 3

    def test_complete_series_has_no_missing_runs(self):
        calendar = crypto_calendar()
        start = datetime(2024, 3, 6, 0, 0, tzinfo=UTC)
        end = start + timedelta(hours=24)
        observed = {start + timedelta(hours=i) for i in range(24)}

        assert calendar.missing_runs(observed, start, end, Timeframe.H1) == []

    def test_calendar_timeframes_are_refused_not_guessed(self):
        with pytest.raises(ValidationFailedError):
            crypto_calendar().expected_bar_times(
                datetime(2024, 3, 1, tzinfo=UTC),
                datetime(2024, 4, 1, tzinfo=UTC),
                Timeframe.MN1,
            )

    def test_naive_timestamps_are_refused(self):
        with pytest.raises(ValidationFailedError):
            crypto_calendar().is_open(datetime(2024, 3, 6, 12, 0))


# -------------------------------------------------------------- session labels
class TestSessionLabels:
    def test_london_new_york_overlap_reports_both(self):
        """The overlap is the most informative window; it must not collapse."""
        # 14:00 UTC in March = 14:00 London (GMT), 10:00 New York (EDT)
        labels = active_sessions(datetime(2024, 3, 6, 14, 0, tzinfo=UTC))

        assert TradingSession.LONDON in labels
        assert TradingSession.NEW_YORK in labels

    def test_asian_morning_excludes_the_western_centres(self):
        # 01:00 UTC = 12:00 Sydney and 10:00 Tokyo; London and New York shut.
        labels = active_sessions(datetime(2024, 3, 6, 1, 0, tzinfo=UTC))

        assert set(labels) == {TradingSession.SYDNEY, TradingSession.TOKYO}

    def test_friday_night_reports_off(self):
        """The one genuinely quiet window: after New York, into the weekend.

        On weekdays the four centres tile the clock with no gap — Sydney opens
        (20:00 UTC) before New York closes (22:00 UTC in winter), and Tokyo
        opens before Sydney shuts. So OFF only appears once the weekend has
        started somewhere: at 23:00 UTC Friday it is already Saturday in
        Sydney and Tokyo, and London and New York are long shut.
        """
        assert active_sessions(datetime(2024, 3, 8, 23, 0, tzinfo=UTC)) == [
            TradingSession.OFF
        ]

    def test_weekend_has_no_sessions(self):
        assert active_sessions(datetime(2024, 3, 9, 14, 0, tzinfo=UTC)) == [
            TradingSession.OFF
        ]


# ------------------------------------------------------------- construction
class TestBuildCalendar:
    def test_falls_back_to_asset_class_defaults(self, session, instrument):
        instrument.trading_hours = []

        calendar = build_calendar(session, instrument)

        assert calendar.timezone == FX_TIMEZONE
        assert len(calendar.windows) == len(FX_HOURS)

    def test_operator_configured_hours_win(self, session, instrument):
        instrument.trading_hours = [{"day": 0, "open": "09:00", "close": "17:00"}]
        instrument.timezone = "Europe/London"

        calendar = build_calendar(session, instrument)

        assert calendar.timezone == "Europe/London"
        assert len(calendar.windows) == 1
        assert calendar.is_open(datetime(2024, 3, 4, 10, 0, tzinfo=UTC)) is True
        assert calendar.is_open(datetime(2024, 3, 4, 18, 0, tzinfo=UTC)) is False

    def test_crypto_instrument_gets_a_crypto_calendar(self, session):
        btc = Instrument(
            symbol="BTCUSD", name="Bitcoin", asset_class=AssetClass.CRYPTO,
            market_code="CRYPTO",
        )
        session.add(btc)
        session.flush()

        calendar = build_calendar(session, btc)

        assert calendar.is_always_open is True

    def test_market_code_follows_asset_class(self):
        assert default_market_code(AssetClass.CRYPTO) == "CRYPTO"
        assert default_market_code(AssetClass.FOREX) == "FX"
        assert default_market_code(AssetClass.STOCK) == "XNYS"

    def test_next_close_skips_past_a_closed_market(self):
        """Asked on a Saturday, it reports the *next* session's close."""
        calendar = fx_calendar()
        saturday = datetime(2024, 3, 9, 14, 0, tzinfo=UTC)

        closes = calendar.next_close(saturday)

        assert closes is not None
        assert closes > calendar.next_open(saturday)
        assert closes.weekday() == 4, "the next session ends on Friday"

    def test_next_close_while_open_is_the_current_session_end(self):
        calendar = fx_calendar()
        wednesday = datetime(2024, 3, 6, 14, 0, tzinfo=UTC)

        # 8 March is EST, so the Friday 17:00 New York close is 22:00 UTC.
        assert calendar.next_close(wednesday) == datetime(2024, 3, 8, 22, 0, tzinfo=UTC)

    def test_next_open_after_the_weekend(self):
        calendar = fx_calendar()
        saturday = datetime(2024, 3, 9, 12, 0, tzinfo=UTC)

        reopen = calendar.next_open(saturday)

        assert reopen is not None
        assert reopen.weekday() == 6  # Sunday evening New York time
        assert reopen == datetime(2024, 3, 10, 21, 0, tzinfo=UTC)
