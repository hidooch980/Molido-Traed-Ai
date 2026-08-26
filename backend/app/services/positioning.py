"""Where the large speculators actually are, from the CFTC.

Every other input in this codebase is a price or something derived from one. A
price says what was agreed; it does not say who is holding what, or how
crowded a side has become. The Commitments of Traders report does: once a week,
every reporting participant in a US futures market declares its position, and
the CFTC publishes the totals by category. "Non-commercial" is the category
that matters here - funds and speculators, as distinct from producers hedging
physical exposure - and it is the closest thing to a public record of what the
institutional money is positioned in.

**The publication lag is the whole correctness problem.** Positions are held on
Tuesday and published the following Friday afternoon. A system that reads the
Tuesday figure on Tuesday is using information that will not exist for three
more days, and it is a peculiarly convincing kind of cheating: the number is
real, the date is real, and the backtest that uses it produces a strategy that
cannot be traded. Everything here is keyed on when a report *became public*,
never on the date it describes, and `as_of` refuses any read that would cross
that line.

**Contract names are pinned, never matched.** Searching for "GOLD" returns a
Coinbase one-ounce contract before the COMEX benchmark; "NATURAL GAS" returns a
San Juan basin index; and the highest open interest under "RUSSELL 2000" is an
annual *dividend* future rather than the index itself. Each of those is a
plausible-looking answer that would attribute one market's positioning to
another - the same class of error the watchlist's docstring warns about, where
the numbers stay perfectly reasonable and the conclusion is about a different
instrument. Every name below was read off the live feed and chosen
deliberately, by what the contract is rather than by what it sorts as.

**Currency positioning is per currency, not per pair.** Every CME currency
future is quoted against the dollar, so the report knows what speculators think
of the euro, not what they think of EUR/GBP. A cross's positioning is the
difference between its two legs, and that is computed here rather than faked
with a contract that does not exist.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime, time as clock, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.core.errors import InsufficientDataError, ProviderError
from app.core.logging import get_logger

log = get_logger(__name__)

ENDPOINT = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"

#: The report describes Tuesday and is published the Friday after, at 15:30 in
#: New York. Both halves matter: the three days, and the fact that it is a wall
#: clock in a place that changes its offset twice a year.
PUBLICATION_LAG_DAYS = 3
PUBLICATION_TIME = clock(15, 30)
PUBLICATION_ZONE = ZoneInfo("America/New_York")

#: Canonical symbol -> the exact contract, as the CFTC names it.
#:
#: Currencies first, and they are keyed by currency rather than by pair for the
#: reason in the module docstring. The rest map one to one.
CONTRACTS: dict[str, str] = {
    # Currencies, all quoted against the dollar
    "EUR": "EURO FX - CHICAGO MERCANTILE EXCHANGE",
    "GBP": "BRITISH POUND - CHICAGO MERCANTILE EXCHANGE",
    "JPY": "JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE",
    "CHF": "SWISS FRANC - CHICAGO MERCANTILE EXCHANGE",
    "CAD": "CANADIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE",
    "AUD": "AUSTRALIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE",
    "NZD": "NEW ZEALAND DOLLAR - CHICAGO MERCANTILE EXCHANGE",
    # Metals. The COMEX benchmarks, not the retail-sized look-alikes.
    "XAUUSD": "GOLD - COMMODITY EXCHANGE INC.",
    "XAGUSD": "SILVER - COMMODITY EXCHANGE INC.",
    "XPTUSD": "PLATINUM - NEW YORK MERCANTILE EXCHANGE",
    "COPPER": "COPPER- #1 - COMMODITY EXCHANGE INC.",
    # Energy. `WTI-PHYSICAL` is the NYMEX benchmark; the ICE listing of the
    # same grade is a separate, smaller book and would report a different
    # crowd.
    "USOIL": "WTI-PHYSICAL - NEW YORK MERCANTILE EXCHANGE",
    "UKOIL": "BRENT LAST DAY - NEW YORK MERCANTILE EXCHANGE",
    "NGAS": "NAT GAS NYME - NEW YORK MERCANTILE EXCHANGE",
    # Equity indices. "Consolidated" rows aggregate several contract sizes;
    # the E-mini is the one whose participants are the speculative crowd.
    "US500": "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE",
    "US100": "NASDAQ MINI - CHICAGO MERCANTILE EXCHANGE",
    "US30": "DJIA Consolidated - CHICAGO BOARD OF TRADE",
    "US2000": "MICRO E-MINI RUSSELL 2000 INDX - CHICAGO MERCANTILE EXCHANGE",
    # Crypto, on the regulated venue. The Coinbase "nano perp style" listings
    # carry more open interest and are a different market with a different
    # participant mix.
    "BTCUSD": "BITCOIN - CHICAGO MERCANTILE EXCHANGE",
    "ETHUSD": "MICRO ETHER - CHICAGO MERCANTILE EXCHANGE",
}

#: The report changes once a week. An hour of staleness cannot straddle a
#: publication, and re-fetching per request would hammer a public endpoint for
#: a number that moves on Fridays.
CACHE_SECONDS = 3600

_cached: dict[str, tuple[float, list[dict[str, Any]]]] = {}


@dataclass(frozen=True)
class Positioning:
    """One market's speculative positioning, as of one weekly report."""

    key: str
    contract: str
    #: The Tuesday the positions were held.
    report_date: date
    #: The moment it became public. Everything downstream keys on this.
    published_at: datetime
    long: int
    short: int
    open_interest: int
    traders_long: int
    traders_short: int

    @property
    def net(self) -> int:
        """Contracts long minus contracts short. Positive is a bullish crowd."""
        return self.long - self.short

    @property
    def net_share(self) -> float:
        """Net position as a share of open interest, in [-1, 1].

        Normalised because the raw count is not comparable across markets -
        two hundred thousand net long euro and two hundred thousand net long
        platinum describe completely different degrees of crowding.
        """
        if self.open_interest <= 0:
            raise InsufficientDataError(
                f"{self.key} reports no open interest, so its net position "
                "cannot be expressed as a share of one.",
                key=self.key,
                report_date=self.report_date.isoformat(),
            )
        return round(self.net / self.open_interest, 6)

    @property
    def traders(self) -> int:
        return self.traders_long + self.traders_short

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "contract": self.contract,
            "report_date": self.report_date.isoformat(),
            "published_at": self.published_at.isoformat(),
            "long": self.long,
            "short": self.short,
            "net": self.net,
            "open_interest": self.open_interest,
            "traders_long": self.traders_long,
            "traders_short": self.traders_short,
        }


def published_at(report_date: date) -> datetime:
    """When a report describing `report_date` became public, in UTC.

    Computed rather than read, because the feed does not carry it. The lag is
    fixed by the CFTC's own schedule, and the conversion goes through New York
    local time so that a report in March and a report in July - which sit on
    different UTC offsets - both land at half past three in the afternoon where
    it was actually published.
    """
    local = datetime.combine(
        report_date + timedelta(days=PUBLICATION_LAG_DAYS),
        PUBLICATION_TIME,
        tzinfo=PUBLICATION_ZONE,
    )
    return local.astimezone(UTC)


def _rows(contract: str, *, limit: int, timeout: float, opener: Any) -> list[dict[str, Any]]:
    """Recent reports for one contract, newest first."""
    cache_key = f"{contract}:{limit}"
    if opener is None:
        hit = _cached.get(cache_key)
        if hit is not None and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]

    query = urllib.parse.urlencode(
        {
            # Equality, not `like`. A pattern is what picks up the Coinbase
            # gold contract instead of the COMEX one.
            "$where": f"market_and_exchange_names = '{contract}'",
            "$order": "report_date_as_yyyy_mm_dd DESC",
            "$limit": str(limit),
        }
    )
    request = urllib.request.Request(  # noqa: S310 - constant https host
        f"{ENDPOINT}?{query}",
        headers={"User-Agent": "molido/1.0 (positioning)"},
    )
    try:
        open_url = opener or urllib.request.urlopen
        with open_url(request, timeout=timeout) as response:
            rows = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as problem:
        raise ProviderError(
            f"the positioning feed answered {problem.code}", status=problem.code
        ) from problem
    except OSError as problem:
        raise ProviderError(
            f"the positioning feed could not be read: {problem}"
        ) from problem
    except ValueError as problem:
        raise ProviderError(
            f"the positioning feed returned something that is not JSON: {problem}"
        ) from problem

    if opener is None:
        _cached[cache_key] = (time.monotonic(), rows)
    return rows


def _read(key: str, contract: str, row: dict[str, Any]) -> Positioning | None:
    """One row, or nothing if it cannot be read as a whole record.

    Partial records are dropped rather than filled in. A report with a long
    count and no short count would produce a net position equal to the longs,
    which reads as an overwhelmingly bullish crowd rather than as missing data.
    """
    try:
        report_date = datetime.strptime(
            str(row["report_date_as_yyyy_mm_dd"])[:10], "%Y-%m-%d"
        ).date()
        return Positioning(
            key=key,
            contract=contract,
            report_date=report_date,
            published_at=published_at(report_date),
            long=int(row["noncomm_positions_long_all"]),
            short=int(row["noncomm_positions_short_all"]),
            open_interest=int(row["open_interest_all"]),
            traders_long=int(row.get("traders_noncomm_long_all") or 0),
            traders_short=int(row.get("traders_noncomm_short_all") or 0),
        )
    except (KeyError, TypeError, ValueError):
        log.warning("positioning.unreadable_row", key=key, contract=contract)
        return None


def history(
    key: str, *, weeks: int = 52, timeout: float = 30.0, opener: Any = None
) -> list[Positioning]:
    """Recent reports for one market, newest first."""
    contract = CONTRACTS.get(key.upper())
    if contract is None:
        raise InsufficientDataError(
            f"no futures contract is mapped for {key}. Positioning is only "
            "available for markets that trade on a US futures exchange, and a "
            "guessed contract would report a different market's crowd.",
            key=key,
            known=sorted(CONTRACTS),
        )

    rows = _rows(contract, limit=weeks, timeout=timeout, opener=opener)
    found = [p for p in (_read(key.upper(), contract, r) for r in rows) if p]
    if not found:
        raise InsufficientDataError(
            f"the positioning feed returned no readable report for {key}.",
            key=key,
            contract=contract,
        )
    return found


def as_of(
    key: str, moment: datetime, *, weeks: int = 52, timeout: float = 30.0, opener: Any = None
) -> Positioning:
    """The newest report that was already public at `moment`.

    This is the function that makes the rest of the module safe to use in a
    replay. Asking for a Tuesday's positioning on that Tuesday returns the
    *previous* week's report, because that is what a person sitting at a desk
    could have known - and it will feel wrong to anybody reading the raw feed,
    which is exactly why it is done here once rather than remembered at every
    call site.
    """
    if moment.tzinfo is None:
        raise ValueError("as_of needs an aware moment; a naive one has no offset")

    reports = history(key, weeks=weeks, timeout=timeout, opener=opener)
    public = [p for p in reports if p.published_at <= moment]
    if not public:
        raise InsufficientDataError(
            f"no {key} positioning report had been published by "
            f"{moment.isoformat()}. The most recent one describes "
            f"{reports[0].report_date.isoformat()} and does not become public "
            f"until {reports[0].published_at.isoformat()}.",
            key=key,
            moment=moment.isoformat(),
        )
    return max(public, key=lambda p: p.published_at)


def pair_tilt(
    base: str, quote: str, moment: datetime, *, timeout: float = 30.0, opener: Any = None
) -> dict[str, Any]:
    """How the speculative crowd is leaning on a currency pair.

    Both legs are read separately and their normalised net positions
    subtracted, because no contract for a cross exists. USD is the implicit
    other side of every currency future, so a pair against the dollar uses the
    one leg it has and says so - inventing a dollar position by summing the
    others would double-count every currency in the list.
    """
    legs: dict[str, Positioning | None] = {}
    for side in (base.upper(), quote.upper()):
        if side == "USD":
            legs[side] = None
            continue
        legs[side] = as_of(side, moment, timeout=timeout, opener=opener)

    base_leg, quote_leg = legs[base.upper()], legs[quote.upper()]
    if base_leg is None and quote_leg is None:
        raise InsufficientDataError(
            "neither side of this pair has a futures contract", base=base, quote=quote
        )

    base_share = base_leg.net_share if base_leg else 0.0
    quote_share = quote_leg.net_share if quote_leg else 0.0

    return {
        "base": base.upper(),
        "quote": quote.upper(),
        # Positive means the crowd is longer the base than the quote.
        "tilt": round(base_share - quote_share, 6),
        "base_leg": base_leg.as_dict() if base_leg else None,
        "quote_leg": quote_leg.as_dict() if quote_leg else None,
        # Stated rather than implied: against the dollar, one side of this is
        # the absence of a contract rather than a crowd that is flat.
        "dollar_leg_implicit": base_leg is None or quote_leg is None,
    }
