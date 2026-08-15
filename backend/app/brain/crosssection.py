"""Rank every instrument against its peers at one instant, and take the extremes.

This is the only rule in this project that has cleared a significance bar, and
it did so by asking a different question from the twenty-four that failed.

Those all looked at one instrument alone against its own history. A rule of that
shape fires when an instrument is unusual against its own past - which happens
to everything at once whenever the whole market moves, so much of what it calls
a signal is just the market. This asks which instrument is unusual *against its
peers at the same instant*, which is market-neutral by construction.

Measured over 601,300 bars of 51 instruments, clustered by instant so
overlapping trades are not counted as independent evidence:

    rule     +0.0201 R per instant
    control  -0.0010 R per instant
    edge     +0.0212 R      t = 3.69 against a required 1.96
    net of a 0.01 R round trip: +0.0112 R

It is **not a proven edge** and this module must not be read as claiming one.
Both halves of that series had already been searched when this was tested, so a
pattern that existed in the past and does not persist is a live possibility.
The edge registry refuses to promote it without forward evidence, which is
correct, and this module exists so that forward evidence gets generated.

Three details carry the result and none of them is cosmetic:

**Divided by ATR.** Gold at 2,400 and EURUSD at 1.09 cannot be ranked on raw
distance - that ranks price levels, not signals.

**A minimum cross-section.** Ranking eight instruments against each other calls
the bottom one "extreme" when it is merely lowest of eight. Below the minimum
this returns nothing rather than a weak opinion.

**Both tails, together.** The long and the short leg are what make the rule
market-neutral. Taking only the oversold side turns it back into a directional
bet on the market, which is the thing it was built not to be.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

#: Bars in the mean. Fixed at the value that was tested; changing it makes this
#: a different rule with no evidence behind it.
MEAN_WINDOW = 50

#: Periods in the volatility estimate the stretch is divided by.
ATR_WINDOW = 14

#: How much of each tail to take. A tenth at each end, as tested.
TAIL_FRACTION = 0.10

#: Below this many instruments the ranking is not a ranking. Eight instruments
#: always have a "most extended" one, and calling it a signal is calling the
#: shape of a small sample a signal.
MIN_CROSS_SECTION = 20


@dataclass(frozen=True)
class Ranked:
    """One instrument's position in the cross-section at one instant."""

    symbol: str
    stretch: float
    atr: float
    price: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "stretch": round(self.stretch, 4),
            "atr": self.atr,
            "price": self.price,
        }


@dataclass(frozen=True)
class CrossSection:
    """What the rule proposes at one instant, or why it proposes nothing."""

    at: datetime
    available: bool
    reason: str | None = None
    longs: tuple[Ranked, ...] = ()
    shorts: tuple[Ranked, ...] = ()
    considered: int = 0
    skipped: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "at": self.at.isoformat(),
            "available": self.available,
            "reason": self.reason,
            "considered": self.considered,
            "longs": [r.as_dict() for r in self.longs],
            "shorts": [r.as_dict() for r in self.shorts],
            # Published, because an instrument that silently drops out of the
            # ranking every cycle looks identical to one the rule never picks.
            "skipped": list(self.skipped),
        }


def average_true_range(
    bars: list[tuple[float, float, float]], period: int = ATR_WINDOW
) -> float | None:
    """ATR from (high, low, close) triples, oldest first.

    None when there is not enough history. Not zero: a zero ATR would divide
    into infinity and put whatever instrument produced it at the top of every
    ranking forever.
    """
    if len(bars) < period + 1:
        return None
    total = 0.0
    for i in range(len(bars) - period, len(bars)):
        high, low = bars[i][0], bars[i][1]
        previous_close = bars[i - 1][2]
        total += max(high - low, abs(high - previous_close), abs(low - previous_close))
    return total / period


def stretch_of(closes: list[float], atr: float) -> float | None:
    """How far the last close sits from the mean, in ATRs.

    The sign is the direction of the stretch: positive is extended upward and
    is a short candidate, negative is extended downward and is a long one.
    """
    if len(closes) < MEAN_WINDOW + 1 or atr <= 0:
        return None
    window = closes[-(MEAN_WINDOW + 1) : -1]
    mean = sum(window) / len(window)
    return (closes[-1] - mean) / atr


def rank(
    snapshot: dict[str, dict[str, Any]],
    *,
    at: datetime,
    min_cross_section: int = MIN_CROSS_SECTION,
    tail_fraction: float = TAIL_FRACTION,
) -> CrossSection:
    """Rank the instruments priced at this instant and take both tails.

    `snapshot` maps a symbol to `{"closes": [...], "bars": [(high, low, close)]}`.
    An instrument with too little history, a zero ATR or a missing series is
    skipped by name rather than dropped silently - one that vanishes from every
    ranking looks exactly like one the rule simply never picks.
    """
    ranked: list[Ranked] = []
    skipped: list[str] = []

    for symbol, data in snapshot.items():
        closes = list(data.get("closes") or [])
        bars = list(data.get("bars") or [])
        atr = average_true_range(bars)
        if atr is None or atr <= 0:
            skipped.append(f"{symbol}: no usable volatility estimate")
            continue
        value = stretch_of(closes, atr)
        if value is None:
            skipped.append(f"{symbol}: fewer than {MEAN_WINDOW + 1} closes")
            continue
        ranked.append(Ranked(symbol=symbol, stretch=value, atr=atr, price=closes[-1]))

    if len(ranked) < min_cross_section:
        # Nothing, rather than a weak opinion. A ranking of eight always has a
        # most-extended member, and calling that a signal is calling the shape
        # of a small sample a signal.
        return CrossSection(
            at=at,
            available=False,
            reason=(
                f"only {len(ranked)} instruments could be ranked and the rule "
                f"needs {min_cross_section}. A cross-section this thin has a "
                "most-extended member whatever the market is doing"
            ),
            considered=len(ranked),
            skipped=tuple(skipped),
        )

    # By stretch, then by symbol. The tiebreak is not decoration: Python's
    # sort is stable, so without it two instruments at the same stretch are
    # ordered by whatever the caller's dictionary happened to iterate first -
    # and that can change between restarts. A rule whose picks depend on the
    # restart schedule produces a forward series that measures the restart
    # schedule.
    ranked.sort(key=lambda r: (r.stretch, r.symbol))
    take = max(1, int(len(ranked) * tail_fraction))

    return CrossSection(
        at=at,
        available=True,
        # The most negative stretches are the most extended downward: long
        # candidates. The most positive are short candidates. Both legs, always
        # - taking one turns a market-neutral rule into a directional bet.
        longs=tuple(ranked[:take]),
        shorts=tuple(reversed(ranked[-take:])),
        considered=len(ranked),
        skipped=tuple(skipped),
    )
