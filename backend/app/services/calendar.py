"""The week's economic releases, in UTC, from a public feed.

The last tool on the list, and the only one that needs an outside source. Every
other calculator here refuses to work without the broker's own numbers; this one
cannot, because no broker publishes when the next CPI print lands.

**The feed carries no timezone field, and the usual assumption is wrong.** The
ForexFactory site renders in the viewer's configured timezone and is widely
documented as US Eastern, so that is what most parsers assume. The public XML is
not Eastern. Derived rather than assumed, from two releases whose local
publication times are fixed and known:

    BusinessNZ Services Index   feed 10:30pm  ->  10:30am NZST next day at UTC+12
    Food Price Index m/m        feed 10:45pm  ->  10:45am NZST next day at UTC+12

Both land exactly on their published New Zealand release times when the feed is
read as UTC, and both are four hours out under Eastern. Two matches is not
proof, so `looks_shifted` re-checks the property on live data - otherwise a feed
that quietly changed its clock would make every time in the platform a confident
lie, and nothing would fail.

Nothing here decides anything. A calendar that suppressed trades around a
release would be a rule, and rules in this project clear the edge registry
first.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.errors import ProviderError

FEED = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"

#: The feed declares windows-1252 in its own XML header. Decoding it as UTF-8
#: mangles the currency symbols and dashes in event titles rather than raising,
#: so the wrong encoding appears as odd-looking text nobody reports.
ENCODING = "windows-1252"

#: Impact levels, most severe first.
IMPACTS = ("High", "Medium", "Low", "Holiday")

#: A real trading week spreads its releases across at least this many distinct
#: hours. Fewer means the clock moved under us.
MIN_DISTINCT_HOURS = 6

_EVENT = re.compile(r"<event>(.*?)</event>", re.S)
_FIELD = re.compile(r"<([a-zA-Z_]+)>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</\1>", re.S)
_CLOCK = re.compile(r"^\d{1,2}:\d{2}(am|pm)$")


def _as_utc(moment: datetime | None) -> datetime:
    """An aware UTC instant, treating a naive one as UTC rather than local.

    `astimezone(UTC)` on a naive datetime silently reads it in the machine's
    timezone. A test written at 12:00 on a UTC+3:30 box came back as 08:30 -
    the exact failure this module exists to prevent, produced by the module
    itself, and invisible on any server that happens to run UTC.
    """
    if moment is None:
        return datetime.now(UTC)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


@dataclass(frozen=True)
class Release:
    """One scheduled economic release."""

    at: datetime | None
    title: str
    currency: str
    impact: str
    forecast: str | None = None
    previous: str | None = None
    url: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            # Always UTC, always explicit. A naive timestamp would be rendered
            # in whatever zone the reader's browser guesses, and a calendar
            # wrong by hours is worse than no calendar.
            "at": self.at.isoformat() if self.at else None,
            "title": self.title,
            "currency": self.currency,
            "impact": self.impact,
            "forecast": self.forecast,
            "previous": self.previous,
            "url": self.url,
            # An all-day entry has no clock. Null rather than midnight: a bank
            # holiday placed at 00:00 sorts to the top of the day looking like
            # something to trade around.
            "all_day": self.at is None,
        }


def _parse_time(date_text: str, time_text: str) -> datetime | None:
    """`08-16-2026` plus `10:30pm` into an aware UTC timestamp.

    None for the entries with no clock - "All Day", "Tentative", bank
    holidays. Those are real entries without a time, and inventing midnight
    puts them at the top of every day's list.
    """
    try:
        day = datetime.strptime(date_text.strip(), "%m-%d-%Y")
    except ValueError:
        return None

    cleaned = time_text.strip().lower().replace(" ", "")
    if not _CLOCK.match(cleaned):
        return None

    moment = datetime.strptime(cleaned, "%I:%M%p")
    return day.replace(hour=moment.hour, minute=moment.minute, tzinfo=UTC)


def parse(body: str) -> list[Release]:
    """Turn the feed into releases, ascending, with untimed entries last."""
    releases: list[Release] = []
    for block in _EVENT.findall(body):
        fields = {k: v.strip() for k, v in _FIELD.findall(block)}
        title = fields.get("title", "").strip()
        if not title:
            continue
        releases.append(
            Release(
                at=_parse_time(fields.get("date", ""), fields.get("time", "")),
                title=title,
                currency=fields.get("country", "").strip().upper(),
                impact=fields.get("impact", "").strip() or "Low",
                # Empty becomes None. A forecast of "" in a table is
                # indistinguishable from a forecast of zero.
                forecast=fields.get("forecast") or None,
                previous=fields.get("previous") or None,
                url=fields.get("url") or None,
            )
        )

    far = datetime.max.replace(tzinfo=UTC)
    return sorted(releases, key=lambda r: (r.at is None, r.at or far))


def looks_shifted(releases: list[Release]) -> str | None:
    """Whether the feed's clock has moved out from under this parser.

    The timezone was derived from known release times rather than declared by
    the feed, so it can change without anything failing. This turns that from a
    silent four-hour lie into a stated doubt.

    The property: a week of releases across Asian, European and American
    currencies straddles the clock. If every timed event lands in a handful of
    hours, the clock moved.
    """
    timed = [r.at for r in releases if r.at is not None]
    if len(timed) < 20:
        # Too few to say anything. Silence rather than a false alarm - a
        # warning that fires on thin weeks is one nobody reads by winter.
        return None

    hours = {moment.hour for moment in timed}
    if len(hours) < MIN_DISTINCT_HOURS:
        return (
            f"every timed release this week falls within {len(hours)} distinct "
            "hours, which a real week does not. The feed's clock has probably "
            "moved and every time shown here is wrong by a constant"
        )
    return None


def fetch(*, timeout: float = 20.0, opener: Any = None) -> str:
    """The raw feed. Separate from parsing so tests never touch the network."""
    request = urllib.request.Request(  # noqa: S310 - constant https URL
        FEED, headers={"User-Agent": "molido/1.0 (economic calendar)"}
    )
    try:
        open_url = opener or urllib.request.urlopen
        with open_url(request, timeout=timeout) as response:
            return str(response.read().decode(ENCODING, "replace"))
    except urllib.error.HTTPError as problem:
        raise ProviderError(
            f"the economic calendar feed answered {problem.code}",
            status=problem.code,
        ) from problem
    except OSError as problem:
        raise ProviderError(
            f"the economic calendar feed could not be read: {problem}"
        ) from problem


def week(
    *,
    now: datetime | None = None,
    opener: Any = None,
    currencies: set[str] | None = None,
    min_impact: str | None = None,
) -> dict[str, Any]:
    """This week's releases, filtered, with the next one called out."""
    moment = _as_utc(now)
    releases = parse(fetch(opener=opener))

    # Checked before filtering. A currency filter can thin a week to a few
    # hours legitimately, and running the check afterwards would cry wolf.
    shifted = looks_shifted(releases)

    if currencies:
        wanted = {c.upper() for c in currencies}
        releases = [r for r in releases if r.currency in wanted]
    if min_impact and min_impact in IMPACTS:
        allowed = set(IMPACTS[: IMPACTS.index(min_impact) + 1])
        releases = [r for r in releases if r.impact in allowed]

    upcoming = [r for r in releases if r.at is not None and r.at >= moment]
    following = upcoming[0] if upcoming else None

    return {
        "as_of": moment.isoformat(),
        "timezone": "UTC",
        "count": len(releases),
        "releases": [r.as_dict() for r in releases],
        "next": following.as_dict() if following else None,
        "hours_to_next": (
            round((following.at - moment).total_seconds() / 3600, 1)
            if following and following.at
            else None
        ),
        # Published, not logged. A feed whose clock moved would otherwise show
        # every time wrong by a constant and look entirely normal doing it.
        "clock_warning": shifted,
        "note": (
            "times are UTC, derived from known release times rather than "
            "declared by the feed - it carries no timezone field, and the "
            "common assumption that it is US Eastern is wrong. This is a "
            "calendar and nothing more: it gates, sizes and suppresses "
            "nothing, because that would be a rule and rules here clear the "
            "edge registry first"
        ),
    }


#: Offsets that matter to an FX trader, in hours from UTC.
#:
#: Deliberately a default rather than a fact. Daylight saving moves several of
#: these twice a year, and a table that silently stops being right is worse
#: than one the caller is expected to supply.
DEFAULT_OFFSETS: dict[str, float] = {
    "UTC": 0.0,
    "London": 1.0,
    "Frankfurt": 2.0,
    "New York": -4.0,
    "Chicago": -5.0,
    "Tokyo": 9.0,
    "Sydney": 10.0,
    "Wellington": 12.0,
    "Tehran": 3.5,
}


def convert(
    moment: datetime | None = None,
    *,
    offsets: dict[str, float] | None = None,
    broker_offset: float | None = None,
) -> dict[str, Any]:
    """One instant, shown where a trader actually needs it.

    Fixed offsets rather than named zones: the question being answered is "what
    time is it at that session", and a session boundary is a property of the
    market rather than of a political timezone.

    The broker's own server offset is included only when supplied. It is the
    one that decides which day a trade is booked to and which bar it lands in,
    and it is the one thing here that must never be guessed - this deployment's
    terminal runs GMT+0, and another broker's will not.
    """
    places = dict(offsets or DEFAULT_OFFSETS)
    if broker_offset is not None:
        places["Broker server"] = broker_offset

    aware = _as_utc(moment)
    return {
        "utc": aware.isoformat(),
        "places": [
            {
                "name": name,
                "offset": offset,
                "local": (aware + timedelta(hours=offset)).strftime("%Y-%m-%d %H:%M"),
            }
            for name, offset in sorted(places.items(), key=lambda kv: kv[1])
        ],
        "broker_offset_known": broker_offset is not None,
        "note": (
            "fixed offsets, not named timezones. Daylight saving moves several "
            "of these twice a year, so they describe the period being looked "
            "at rather than being inferred. The broker's server offset is "
            "shown only when the terminal reported one"
        ),
    }
