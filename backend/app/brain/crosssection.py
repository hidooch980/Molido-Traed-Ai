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

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

#: Bars in the mean. Fixed at the value that was tested; changing it makes this
#: a different rule with no evidence behind it.
MEAN_WINDOW = 50

#: Periods in the volatility estimate the stretch is divided by.
ATR_WINDOW = 14

#: How much of each tail to take. A tenth at each end, as tested.
TAIL_FRACTION = 0.10

#: The instruments this rule ranks, fixed and versioned.
#:
#: Not "whatever is active in the database". A universe that changes whenever
#: somebody adds an instrument is a universe nobody chose, and a forward
#: measurement taken across a changing universe measures the changes.
#:
#: Gold, silver, oil and five index CFDs became available on the broker the day
#: after this measurement started. They are collected and deliberately not
#: ranked: adding twenty instruments mid-measurement would mean the series
#: covers two different universes and the join is invisible afterwards. Equities
#: and indices also behave differently from currencies - they trend where FX
#: mean-reverts - so including them changes the rule rather than widening it.
#:
#: Adding them is a decision for the next measurement, taken deliberately, with
#: its own start date.
UNIVERSE_VERSION = "fx-metals-crypto-2026-08"

RANKED_UNIVERSE: frozenset[str] = frozenset({
    # Majors and crosses
    "AUDCAD", "AUDCHF", "AUDJPY", "AUDNZD", "AUDUSD",
    "CADCHF", "CADJPY", "CHFJPY",
    "EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURJPY", "EURNZD", "EURUSD",
    "GBPAUD", "GBPCAD", "GBPCHF", "GBPJPY", "GBPNZD", "GBPUSD",
    "NZDCAD", "NZDCHF", "NZDJPY", "NZDUSD",
    "USDCAD", "USDCHF", "USDJPY",
    # Emerging and minor
    "USDCNH", "USDCZK", "USDDKK", "USDHKD", "USDHUF", "USDILS", "USDINR",
    "USDMXN", "USDNOK", "USDPLN", "USDSEK", "USDSGD", "USDTHB", "USDTRY",
    "USDZAR",
    # Metals and crypto, as futures - the series the measurement was taken on
    "GCFUT", "SIFUT", "HGFUT", "PLFUT",
    "BTCUSD", "ETHUSD",
})

#: Below this many instruments the ranking is not a ranking. Eight instruments
#: always have a "most extended" one, and calling it a signal is calling the
#: shape of a small sample a signal.
MIN_CROSS_SECTION = 20

#: How far behind the cross-section's own instant an instrument's last bar may
#: be before it is excluded.
#:
#: This is not a general freshness check; it is specific to what a ranking does.
#: A series that stopped updating keeps its last price while every other
#: instrument moves on, so its distance from its own mean drifts further from
#: the truth with every hour - and drifts in one direction, which means it
#: reliably ranks extreme and is reliably picked. Two frozen duplicates of live
#: symbols were doing exactly that on this deployment before this existed.
#:
#: Three bars: one late bar is a slow provider, three is a series that stopped.
MAX_STALENESS_BARS = 3


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
            "universe": UNIVERSE_VERSION,
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


#: Timeframes must agree at least this often before a signal is treated as
#: confirmed. Two out of three is a coin landing the same way twice; this is
#: the first ratio that is not.
MIN_AGREEMENT = 0.75


def agreement(stretches: Sequence[float | None]) -> tuple[int, int, float | None]:
    """How many timeframes point the same way as the majority of them.

    A stretch that shows on one timeframe and nowhere else is usually the last
    bar rather than a move. One that shows on five is a move. This counts the
    agreement rather than averaging the stretches: averaging lets one violent
    short timeframe outvote four calm long ones, which is the opposite of what
    confirmation means.

    A `None` stretch is a timeframe with too little history to have an opinion.
    It is dropped from both sides rather than counted as disagreement - absent
    is not the same as against - and the total returned is what remained, so a
    caller can tell unanimity-of-five from unanimity-of-one.

    Returns (agreeing, usable, ratio). Ratio is None when nothing was usable,
    because zero out of zero is not zero agreement, it is no evidence.
    """
    usable = [x for x in stretches if x is not None and x != 0.0]
    if not usable:
        return 0, 0, None

    up = sum(1 for x in usable if x > 0)
    down = len(usable) - up
    agreeing = max(up, down)
    return agreeing, len(usable), agreeing / len(usable)


def confirmed(
    stretches: Sequence[float | None],
    *,
    minimum: float = MIN_AGREEMENT,
    direction: float | None = None,
) -> bool:
    """Whether the timeframes agree enough to act on.

    Refuses on a single usable timeframe however emphatic it is: one timeframe
    agreeing with itself is not confirmation, and it would otherwise score a
    perfect 1.0 and pass every threshold.

    `direction` is the reading being confirmed. Without it this asks only
    whether the timeframes agree with *each other*, which is a different and
    much weaker question: three saying down and one saying up is 75% agreement
    and is not confirmation of the up. When a caller is acting on a particular
    reading it must pass that reading here, or the check will happily confirm
    the opposite of what is about to be traded.
    """
    usable = [x for x in stretches if x is not None and x != 0.0]
    if len(usable) < 2:
        return False

    if direction is None:
        _, _, ratio = agreement(usable)
        return ratio is not None and ratio >= minimum

    if direction == 0:
        return False
    with_it = sum(1 for x in usable if (x > 0) == (direction > 0))
    return with_it / len(usable) >= minimum


def rank(
    snapshot: dict[str, dict[str, Any]],
    *,
    at: datetime,
    min_cross_section: int = MIN_CROSS_SECTION,
    tail_fraction: float = TAIL_FRACTION,
    bar_interval: timedelta | None = None,
    universe: frozenset[str] | None = RANKED_UNIVERSE,
    confirmations: dict[str, Sequence[float | None]] | None = None,
) -> CrossSection:
    """Rank the instruments priced at this instant and take both tails.

    `snapshot` maps a symbol to `{"closes": [...], "bars": [(high, low, close)]}`.
    An instrument with too little history, a zero ATR or a missing series is
    skipped by name rather than dropped silently - one that vanishes from every
    ranking looks exactly like one the rule simply never picks.

    `confirmations` optionally maps a symbol to the stretches the same rule
    reads on other timeframes. When given, an instrument whose timeframes
    disagree is skipped by name: a stretch on one timeframe and nowhere else
    is usually the last bar rather than a move.

    Omitted, nothing is filtered and this ranks exactly as it did before. A
    symbol absent from the map is also unfiltered rather than refused - no
    confirmation offered is not the same as confirmation withheld, and
    refusing on absence would silently empty the ranking the first time a
    caller passed a partial map.
    """
    ranked: list[Ranked] = []
    skipped: list[str] = []

    cutoff = (
        at - MAX_STALENESS_BARS * bar_interval if bar_interval is not None else None
    )

    for symbol, data in snapshot.items():
        if universe is not None and symbol not in universe:
            # Collected but not ranked. Naming it rather than dropping it
            # silently: an instrument absent from every ranking looks the same
            # whether it was excluded on purpose or lost by accident.
            skipped.append(f"{symbol}: outside the ranked universe {UNIVERSE_VERSION}")
            continue

        closes = list(data.get("closes") or [])
        bars = list(data.get("bars") or [])

        last_at = data.get("last_at")
        if cutoff is not None and last_at is not None and last_at < cutoff:
            # Excluded by name. A frozen series keeps its last price while
            # everything else moves, so its distance from its own mean drifts
            # one way and it reliably ranks extreme - which means it is
            # reliably picked, and the picks are about the outage rather than
            # the market.
            skipped.append(
                f"{symbol}: last bar {last_at.isoformat()} is more than "
                f"{MAX_STALENESS_BARS} bars behind the cross-section"
            )
            continue

        atr = average_true_range(bars)
        if atr is None or atr <= 0:
            skipped.append(f"{symbol}: no usable volatility estimate")
            continue
        value = stretch_of(closes, atr)
        if value is None:
            skipped.append(f"{symbol}: fewer than {MEAN_WINDOW + 1} closes")
            continue

        if confirmations is not None and symbol in confirmations:
            # This timeframe's own reading votes alongside the others, so a
            # symbol confirmed here is confirmed including the view being
            # ranked rather than by a quorum that excludes it.
            votes = [value, *confirmations[symbol]]
            usable = [v for v in votes if v is not None and v != 0.0]
            agreeing = sum(1 for v in usable if (v > 0) == (value > 0))
            # Confirmed against this reading's own direction, not merely that
            # the timeframes agree among themselves: three saying down and one
            # saying up is 75% agreement and is not confirmation of the up.
            if not confirmed(votes, direction=value):
                skipped.append(
                    f"{symbol}: only {agreeing} of {len(usable)} timeframes agree "
                    f"with this one, "
                    f"under the {MIN_AGREEMENT:.0%} needed to call it a move"
                )
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
