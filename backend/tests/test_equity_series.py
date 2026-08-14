"""The equity series, and the two different peaks that get confused.

FTMO's floor trails "the highest account balance achieved at 00:00 CE(S)T of
any preceding trading day". That is not the highest equity ever seen, and it is
not the highest balance ever seen either. A balance that peaked at noon and
fell back before midnight never raised the floor, and reading the wrong one
moves the floor by however far equity ran intraday - on a good day, the whole
of that day's profit.

So the two are separate functions with separate tests, and most of this file is
about them staying different.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services import equity

ACCOUNT = "68345601"

#: 22:00 UTC is 00:00 CE(S)T at the +2 offset the service uses, so these are
#: day boundaries as the provider counts them, not as UTC does.
def boundary(day: int, minutes_after: int = 0) -> datetime:
    return datetime(2026, 8, day, 22, 0, tzinfo=UTC) + timedelta(minutes=minutes_after)


def midday(day: int) -> datetime:
    return datetime(2026, 8, day, 10, 0, tzinfo=UTC)


class TestRecording:
    def test_a_sample_is_stored(self, session):
        assert equity.record(
            session, account_key=ACCOUNT, equity=10000.0, balance=10000.0, at=midday(1)
        )

    def test_the_same_instant_twice_is_stored_once(self, session):
        """The bridge republishes the same snapshot whenever the writer runs
        faster than the terminal. A duplicated peak is harmless; a duplicated
        count makes a quiet hour look busy."""
        first = equity.record(
            session, account_key=ACCOUNT, equity=10000.0, balance=10000.0, at=midday(1)
        )
        second = equity.record(
            session, account_key=ACCOUNT, equity=10000.0, balance=10000.0, at=midday(1)
        )

        assert first is True
        assert second is False
        assert equity.series(session, ACCOUNT).samples == 1

    def test_two_accounts_do_not_share_a_series(self, session):
        equity.record(
            session, account_key=ACCOUNT, equity=10000.0, balance=10000.0, at=midday(1)
        )
        equity.record(
            session, account_key="other", equity=99999.0, balance=99999.0, at=midday(1)
        )

        assert equity.peak_equity(session, ACCOUNT) == 10000.0


class TestNothingRecordedMeansNone:
    def test_peak_equity_is_none(self, session):
        """None means nobody was watching. Not "the peak is today's equity" -
        that places a floor at today's level and reports rope the account does
        not have."""
        assert equity.peak_equity(session, ACCOUNT) is None

    def test_the_day_open_peak_is_none(self, session):
        assert equity.peak_day_open_balance(session, ACCOUNT) is None

    def test_the_series_says_so_rather_than_showing_zero(self, session):
        described = equity.series(session, ACCOUNT)

        assert described.measured is False
        assert described.peak_equity is None
        assert "no trailing floor can be placed" in described.as_dict()["note"]


class TestPeakEquity:
    def test_it_is_the_highest_ever_seen(self, session):
        for day, value in ((1, 10000.0), (2, 10800.0), (3, 10200.0)):
            equity.record(
                session,
                account_key=ACCOUNT,
                equity=value,
                balance=value,
                at=midday(day),
            )

        assert equity.peak_equity(session, ACCOUNT) == 10800.0

    def test_it_includes_intraday_highs(self, session):
        """Equity is watched continuously, so a spike counts - which is exactly
        why it is the wrong number for FTMO's floor."""
        equity.record(
            session, account_key=ACCOUNT, equity=10000.0, balance=10000.0, at=boundary(1)
        )
        equity.record(
            session, account_key=ACCOUNT, equity=11500.0, balance=10000.0, at=midday(2)
        )

        assert equity.peak_equity(session, ACCOUNT) == 11500.0


class TestTheDayOpenPeakIsNotTheHighestBalance:
    def test_a_balance_that_fell_back_before_midnight_never_raised_the_floor(
        self, session
    ):
        """The number FTMO trails is the balance *at the boundary*. A balance
        that touched 11,000 at noon and closed the day at 10,000 never moved
        the floor, and treating it as though it had reports less rope than the
        account really has."""
        equity.record(
            session, account_key=ACCOUNT, equity=10000.0, balance=10000.0, at=boundary(1)
        )
        equity.record(
            session, account_key=ACCOUNT, equity=11000.0, balance=11000.0, at=midday(2)
        )
        equity.record(
            session, account_key=ACCOUNT, equity=10000.0, balance=10000.0, at=boundary(2)
        )

        peak = equity.peak_day_open_balance(session, ACCOUNT, before=boundary(5))

        assert peak == 10000.0

    def test_a_balance_held_over_the_boundary_does_raise_it(self, session):
        equity.record(
            session, account_key=ACCOUNT, equity=10000.0, balance=10000.0, at=boundary(1)
        )
        equity.record(
            session, account_key=ACCOUNT, equity=10900.0, balance=10900.0, at=boundary(2)
        )

        peak = equity.peak_day_open_balance(session, ACCOUNT, before=boundary(5))

        assert peak == 10900.0

    def test_the_two_peaks_differ_by_the_intraday_run(self, session):
        """Stated as a test because it is the whole reason there are two
        functions. If these ever agree by construction, one of them has been
        quietly rewritten into the other."""
        equity.record(
            session, account_key=ACCOUNT, equity=10000.0, balance=10000.0, at=boundary(1)
        )
        equity.record(
            session, account_key=ACCOUNT, equity=12000.0, balance=12000.0, at=midday(2)
        )
        equity.record(
            session, account_key=ACCOUNT, equity=10100.0, balance=10100.0, at=boundary(2)
        )

        assert equity.peak_equity(session, ACCOUNT) == 12000.0
        assert equity.peak_day_open_balance(session, ACCOUNT, before=boundary(5)) == 10100.0

    def test_today_is_excluded(self, session):
        """The rule says "any preceding trading day". Including today would let
        a floor rise on the same session it is being checked against."""
        equity.record(
            session, account_key=ACCOUNT, equity=10000.0, balance=10000.0, at=boundary(1)
        )
        equity.record(
            session, account_key=ACCOUNT, equity=11000.0, balance=11000.0, at=boundary(2)
        )

        peak = equity.peak_day_open_balance(session, ACCOUNT, before=boundary(2))

        assert peak == 10000.0, "the current day raised its own floor"

    def test_a_sample_shortly_after_the_boundary_still_counts(self, session):
        """The bridge publishes on its own clock; nothing lands on 00:00:00
        exactly, and requiring that would mean no day ever has an open."""
        equity.record(
            session,
            account_key=ACCOUNT,
            equity=10500.0,
            balance=10500.0,
            at=boundary(1, minutes_after=3),
        )

        assert equity.peak_day_open_balance(session, ACCOUNT, before=boundary(5)) == 10500.0


class TestTheSeriesReportsItsOwnSpan:
    def test_it_reports_what_it_covers(self, session):
        equity.record(
            session, account_key=ACCOUNT, equity=10000.0, balance=10000.0, at=midday(1)
        )
        equity.record(
            session, account_key=ACCOUNT, equity=10500.0, balance=10500.0, at=midday(3)
        )

        described = equity.series(session, ACCOUNT)

        assert described.samples == 2
        assert described.first_at == midday(1)
        assert described.last_at == midday(3)

    def test_the_payload_names_both_peaks(self, session):
        """A caller reading one number where the provider means the other is
        the failure this whole module exists to prevent, so both travel."""
        equity.record(
            session, account_key=ACCOUNT, equity=10000.0, balance=10000.0, at=boundary(1)
        )

        payload = equity.series(session, ACCOUNT).as_dict()

        assert "peak_equity" in payload
        assert "peak_day_open_balance" in payload
