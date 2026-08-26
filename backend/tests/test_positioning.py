"""Institutional positioning, and the three days nobody can see it.

The Commitments of Traders report describes a Tuesday and is published the
Friday after. Almost every property tested here follows from that gap. A reader
that keys on the date the report *describes* is using numbers that were secret
at the time, and the resulting backtest is not merely optimistic - it is
unrepeatable, because the information it traded on did not exist. So the tests
that matter most are the ones that ask what was public at a given moment rather
than what had happened by then.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from app.core.errors import InsufficientDataError, ProviderError
from app.services import positioning


def report(
    day: str,
    *,
    long: int = 100_000,
    short: int = 60_000,
    oi: int = 400_000,
    traders_long: int = 70,
    traders_short: int = 50,
) -> dict[str, object]:
    return {
        "report_date_as_yyyy_mm_dd": f"{day}T00:00:00.000",
        "noncomm_positions_long_all": str(long),
        "noncomm_positions_short_all": str(short),
        "open_interest_all": str(oi),
        "traders_noncomm_long_all": str(traders_long),
        "traders_noncomm_short_all": str(traders_short),
    }


class FakeOpener:
    def __init__(self, rows: list[dict[str, object]]):
        self.rows = rows

    def __call__(self, request, timeout=None):  # noqa: ANN001 - urllib's shape
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self) -> bytes:
        return json.dumps(self.rows).encode("utf-8")


class TestPublicationLag:
    """The gap between when a position is held and when anybody may know."""

    def test_a_tuesday_report_becomes_public_on_the_friday(self):
        assert positioning.published_at(date(2026, 8, 18)).date() == date(2026, 8, 21)

    def test_it_lands_at_half_past_three_in_new_york_in_summer(self):
        """August is daylight time, so 15:30 local is 19:30 UTC."""
        moment = positioning.published_at(date(2026, 8, 18))
        assert moment == datetime(2026, 8, 21, 19, 30, tzinfo=UTC)

    def test_it_lands_at_half_past_three_in_new_york_in_winter(self):
        """January is standard time, so the same wall clock is 20:30 UTC.

        This is the test that would fail if the lag were applied as a fixed
        number of hours. Half the year would be an hour early - and an hour
        early on a release is the whole of the advantage a release creates.
        """
        moment = positioning.published_at(date(2026, 1, 13))
        assert moment == datetime(2026, 1, 16, 20, 30, tzinfo=UTC)


class TestAsOf:
    @pytest.fixture
    def opener(self):
        # Newest first, as the feed returns them.
        return FakeOpener(
            [
                report("2026-08-18", long=100_000, short=60_000),
                report("2026-08-11", long=90_000, short=70_000),
                report("2026-08-04", long=80_000, short=80_000),
            ]
        )

    def test_returns_the_newest_report_that_was_already_public(self, opener):
        # The Friday evening after the 18th: its report is out.
        moment = datetime(2026, 8, 21, 20, 0, tzinfo=UTC)
        found = positioning.as_of("EUR", moment, opener=opener)
        assert found.report_date == date(2026, 8, 18)

    def test_does_not_return_a_report_that_had_not_been_published(self, opener):
        """Asked on the Tuesday itself, it answers with the week before.

        This will look wrong to anybody reading the raw feed, and that is the
        point of doing it once here rather than remembering it at every call
        site: on the 18th, the 18th's report is three days from existing.
        """
        moment = datetime(2026, 8, 18, 23, 59, tzinfo=UTC)
        found = positioning.as_of("EUR", moment, opener=opener)
        assert found.report_date == date(2026, 8, 11)

    def test_the_boundary_is_the_publication_minute_itself(self, opener):
        just_before = datetime(2026, 8, 21, 19, 29, tzinfo=UTC)
        just_after = datetime(2026, 8, 21, 19, 30, tzinfo=UTC)
        assert positioning.as_of("EUR", just_before, opener=opener).report_date == date(
            2026, 8, 11
        )
        assert positioning.as_of("EUR", just_after, opener=opener).report_date == date(
            2026, 8, 18
        )

    def test_refuses_when_nothing_had_been_published_yet(self, opener):
        moment = datetime(2020, 1, 1, tzinfo=UTC)
        with pytest.raises(InsufficientDataError):
            positioning.as_of("EUR", moment, opener=opener)

    def test_refuses_a_moment_with_no_timezone(self, opener):
        """A naive datetime has no offset, so "was this public yet" has no answer."""
        with pytest.raises(ValueError):
            positioning.as_of("EUR", datetime(2026, 8, 21, 20, 0), opener=opener)


class TestContracts:
    def test_an_unmapped_market_is_refused_rather_than_guessed(self):
        """Guessing is how one market's crowd gets reported as another's.

        Searching the feed for "GOLD" returns a Coinbase one-ounce contract
        ahead of the COMEX benchmark, and the answer looks entirely reasonable.
        """
        with pytest.raises(InsufficientDataError) as refused:
            positioning.history("DOGECOIN", opener=FakeOpener([]))
        assert "DOGECOIN" in str(refused.value.context["key"])

    def test_the_currency_contracts_are_keyed_by_currency(self):
        """Not by pair. No CME contract exists for EUR/GBP."""
        assert "EUR" in positioning.CONTRACTS
        assert "EURGBP" not in positioning.CONTRACTS

    def test_every_contract_name_is_fully_qualified(self):
        """Contract plus exchange, because the same name trades in two places.

        `CRUDE OIL, LIGHT SWEET-WTI` exists on ICE and on NYMEX with different
        books and different participants.
        """
        for key, name in positioning.CONTRACTS.items():
            assert " - " in name or "- " in name, f"{key} names no exchange"


class TestReading:
    def test_computes_net_and_its_share_of_open_interest(self):
        opener = FakeOpener([report("2026-08-18", long=100_000, short=60_000, oi=400_000)])
        found = positioning.as_of(
            "EUR", datetime(2026, 8, 22, tzinfo=UTC), opener=opener
        )
        assert found.net == 40_000
        assert found.net_share == pytest.approx(0.1)

    def test_a_net_short_crowd_reads_negative(self):
        opener = FakeOpener([report("2026-08-18", long=60_000, short=100_000)])
        found = positioning.as_of(
            "EUR", datetime(2026, 8, 22, tzinfo=UTC), opener=opener
        )
        assert found.net < 0

    def test_a_market_with_no_open_interest_refuses_to_normalise(self):
        opener = FakeOpener([report("2026-08-18", oi=0)])
        found = positioning.as_of(
            "EUR", datetime(2026, 8, 22, tzinfo=UTC), opener=opener
        )
        with pytest.raises(InsufficientDataError):
            _ = found.net_share

    def test_a_partial_row_is_dropped_rather_than_filled_in(self):
        """A long count with no short count is not an overwhelmingly long crowd."""
        broken = report("2026-08-18")
        del broken["noncomm_positions_short_all"]
        with pytest.raises(InsufficientDataError):
            positioning.history("EUR", opener=FakeOpener([broken]))

    def test_one_unreadable_row_does_not_cost_the_others(self):
        broken = report("2026-08-18")
        broken["open_interest_all"] = "not a number"
        found = positioning.history(
            "EUR", opener=FakeOpener([broken, report("2026-08-11")])
        )
        assert [p.report_date for p in found] == [date(2026, 8, 11)]

    def test_a_refused_feed_is_reported_rather_than_returned_empty(self):
        def broken(request, timeout=None):  # noqa: ANN001
            raise OSError("connection reset")

        with pytest.raises(ProviderError):
            positioning.history("EUR", opener=broken)


class TestPairTilt:
    @pytest.fixture
    def moment(self):
        return datetime(2026, 8, 22, tzinfo=UTC)

    def test_subtracts_one_leg_from_the_other(self, moment):
        # Both legs read the same fixture, so the tilt is exactly zero - which
        # is the arithmetic being checked, not a market claim.
        opener = FakeOpener([report("2026-08-18")])
        tilt = positioning.pair_tilt("EUR", "GBP", moment, opener=opener)
        assert tilt["tilt"] == 0.0
        assert tilt["dollar_leg_implicit"] is False

    def test_says_when_one_side_is_the_dollar(self, moment):
        """Every currency future is quoted against it, so it has no contract.

        Summing the others into a synthetic dollar position would count every
        currency in the list twice.
        """
        opener = FakeOpener([report("2026-08-18")])
        tilt = positioning.pair_tilt("EUR", "USD", moment, opener=opener)
        assert tilt["dollar_leg_implicit"] is True
        assert tilt["quote_leg"] is None
        assert tilt["base_leg"] is not None
