"""What moves a currency other than its own chart.

Every other read in this API is derived from price. These two are not: what a
central bank charges, and where the large speculators actually sit. Both are
facts about the world rather than about a series, and neither can be recovered
from a candle no matter how it is transformed.

**Nothing here is a recommendation.** A rate differential says a position is
paid or charged to hold; a crowded speculative book says a lot of people
already own the trade. Both are inputs with well-documented failure modes -
carry unwinds violently and crowded trades stay crowded for years - so these
routes report the measurements and stop there, in the same way the rest of this
API reports a proposal rather than an instruction.

**Two different freshness stories, told separately.** Policy rates are a live
reading, correct as of now and unavailable for any past instant, because the
upstream feed carries only the newest observation. Positioning is a weekly
report with a three-day publication lag, so it can be asked as of a moment and
will answer with what was public then. Merging them into one "fundamentals"
blob would hide that difference, and the difference is the part a person needs
in order to know what they are looking at.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import Principal, require
from app.core.enums import Permission
from app.core.errors import MolidoError
from app.services import policy_rates, positioning

router = APIRouter(prefix="/fundamentals", tags=["fundamentals"])

READ = Depends(require(Permission.READ))

#: The pairs the rate differential is reported for without being asked.
#: Deliberately the majors: every one of them has both legs in the feed, so
#: none of them can render as an unexplained gap on a landing panel.
HEADLINE_PAIRS: tuple[tuple[str, str], ...] = (
    ("EUR", "USD"),
    ("GBP", "USD"),
    ("USD", "JPY"),
    ("AUD", "USD"),
    ("USD", "CAD"),
    ("USD", "CHF"),
    ("NZD", "USD"),
    ("AUD", "JPY"),
    ("EUR", "GBP"),
)


@router.get("/policy-rates")
def read_policy_rates(_: Principal = READ) -> dict[str, Any]:
    """Every central bank rate this platform can attribute to a currency.

    The feed is refused rather than approximated when it cannot be read. A
    stale rate differential is indistinguishable from a live one on a screen,
    which is exactly why an unreachable source has to be reported as one.
    """
    try:
        rates = policy_rates.current()
    except MolidoError as problem:
        return {
            "available": False,
            "reason": problem.message,
            "rates": [],
            "differentials": [],
        }

    differentials = []
    for base, quote in HEADLINE_PAIRS:
        try:
            differentials.append(
                {
                    "pair": f"{base}{quote}",
                    "base": base,
                    "quote": quote,
                    "differential": policy_rates.differential(base, quote, rates),
                }
            )
        except MolidoError:
            # One missing leg costs one pair, never the table. A currency the
            # feed stopped carrying should show up as a gap in one row rather
            # than as an empty panel nobody can diagnose.
            continue

    return {
        "available": True,
        "rates": [r.as_dict() for r in sorted(rates.values(), key=lambda r: -r.rate)],
        "differentials": differentials,
        # Said plainly, because the alternative is a reader assuming this is a
        # historical series and quietly using it as one.
        "note": (
            "a live reading of the newest observation per bank; it carries no "
            "history and cannot be asked for a past date"
        ),
    }


@router.get("/positioning")
def read_positioning(
    key: str = Query(..., description="A currency (EUR) or a market (XAUUSD)"),
    _: Principal = READ,
) -> dict[str, Any]:
    """Where the speculative crowd sits in one futures market.

    Keyed on when the report became public rather than on the Tuesday it
    describes, so what comes back is what a person at a desk could have known
    at this moment - not what had happened by it.
    """
    now = datetime.now(UTC)
    try:
        latest = positioning.as_of(key, now)
        recent = positioning.history(key, weeks=12)
    except MolidoError as problem:
        return {
            "available": False,
            "key": key.upper(),
            "reason": problem.message,
            "known": sorted(positioning.CONTRACTS),
        }

    return {
        "available": True,
        "key": key.upper(),
        "latest": latest.as_dict(),
        "net_share": latest.net_share if latest.open_interest > 0 else None,
        # Published-and-visible only. A twelve week window that quietly
        # included this week's unpublished report would make every chart drawn
        # from it a slightly different chart from the one a trader saw.
        "history": [
            p.as_dict() for p in recent if p.published_at <= now
        ],
        "note": (
            "the CFTC publishes Tuesday's positions on the Friday after, so "
            "the newest row here is up to a week old by design"
        ),
    }
