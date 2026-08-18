"""Candidate rules, measured through the same pipeline as the one that failed.

The cross-sectional stretch rule was the only thing this system could test,
so the whole measurement apparatus was built around its shape. That made the
apparatus the valuable part and the rule the disposable one - which is the
right way round, and only became obvious once the rule stopped surviving its
own numbers.

A rule here is one function: it sees a snapshot cut at the decision instant
and returns the symbols it wants long and short. Everything that makes the
measurement trustworthy - the point-in-time cut, the random control written in
the same call, the clustering by instant, the cost charged against the stop -
lives outside it and is identical for every candidate.

That matters more than any single rule. A candidate measured under its own
harness proves nothing about the others; measured under this one, the
comparison is the point.

**No rule here is claimed to work.** They are hypotheses with published
priors, written so the machine can refuse them quickly. The cross-sectional
one is kept as the baseline precisely because it is known to fail: a harness
that cannot reproduce a known negative is not measuring anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from app.brain import crosssection


@dataclass(frozen=True)
class Picks:
    """What a rule wants to hold at one instant."""

    longs: tuple[str, ...] = ()
    shorts: tuple[str, ...] = ()
    #: Named when a rule declines. A rule that returns nothing because the
    #: cross-section was thin and one that returns nothing because it saw no
    #: signal are different facts, and the measurement counts them apart.
    declined: str | None = None

    @property
    def empty(self) -> bool:
        return not self.longs and not self.shorts


class Rule(Protocol):
    """Sees a snapshot cut at the instant, names what it wants to hold."""

    name: str

    def __call__(
        self, snapshot: dict[str, dict[str, Any]], *, universe: frozenset[str] | None
    ) -> Picks: ...


def _closes(snapshot: dict[str, dict[str, Any]], symbol: str) -> list[float]:
    return list(snapshot.get(symbol, {}).get("closes") or [])


def _eligible(
    snapshot: dict[str, dict[str, Any]], universe: frozenset[str] | None
) -> list[str]:
    return sorted(
        symbol
        for symbol in snapshot
        if universe is None or symbol in universe
    )


# --------------------------------------------------------------------- rules


class CrossSectionalStretch:
    """The incumbent, kept as the baseline that is known to fail.

    A harness that cannot reproduce a known negative is not measuring
    anything, so this stays in the list rather than being deleted with the
    conclusion.
    """

    name = "cross-sectional-stretch"

    def __call__(
        self, snapshot: dict[str, dict[str, Any]], *, universe: frozenset[str] | None
    ) -> Picks:
        ranked = crosssection.rank(
            snapshot,
            at=max(
                (row.get("last_at") for row in snapshot.values() if row.get("last_at")),
                default=None,
            ),
            universe=universe,
        )
        if not ranked.available:
            return Picks(declined="the cross-section was too thin to rank")
        return Picks(
            longs=tuple(pick.symbol for pick in ranked.longs),
            shorts=tuple(pick.symbol for pick in ranked.shorts),
        )


@dataclass(frozen=True)
class TimeSeriesMomentum:
    """Each instrument judged against its own past, not against the others.

    The most replicated effect in futures and currencies: an instrument that
    has risen over the last year tends to keep rising over the next month, and
    the effect is *time-series* rather than cross-sectional - it asks whether
    this instrument is above its own past, not whether it is above its peers.

    That distinction is the reason to test it here. The incumbent ranks
    instruments against each other, which is exactly the comparison that made
    pegged currencies look enormous: a policy-flat instrument has a tiny
    denominator and takes both tails. A rule that never compares two
    instruments cannot be captured that way.

    Sized by the *sign* of the lookback return rather than its magnitude, so
    one violent instrument cannot dominate the book - the same reason the
    agreement check counts votes instead of averaging them.
    """

    name: str = "time-series-momentum"
    #: Bars of lookback. Twelve months of daily bars, the horizon the
    #: published result uses; shorter windows are where it is weakest.
    lookback: int = 252
    #: How many instruments to hold per side. Both sides always, so the book
    #: stays close to market-neutral and the measurement is about the rule
    #: rather than about whether the dollar went up.
    per_side: int = 4

    def __call__(
        self, snapshot: dict[str, dict[str, Any]], *, universe: frozenset[str] | None
    ) -> Picks:
        scored: list[tuple[float, str]] = []
        for symbol in _eligible(snapshot, universe):
            closes = _closes(snapshot, symbol)
            if len(closes) < self.lookback + 1:
                continue
            past, now = closes[-self.lookback - 1], closes[-1]
            if past <= 0:
                continue
            scored.append(((now - past) / past, symbol))

        if len(scored) < self.per_side * 2:
            return Picks(
                declined=(
                    f"only {len(scored)} instruments have {self.lookback} bars of "
                    "history, which is fewer than the book needs"
                )
            )

        scored.sort()
        return Picks(
            longs=tuple(symbol for _, symbol in scored[-self.per_side :]),
            shorts=tuple(symbol for _, symbol in scored[: self.per_side]),
        )


@dataclass(frozen=True)
class ShortHorizonReversal:
    """The incumbent's idea at a horizon where it has published support.

    Cross-sectional reversal in currencies is documented over days rather than
    over the twenty-bar mean the incumbent uses, and measured on returns
    rather than in ATR units. Both differences matter: returns have no
    denominator that collapses on a pegged instrument.

    Kept because it isolates one variable. If this works where the incumbent
    does not, the failure was the ATR denominator rather than the idea.
    """

    name: str = "short-horizon-reversal"
    lookback: int = 5
    per_side: int = 4

    def __call__(
        self, snapshot: dict[str, dict[str, Any]], *, universe: frozenset[str] | None
    ) -> Picks:
        scored: list[tuple[float, str]] = []
        for symbol in _eligible(snapshot, universe):
            closes = _closes(snapshot, symbol)
            if len(closes) < self.lookback + 1:
                continue
            past, now = closes[-self.lookback - 1], closes[-1]
            if past <= 0:
                continue
            scored.append(((now - past) / past, symbol))

        if len(scored) < self.per_side * 2:
            return Picks(
                declined=f"only {len(scored)} instruments have enough history"
            )

        scored.sort()
        # Reversal: buy what fell, sell what rose. The opposite end from
        # momentum, deliberately, so the two cannot both be right and the
        # measurement has to choose.
        return Picks(
            longs=tuple(symbol for _, symbol in scored[: self.per_side]),
            shorts=tuple(symbol for _, symbol in scored[-self.per_side :]),
        )


#: Every candidate, by name. Adding one here is the whole cost of testing it.
CANDIDATES: dict[str, Rule] = {
    rule.name: rule  # type: ignore[misc]
    for rule in (
        CrossSectionalStretch(),
        TimeSeriesMomentum(),
        ShortHorizonReversal(),
    )
}


def get(name: str) -> Rule | None:
    return CANDIDATES.get(name)


def names() -> list[str]:
    return sorted(CANDIDATES)
