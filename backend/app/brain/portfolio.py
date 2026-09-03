"""Portfolio brain (spec phase 22, §25).

The spec's rule is one line: *never evaluate a trade only in isolation.*

Two independently excellent EUR/USD and GBP/USD longs are, in practice, one
larger dollar-short position. A risk engine that sizes each on its own merit
approves twice the exposure it believes it approved, and finds out only when
both stops fill in the same minute.

So this module answers a different question from EV. EV asks "is this trade
worth taking?"; the portfolio asks "is this trade worth taking *given what is
already open*?" A trade can pass the first and fail the second, and when it
does, the portfolio wins.

Three exposures are tracked, in ascending order of how often they are missed:

1. **Instrument** — the same symbol twice. Obvious, and rarely the problem.
2. **Currency** — EUR/USD long and EUR/JPY long share a long EUR leg. Netting
   per currency reveals concentration that a per-symbol view cannot see.
3. **Correlated cluster** — measured correlation from phase 8, not a hand-made
   list of "related pairs". A stale hard-coded list is worse than none, because
   it is trusted.

Correlation is *measured or absent*. When phase 8 has no correlation profile
for a pair, this module says so rather than assuming independence — assuming
independence is exactly the error that makes a portfolio look diversified
while it is not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Above this absolute correlation, two instruments are treated as substantially
# the same risk. 0.7 is the conventional line and, more usefully, it is where
# the shared variance (r² ≈ 0.5) passes half.
CORRELATION_CLUSTER = 0.7

# Portfolio-level ceilings, expressed in R (units of per-trade risk) so they
# are independent of account size and of position-sizing choices.
MAX_TOTAL_RISK_R = 6.0
MAX_CURRENCY_RISK_R = 3.0
MAX_CLUSTER_RISK_R = 3.0
MAX_INSTRUMENT_RISK_R = 2.0

#: How many open positions may lean the same way on one currency, whatever
#: they are sized at.
#:
#: Every other limit here is denominated in R, and that is the right unit for
#: "how much can this lose". It is the wrong unit for "is this one bet or
#: several", and the difference showed up on a live account: ten positions,
#: seven of them long against the yen, all losing together. The currency cap
#: is 3.0 R and the yen exposure was 0.28 R, because the deployment is unsure
#: of itself and sizes every trade at a twenty-fifth of the configured risk.
#:
#: So the guard against concentration scaled down with the very uncertainty
#: that should have made it stricter, and seven identical bets passed a check
#: written to stop three. Seven small copies of one trade are still one trade;
#: the account was not diversified, it was only quiet about it.
#:
#: A count does not shrink. Three is the same intent as MAX_CURRENCY_RISK_R -
#: three trades' worth on one currency - in a unit that survives being unsure.
MAX_SAME_CURRENCY_POSITIONS = 3


@dataclass
class Position:
    """An open position, expressed in the only unit that composes: risk.

    `risk_r` is what is lost if the stop fills — 1.0 for a standard one-unit
    trade. Sizes and lots are broker-specific and do not aggregate across
    instruments; risk does.
    """

    symbol: str
    direction: str  # "buy" | "sell"
    risk_r: float
    base_currency: str | None = None
    quote_currency: str | None = None

    def legs(self) -> dict[str, float]:
        """Signed currency exposure. Long EUR/USD is +EUR and −USD."""
        sign = 1.0 if self.direction == "buy" else -1.0
        out: dict[str, float] = {}
        if self.base_currency:
            out[self.base_currency] = out.get(self.base_currency, 0.0) + sign * self.risk_r
        if self.quote_currency:
            out[self.quote_currency] = out.get(self.quote_currency, 0.0) - sign * self.risk_r
        return out


@dataclass
class PortfolioVerdict:
    allowed: bool
    verdict: str  # "approve" | "reduce" | "block"
    max_additional_risk_r: float
    breaches: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    exposures: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "verdict": self.verdict,
            "max_additional_risk_r": round(self.max_additional_risk_r, 4),
            "breaches": self.breaches,
            "warnings": self.warnings,
            "exposures": self.exposures,
        }


def currency_exposure(positions: list[Position]) -> dict[str, float]:
    """Net signed exposure per currency across the whole book."""
    totals: dict[str, float] = {}
    for position in positions:
        for currency, amount in position.legs().items():
            totals[currency] = totals.get(currency, 0.0) + amount
    return {k: round(v, 6) for k, v in sorted(totals.items())}


def correlated_cluster(
    symbol: str,
    positions: list[Position],
    correlations: dict[str, float] | None,
) -> tuple[list[str], list[str]]:
    """(symbols correlated with `symbol`, symbols whose correlation is unknown).

    The second list is the important one. An unmeasured pair is not an
    uncorrelated pair, and collapsing the two is how a book that looks spread
    across six instruments turns out to be one position.
    """
    correlations = correlations or {}
    clustered: list[str] = []
    unknown: list[str] = []

    for position in positions:
        if position.symbol == symbol:
            continue
        value = correlations.get(position.symbol)
        if value is None:
            unknown.append(position.symbol)
        elif abs(value) >= CORRELATION_CLUSTER:
            clustered.append(position.symbol)

    return sorted(set(clustered)), sorted(set(unknown))


def evaluate(
    *,
    symbol: str,
    direction: str,
    proposed_risk_r: float,
    positions: list[Position],
    base_currency: str | None = None,
    quote_currency: str | None = None,
    correlations: dict[str, float] | None = None,
) -> PortfolioVerdict:
    """Decide what the book can still absorb of this trade.

    Returns the *headroom*, not just a yes or no: the risk engine downstream
    needs to know how much it may take, and "reduce to 0.4 R" is a far more
    useful answer than "no".
    """
    if proposed_risk_r <= 0:
        return PortfolioVerdict(
            allowed=False,
            verdict="block",
            max_additional_risk_r=0.0,
            breaches=["proposed risk must be positive"],
        )

    candidate = Position(
        symbol=symbol,
        direction=direction,
        risk_r=proposed_risk_r,
        base_currency=base_currency,
        quote_currency=quote_currency,
    )

    current_total = sum(p.risk_r for p in positions)
    instrument_risk = sum(p.risk_r for p in positions if p.symbol == symbol)

    clustered, unknown = correlated_cluster(symbol, positions, correlations)
    cluster_risk = sum(p.risk_r for p in positions if p.symbol in clustered)

    # Currency headroom is computed on the *worst* leg the new trade touches:
    # a trade that would take one currency over the line is capped by that
    # currency even if its other leg has room.
    exposures = currency_exposure(positions)
    candidate_legs = candidate.legs()

    headrooms: list[tuple[str, float]] = [
        ("total", MAX_TOTAL_RISK_R - current_total),
        ("instrument", MAX_INSTRUMENT_RISK_R - instrument_risk),
        ("cluster", MAX_CLUSTER_RISK_R - cluster_risk),
    ]
    for currency, leg in candidate_legs.items():
        if leg == 0:
            continue
        # Only the direction the new trade pushes matters: adding a long EUR
        # leg is constrained by existing long EUR, not by short EUR elsewhere.
        existing = exposures.get(currency, 0.0)
        same_direction = existing if (existing > 0) == (leg > 0) else 0.0
        headrooms.append((f"currency:{currency}", MAX_CURRENCY_RISK_R - abs(same_direction)))

    # The count limit, which does not shrink when the trades do.
    for currency, leg in candidate_legs.items():
        if leg == 0:
            continue
        same_side = sum(
            1
            for position in positions
            for held_currency, held_leg in position.legs().items()
            if held_currency == currency and held_leg != 0 and (held_leg > 0) == (leg > 0)
        )
        if same_side >= MAX_SAME_CURRENCY_POSITIONS:
            # Expressed as headroom rather than as its own veto, so it travels
            # the same path as every other limit: one reported cause, one place
            # that decides, and a caller that cannot forget to check this one.
            #
            # The value is how far past the limit this currency already is,
            # negative, rather than a flat zero. `min` then reports the worst
            # breach instead of whichever was appended first - the live book
            # was three deep on USD and seven deep on JPY, both at zero
            # headroom, and it named USD. That is true and it is not the
            # sentence somebody needs to read.
            #
            # Only added when it is breached. A positive count headroom would
            # be compared against headrooms measured in R, and "1 position of
            # room" would cap a trade at 1.0 R for no reason anybody chose.
            headrooms.append(
                (
                    f"currency-count:{currency}",
                    float(MAX_SAME_CURRENCY_POSITIONS - same_side),
                )
            )

    limiting_name, headroom = min(headrooms, key=lambda item: item[1])
    headroom = max(0.0, headroom)
    allowed_risk = min(proposed_risk_r, headroom)

    breaches: list[str] = []
    warnings: list[str] = []

    if headroom <= 0:
        breaches.append(f"{limiting_name} limit already reached")
    elif allowed_risk < proposed_risk_r:
        warnings.append(
            f"{limiting_name} limit caps this trade at {allowed_risk:.2f} R "
            f"of the {proposed_risk_r:.2f} R proposed"
        )

    if clustered:
        warnings.append(
            "correlated with open positions (|r| >= "
            f"{CORRELATION_CLUSTER}): {', '.join(clustered)}"
        )
    if unknown:
        # Not a breach, but never silent: an unmeasured pair is a hole in the
        # picture, not a confirmed absence of correlation.
        warnings.append(
            "correlation unmeasured against: " + ", ".join(unknown)
            + " — treated as unknown, not as uncorrelated"
        )

    if allowed_risk <= 0:
        verdict = "block"
    elif allowed_risk < proposed_risk_r:
        verdict = "reduce"
    else:
        verdict = "approve"

    return PortfolioVerdict(
        allowed=allowed_risk > 0,
        verdict=verdict,
        max_additional_risk_r=allowed_risk,
        breaches=breaches,
        warnings=warnings,
        exposures={
            "total_risk_r": round(current_total, 4),
            "instrument_risk_r": round(instrument_risk, 4),
            "cluster_risk_r": round(cluster_risk, 4),
            "currencies": exposures,
            "correlated_with": clustered,
            "correlation_unknown": unknown,
            "limiting_constraint": limiting_name,
        },
    )
