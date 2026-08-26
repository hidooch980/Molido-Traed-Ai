"""What the world's central banks are charging, from the BIS.

The fundamental driver of a currency pair is not either country's interest
rate; it is the difference between them. A trader long AUD/JPY is paid the gap
between what the Reserve Bank of Australia charges and what the Bank of Japan
charges, every night, whether or not the price moves. That gap is the single
number this module exists to produce, and nothing else here could compute it -
every other calculator in this codebase reads prices, and a price series does
not contain the reason it drifts.

**One source, forty-nine central banks, no key.** The Bank for International
Settlements publishes each member's policy rate as a single dataset. Taking it
from one place rather than from eight separate central bank sites is not
laziness: eight sources means eight parsers, eight formats and eight
opportunities for one of them to quietly change and take a currency's rate to
zero without anything failing. The BIS also does the harder half of the work -
deciding which of a central bank's several published rates is *the* policy rate
- and it does it consistently across all of them, which is what makes the
differences between them comparable at all.

**This is a live reading, not a point-in-time series.** It answers "what is the
rate now", and `lastNObservations=1` is exactly what it asks for. That makes it
correct for a decision being taken today and wrong for a decision being
replayed from last year, which would see a rate set after the bar it is
deciding on. `as_of` refuses that read rather than serving it, because a
backtest that quietly knows next month's rate decision produces a strategy that
cannot exist.

**A missing currency is refused, never defaulted.** A zero would be a plausible
number - the Swiss National Bank's rate genuinely is zero - so a missing rate
silently read as zero would produce a differential that is wrong by exactly the
size of the rate, in the direction of "this pair pays nothing", and nothing
downstream could tell the two apart.
"""

from __future__ import annotations

import csv
import io
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app.core.errors import InsufficientDataError, LookaheadViolationError, ProviderError
from app.core.logging import get_logger

log = get_logger(__name__)

#: Daily frequency, every reference area the dataset carries. One request.
FEED = (
    "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/D.*"
    "?format=csv&lastNObservations=1"
)

#: BIS reference area -> the currency that rate belongs to, and who sets it.
#:
#: Pinned rather than derived. An area code is not a currency code - the euro
#: area is `XM`, which no ISO currency table will map to EUR - and guessing
#: from a two-letter prefix would map `CH` to a Chinese currency and hand the
#: Swiss rate to the yuan. Every entry here was read off the live feed.
AREAS: dict[str, tuple[str, str]] = {
    "US": ("USD", "Federal Reserve"),
    "XM": ("EUR", "European Central Bank"),
    "GB": ("GBP", "Bank of England"),
    "JP": ("JPY", "Bank of Japan"),
    "CH": ("CHF", "Swiss National Bank"),
    "CA": ("CAD", "Bank of Canada"),
    "AU": ("AUD", "Reserve Bank of Australia"),
    "NZ": ("NZD", "Reserve Bank of New Zealand"),
    "SE": ("SEK", "Sveriges Riksbank"),
    "NO": ("NOK", "Norges Bank"),
    "MX": ("MXN", "Banco de Mexico"),
    "ZA": ("ZAR", "South African Reserve Bank"),
    "TR": ("TRY", "Central Bank of Turkey"),
    "PL": ("PLN", "Narodowy Bank Polski"),
    "BR": ("BRL", "Banco Central do Brasil"),
    "IN": ("INR", "Reserve Bank of India"),
    "CN": ("CNY", "People's Bank of China"),
    "KR": ("KRW", "Bank of Korea"),
}

#: Rates move on scheduled meeting days, six to eight times a year per bank.
#: An hour of staleness cannot straddle a decision that matters, and the
#: alternative is one request per page load to another continent.
CACHE_SECONDS = 3600

#: Set by `fetch`, read by `fetch`. Module-level for the same reason the
#: calendar's is: a cache the caller has to remember to pass is one that gets
#: bypassed.
_cached: tuple[float, str] | None = None


@dataclass(frozen=True)
class PolicyRate:
    """One central bank's policy rate, as the BIS records it."""

    currency: str
    area: str
    bank: str
    #: Per cent per year, as published. Not a decimal fraction - 3.625 means
    #: 3.625%, and dividing it here would put the unit in two places.
    rate: float
    observed: date

    def as_dict(self) -> dict[str, Any]:
        return {
            "currency": self.currency,
            "area": self.area,
            "bank": self.bank,
            "rate": self.rate,
            "observed": self.observed.isoformat(),
        }


def fetch(*, timeout: float = 30.0, opener: Any = None) -> str:
    """The raw feed, reused for `CACHE_SECONDS` between fetches.

    A failed fetch does not poison the cache, and a cached answer is not served
    past its age. The alternative is a page that keeps reporting last quarter's
    rates because the feed went down - which is worse than one that says it
    could not read them, because a stale rate differential looks exactly like a
    live one.
    """
    global _cached

    if opener is None and _cached is not None:
        cached_at, body = _cached
        if time.monotonic() - cached_at < CACHE_SECONDS:
            return body

    request = urllib.request.Request(  # noqa: S310 - constant https URL
        FEED, headers={"User-Agent": "molido/1.0 (policy rates)"}
    )
    try:
        open_url = opener or urllib.request.urlopen
        with open_url(request, timeout=timeout) as response:
            body = str(response.read().decode("utf-8", "replace"))
        # Stored only on success, and only for the real opener - a test that
        # injects one must never leave its fixture in the cache for the next.
        if opener is None:
            _cached = (time.monotonic(), body)
        return body
    except urllib.error.HTTPError as problem:
        raise ProviderError(
            f"the policy rate feed answered {problem.code}", status=problem.code
        ) from problem
    except OSError as problem:
        raise ProviderError(
            f"the policy rate feed could not be read: {problem}"
        ) from problem


def parse(body: str) -> dict[str, PolicyRate]:
    """Currency -> its central bank's rate, for the areas this platform trades.

    Rows for areas outside `AREAS` are dropped rather than kept under their own
    code. A rate nobody can attribute to a currency cannot enter a differential,
    and carrying it would only make the count look healthier than the coverage.
    """
    rates: dict[str, PolicyRate] = {}

    for row in csv.DictReader(io.StringIO(body)):
        area = (row.get("REF_AREA") or "").strip()
        mapping = AREAS.get(area)
        if mapping is None:
            continue

        raw_value = (row.get("OBS_VALUE") or "").strip()
        raw_period = (row.get("TIME_PERIOD") or "").strip()
        if not raw_value or not raw_period:
            # A row with no observation is a bank that has not reported, which
            # is not the same as a bank at zero.
            continue

        try:
            value = float(raw_value)
            observed = datetime.strptime(raw_period[:10], "%Y-%m-%d").date()
        except ValueError:
            log.warning(
                "policy_rates.unreadable_row", area=area, value=raw_value,
                period=raw_period,
            )
            continue

        currency, bank = mapping
        rates[currency] = PolicyRate(
            currency=currency, area=area, bank=bank, rate=value, observed=observed
        )

    return rates


#: The parsed reading, keyed to the raw body it came from.
#:
#: `fetch` has always cached the download; `parse` ran on every call, which was
#: free while this was read once to draw a page. It stopped being free when the
#: decision chain began asking for a differential per instrument: forty-three
#: instruments meant parsing forty-nine central banks forty-three times to
#: answer a question whose input had not changed.
_parsed: tuple[str, dict[str, PolicyRate]] | None = None


def current(*, timeout: float = 30.0, opener: Any = None) -> dict[str, PolicyRate]:
    """Every policy rate this platform can attribute to a currency, right now."""
    global _parsed

    body = fetch(timeout=timeout, opener=opener)

    # Keyed on the body rather than on a clock, so this cache cannot outlive
    # the fetch cache that feeds it. A separate expiry would eventually serve a
    # parse of a document that had already been replaced.
    if _parsed is not None and _parsed[0] == body:
        # Copied, because callers pass this dict into `differential` and a
        # shared mutable reading is one a caller can edit for everybody else.
        return dict(_parsed[1])

    rates = parse(body)
    _parsed = (body, rates)
    return dict(rates)


def as_of(moment: date, *, timeout: float = 30.0, opener: Any = None) -> dict[str, PolicyRate]:
    """The same reading, refused if it would see past `moment`.

    The feed carries only the newest observation per bank, so there is no
    honest way to answer "what was the rate last March" from it. Rather than
    return today's rates against a historical timestamp - which is a decision
    that knows the outcome of a meeting that had not happened - this refuses.

    Callers replaying history need a stored series, and the absence of one is
    the reason this raises instead of quietly being useful.
    """
    rates = current(timeout=timeout, opener=opener)
    ahead = sorted(
        {r.currency for r in rates.values() if r.observed > moment}
    )
    if ahead:
        raise LookaheadViolationError(
            "the policy rate feed only carries today's rates, and these were "
            f"set after {moment.isoformat()}: {', '.join(ahead)}. Reading them "
            "against that date would decide with information that did not "
            "exist yet.",
            as_of=moment.isoformat(),
            currencies=ahead,
        )
    return rates


def differential(
    base: str, quote: str, rates: dict[str, PolicyRate] | None = None, **kwargs: Any
) -> float:
    """What holding `base` against `quote` is paid in policy rate terms.

    Positive means the base currency earns more than the quote, which is the
    direction a carry trade wants. AUD/JPY at +3.35 means the Reserve Bank of
    Australia charges 3.35 percentage points more than the Bank of Japan.

    Both sides must be present. A pair with one known rate has no differential,
    and returning the known side alone would be off by the whole of the missing
    one while looking like an ordinary number.
    """
    known = rates if rates is not None else current(**kwargs)

    missing = [c for c in (base, quote) if c not in known]
    if missing:
        raise InsufficientDataError(
            "no policy rate for " + ", ".join(missing) + ", so the rate "
            "differential for this pair cannot be computed. A missing rate is "
            "not a rate of zero.",
            missing=missing,
            known=sorted(known),
        )

    return round(known[base].rate - known[quote].rate, 4)
