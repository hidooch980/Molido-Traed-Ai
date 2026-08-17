"""The one tool that needs an outside source, and the timezone it lies about.

Every other calculator in this project refuses to work without the broker's own
numbers. This one cannot - no broker publishes when the next CPI lands - so the
tests are about the two ways a calendar becomes actively harmful: times that are
wrong by a constant, and entries that invent a clock they never had.

The fixture below is real bytes from the live feed.
"""

from __future__ import annotations

import io
import urllib.error
from datetime import UTC, datetime

import pytest

from app.core.errors import ProviderError
from app.services import calendar

#: Real shape, captured from the live feed. Two of these are the releases the
#: timezone was derived from, so they are load-bearing rather than decorative.
FEED = """<?xml version="1.0" encoding="windows-1252"?>
<weeklyevents>
 <event>
  <title>BusinessNZ Services Index</title>
  <country>NZD</country>
  <date><![CDATA[08-16-2026]]></date>
  <time><![CDATA[10:30pm]]></time>
  <impact><![CDATA[Low]]></impact>
  <forecast><![CDATA[]]></forecast>
  <previous><![CDATA[50.6]]></previous>
  <url><![CDATA[https://www.forexfactory.com/calendar/852]]></url>
 </event>
 <event>
  <title>FPI m/m</title>
  <country>NZD</country>
  <date><![CDATA[08-16-2026]]></date>
  <time><![CDATA[10:45pm]]></time>
  <impact><![CDATA[Low]]></impact>
  <previous><![CDATA[0.6%]]></previous>
 </event>
 <event>
  <title>Bank Holiday</title>
  <country>EUR</country>
  <date><![CDATA[08-17-2026]]></date>
  <time><![CDATA[All Day]]></time>
  <impact><![CDATA[Holiday]]></impact>
 </event>
 <event>
  <title>CPI y/y</title>
  <country>USD</country>
  <date><![CDATA[08-18-2026]]></date>
  <time><![CDATA[12:30pm]]></time>
  <impact><![CDATA[High]]></impact>
  <forecast><![CDATA[2.7%]]></forecast>
  <previous><![CDATA[2.9%]]></previous>
 </event>
</weeklyevents>"""


def opener_for(body: str, *, encoding: str = "windows-1252"):
    class Response:
        def read(self):
            return body.encode(encoding, "replace")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def answer(request, timeout=None):
        return Response()

    return answer


class TestTheTimezoneIsDerivedNotAssumed:
    """The feed carries no timezone field. The site renders in the viewer's
    zone and is widely documented as US Eastern, so that is what most parsers
    assume - and it is four hours wrong."""

    def test_the_new_zealand_releases_land_on_their_published_times(self):
        """The two releases the timezone was derived from. Read as UTC they
        land at 10:30 and 10:45 New Zealand time, which is when NZ publishes
        them. Read as Eastern they land in the middle of the NZ night."""
        releases = calendar.parse(FEED)
        by_title = {r.title: r for r in releases}

        psi = by_title["BusinessNZ Services Index"].at
        fpi = by_title["FPI m/m"].at

        assert psi == datetime(2026, 8, 16, 22, 30, tzinfo=UTC)
        assert fpi == datetime(2026, 8, 16, 22, 45, tzinfo=UTC)
        # NZST is UTC+12 in August.
        assert (psi.hour + 12) % 24 == 10
        assert (fpi.hour + 12) % 24 == 10

    def test_every_time_is_timezone_aware(self):
        """A naive timestamp is rendered in whatever zone the reader's browser
        guesses, which turns one wrong assumption into every reader's."""
        for release in calendar.parse(FEED):
            assert release.at is None or release.at.tzinfo is not None

    def test_the_payload_says_which_zone_it_is_in(self):
        described = calendar.week(opener=opener_for(FEED), now=datetime(2026, 8, 17, tzinfo=UTC))

        assert described["timezone"] == "UTC"
        assert "US Eastern is wrong" in described["note"]


class TestAnUntimedEntryKeepsNoClock:
    def test_an_all_day_entry_has_no_time(self):
        """Inventing midnight puts a bank holiday at the top of the day's list
        looking like something to trade around."""
        holiday = next(r for r in calendar.parse(FEED) if r.title == "Bank Holiday")

        assert holiday.at is None
        assert holiday.as_dict()["all_day"] is True

    def test_untimed_entries_sort_last_rather_than_first(self):
        titles = [r.title for r in calendar.parse(FEED)]

        assert titles[-1] == "Bank Holiday"

    def test_an_untimed_entry_is_never_the_next_release(self):
        described = calendar.week(
            opener=opener_for(FEED), now=datetime(2026, 8, 16, 23, tzinfo=UTC)
        )

        assert described["next"]["title"] == "CPI y/y"


class TestEmptyIsNotZero:
    def test_a_blank_forecast_is_none(self):
        """An empty string in a table is indistinguishable from a forecast of
        zero, and a forecast of zero is a real and different thing."""
        psi = next(
            r for r in calendar.parse(FEED) if r.title == "BusinessNZ Services Index"
        )

        assert psi.forecast is None
        assert psi.previous == "50.6"

    def test_a_present_forecast_survives(self):
        cpi = next(r for r in calendar.parse(FEED) if r.title == "CPI y/y")

        assert cpi.forecast == "2.7%"
        assert cpi.impact == "High"


class TestTheClockCheck:
    """The timezone was derived, not declared, so it can change without
    anything failing. This is what turns that into a stated doubt."""

    def test_a_thin_week_says_nothing_rather_than_crying_wolf(self):
        assert calendar.looks_shifted(calendar.parse(FEED)) is None

    def test_a_week_squeezed_into_a_few_hours_is_flagged(self):
        squashed = [
            calendar.Release(
                at=datetime(2026, 8, 17, 9, minute % 60, tzinfo=UTC),
                title=f"Event {minute}",
                currency="USD",
                impact="Low",
            )
            for minute in range(30)
        ]

        warning = calendar.looks_shifted(squashed)

        assert warning is not None
        assert "wrong by a constant" in warning

    def test_a_normal_week_is_not_flagged(self):
        spread = [
            calendar.Release(
                at=datetime(2026, 8, 17, hour % 24, 0, tzinfo=UTC),
                title=f"Event {hour}",
                currency="USD",
                impact="Low",
            )
            for hour in range(24)
        ]

        assert calendar.looks_shifted(spread) is None

    def test_the_warning_reaches_the_payload(self):
        described = calendar.week(
            opener=opener_for(FEED), now=datetime(2026, 8, 17, tzinfo=UTC)
        )

        assert "clock_warning" in described


class TestItDecidesNothing:
    def test_the_payload_says_so(self):
        """A calendar that suppressed trades around a release would be a rule,
        and rules here clear the edge registry first."""
        described = calendar.week(
            opener=opener_for(FEED), now=datetime(2026, 8, 17, tzinfo=UTC)
        )

        assert "gates, sizes and suppresses" in described["note"]


class TestFiltering:
    def test_by_currency(self):
        described = calendar.week(
            opener=opener_for(FEED),
            now=datetime(2026, 8, 16, tzinfo=UTC),
            currencies={"usd"},
        )

        assert {r["currency"] for r in described["releases"]} == {"USD"}

    def test_by_impact_includes_everything_more_severe(self):
        described = calendar.week(
            opener=opener_for(FEED),
            now=datetime(2026, 8, 16, tzinfo=UTC),
            min_impact="Medium",
        )

        assert {r["impact"] for r in described["releases"]} == {"High"}

    def test_an_unknown_impact_filters_nothing_rather_than_everything(self):
        """Silently returning an empty calendar reads as a quiet week."""
        described = calendar.week(
            opener=opener_for(FEED),
            now=datetime(2026, 8, 16, tzinfo=UTC),
            min_impact="Catastrophic",
        )

        assert described["count"] == 4


class TestTheFeedFailingIsNotAQuietWeek:
    def test_an_http_error_raises(self):
        def gone(request, timeout=None):
            raise urllib.error.HTTPError(
                calendar.FEED, 503, "no", {}, io.BytesIO(b"")
            )

        with pytest.raises(ProviderError, match="answered 503"):
            calendar.week(opener=gone)

    def test_a_network_error_raises(self):
        def drop(request, timeout=None):
            raise urllib.error.URLError("reset")

        with pytest.raises(ProviderError, match="could not be read"):
            calendar.week(opener=drop)

    def test_junk_parses_to_nothing_rather_than_guessing(self):
        assert calendar.parse("<html>not a feed</html>") == []


class TestTheTimezoneConverter:
    MOMENT = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)

    def test_it_converts_by_fixed_offset(self):
        places = {p["name"]: p["local"] for p in calendar.convert(self.MOMENT)["places"]}

        assert places["UTC"] == "2026-08-17 12:00"
        assert places["Tokyo"] == "2026-08-17 21:00"
        assert places["New York"] == "2026-08-17 08:00"

    def test_a_half_hour_offset_works(self):
        """Tehran is UTC+3:30, and an integer-only converter is wrong there by
        half an hour all year."""
        places = {p["name"]: p["local"] for p in calendar.convert(self.MOMENT)["places"]}

        assert places["Tehran"] == "2026-08-17 15:30"

    def test_places_are_ordered_west_to_east(self):
        offsets = [p["offset"] for p in calendar.convert(self.MOMENT)["places"]]

        assert offsets == sorted(offsets)

    def test_the_broker_offset_appears_only_when_it_is_known(self):
        """It decides which day a trade books to and which bar it lands in.
        This deployment's terminal runs GMT+0 and another broker's will not, so
        it is the one thing here that must never be guessed."""
        without = calendar.convert(self.MOMENT)
        with_broker = calendar.convert(self.MOMENT, broker_offset=3.0)

        assert without["broker_offset_known"] is False
        assert all(p["name"] != "Broker server" for p in without["places"])
        assert with_broker["broker_offset_known"] is True
        assert any(p["name"] == "Broker server" for p in with_broker["places"])

    def test_a_naive_moment_is_treated_as_utc_not_local(self):
        naive = datetime(2026, 8, 17, 12, 0)

        assert calendar.convert(naive)["utc"].startswith("2026-08-17T12:00")


class TestTheFeedIsNotRefetchedOnEveryLoad:
    """This is the only page component that reaches another continent on every
    load, and the answer it gets is a week old by design."""

    def test_an_injected_opener_is_never_cached(self, monkeypatch):
        """A test fixture left in the cache would be served to the next test,
        and to production if the injection ever happened there."""
        calls: list[int] = []

        def counting(request, timeout=None):
            calls.append(1)
            return opener_for(FEED)(request, timeout)

        calendar.fetch(opener=counting)
        calendar.fetch(opener=counting)

        assert len(calls) == 2

    def test_the_cache_window_is_stated(self):
        assert calendar.CACHE_SECONDS == 600

    def test_a_failed_fetch_does_not_poison_the_cache(self, monkeypatch):
        """A calendar that keeps showing last week because the feed went down
        is worse than one that says it could not be read."""
        import urllib.error

        monkeypatch.setattr(calendar, "_cached", None)

        def broken(request, timeout=None):
            raise urllib.error.URLError("down")

        with pytest.raises(ProviderError):
            calendar.fetch(opener=broken)

        assert calendar._cached is None
