"""What holding a position costs in interest, before it has moved at all.

A trade is not free to keep open. Every night it is held, the difference
between the two countries' policy rates is paid or charged, and over a week
that is a real number on the statement whether or not the price did anything.
The expected value model already knows this - `CostModel` has had a `swap`
field since it was written - and on any deployment without a broker symbol
configured it has always been `None`, which means every decision has been made
with "we do not know the swap" in its list of unmeasured costs.

This turns the policy rate differential into that number.

**It is an estimate, and the broker's own figure beats it.** What a broker
actually charges is the interbank differential plus their markup, which can be
several times the differential on a retail account. So this is a floor rather
than a forecast: it says a carry-negative trade costs *at least* this much. A
configured broker swap is used instead wherever one exists, and the caller
decides that rather than this module.

**The holding period is policy, not measurement.** Nothing at decision time
knows how long a position will be open - that is what the stop and the target
are for. So a number has to be chosen and published, in the same way the stop
distance is a stated multiple of ATR rather than a derived fact. Three days is
the choice, and a trade that closes the same afternoon will have been charged
for a carry it never paid. That error is small next to the spread, and it is
in the conservative direction for the trades this most affects.

**Swap is the one cost that can be a credit,** which is why this returns a
signed number. Spread, commission and slippage are money leaving under every
circumstance. Carry depends on which side is held: long a currency that pays
more than the one it is quoted against is paid to exist. Reporting that as a
cost would be wrong by exactly twice the carry, and in the direction that makes
the trades worth holding look like the trades worth avoiding.
"""

from __future__ import annotations

#: Days a position is assumed to be held, for costing purposes only.
#:
#: Policy, published in the trace. Nothing here forecasts a holding period and
#: nothing acts on this as if it were one - it exists so a per-annum rate can
#: be turned into a number in price units, which requires a duration.
ASSUMED_HOLDING_DAYS = 3.0

#: Days in a year, for the same conversion. Central banks quote per annum and
#: brokers charge per night; 365 rather than 252 because interest accrues at
#: the weekend and the market being shut does not pause it.
DAYS_PER_YEAR = 365.0


def swap_cost(
    *,
    differential_pct: float,
    entry: float,
    direction: str,
    holding_days: float = ASSUMED_HOLDING_DAYS,
) -> float:
    """Carry over the holding period, in price units, as a cost.

    `differential_pct` is the base currency's policy rate minus the quote's,
    in per cent per year - the number `policy_rates.differential` returns.

    The sign convention is the cost model's: **positive means money leaving.**
    So a long position in a pair whose base pays more than its quote returns a
    negative number, because that position is paid to exist. Getting this
    backwards is not a rounding error - it is an error of twice the carry,
    pointing the wrong way.

    >>> round(swap_cost(differential_pct=3.35, entry=100.0, direction="buy"), 6)
    -0.027534
    >>> round(swap_cost(differential_pct=3.35, entry=100.0, direction="sell"), 6)
    0.027534
    """
    if direction not in ("buy", "sell"):
        raise ValueError(f"unknown direction {direction!r}")
    if entry <= 0:
        raise ValueError("entry price must be positive to express carry in price units")
    if holding_days < 0:
        raise ValueError("a position cannot be held for a negative number of days")

    # Per annum on the notional, prorated. The notional is the entry price
    # because the whole model works in price units per unit of instrument.
    over_period = entry * (differential_pct / 100.0) * (holding_days / DAYS_PER_YEAR)

    # Long earns the differential, short pays it; and the model wants a cost,
    # so the earning case is negative.
    return -over_period if direction == "buy" else over_period
