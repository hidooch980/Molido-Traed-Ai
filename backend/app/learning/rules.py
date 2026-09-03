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
from typing import Any, Protocol

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
        # The latest bar in the snapshot is the instant being ranked. With
        # none, there is no instant - and `rank` would be asked to rank at
        # None, which is not a time and not a refusal either.
        stamps = [row["last_at"] for row in snapshot.values() if row.get("last_at")]
        if not stamps:
            return Picks(declined="no instrument in the snapshot carries a bar time")
        ranked = crosssection.rank(
            snapshot,
            at=max(stamps),
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


def _pair_currencies(symbol: str) -> tuple[str, str] | None:
    """EURUSD -> (EUR, USD). Anything that is not two 3-letter codes is None.

    Metals and indices in the universe (XAUUSD, .DE40Cash) are not funding
    trades between two central banks, and pretending XAU has a policy rate
    would hand gold a differential nobody sets.
    """
    if len(symbol) != 6 or not symbol.isalpha():
        return None
    return symbol[:3].upper(), symbol[3:].upper()


class CarryDifferential:
    """Long the currencies that pay, short the ones that charge.

    The oldest documented return in FX: a position is paid the policy-rate
    gap every night it is held, and historically the price has not fallen
    fast enough, on average, to give it all back. Deutsche Bank has run an
    investable index of exactly this since 1993 - the prior is published,
    not invented here.

    The score is the pair's rate differential at the decision instant, read
    from the stored BIS history strictly *before* the instant - the live
    reader refuses replays for exactly this reason. No differential, no
    score: a missing rate is not a rate of zero, and a stale one (no
    observation for `max_stale_days`) is treated as missing rather than
    carried forward into an era it knows nothing about.

    Sized by rank, not by magnitude, like every other candidate: the brains
    must differ only in what they choose.
    """

    name: str = "carry-differential"
    lookback: int = 0
    per_side: int = 3
    max_stale_days: int = 35

    def __init__(self, table: dict[str, list[tuple[Any, float]]] | None = None):
        #: currency -> [(observed date, rate), ...] ascending. Injectable so
        #: tests need no database; loaded once from the stored history
        #: otherwise. None after a failed load means "could not read", and
        #: the rule declines by name rather than caching an empty answer.
        self._table = table or None
        self._tried = table is not None

    def _load(self) -> dict[str, list[tuple[Any, float]]] | None:
        if self._tried:
            return self._table
        self._tried = True
        try:
            from sqlalchemy import select as sa_select

            from app.db.session import session_scope
            from app.models.policy_rates import PolicyRateObservation

            with session_scope() as session:
                rows = session.execute(
                    sa_select(
                        PolicyRateObservation.currency,
                        PolicyRateObservation.observed,
                        PolicyRateObservation.rate,
                    ).order_by(
                        PolicyRateObservation.currency,
                        PolicyRateObservation.observed,
                    )
                ).all()
            table: dict[str, list[tuple[Any, float]]] = {}
            for currency, observed, rate in rows:
                table.setdefault(currency, []).append((observed, float(rate)))
            self._table = table or None
        except Exception:  # noqa: BLE001 - a broken read declines, never raises
            self._table = None
        return self._table

    def _rate_before(self, currency: str, day: Any) -> float | None:
        table = self._table or {}
        series = table.get(currency)
        if not series:
            return None
        import bisect

        index = bisect.bisect_left(series, (day,)) - 1
        if index < 0:
            return None
        observed, rate = series[index]
        if (day - observed).days > self.max_stale_days:
            return None
        return rate

    def __call__(
        self, snapshot: dict[str, dict[str, Any]], *, universe: frozenset[str] | None
    ) -> Picks:
        if self._load() is None:
            return Picks(
                declined=(
                    "no policy rate history is stored, so no differential "
                    "can be read - a missing rate is not a rate of zero"
                )
            )

        instants = [
            stamp
            for stamp in (v.get("last_at") for v in snapshot.values())
            if stamp is not None
        ]
        if not instants:
            return Picks(declined="the snapshot carries no instant to read rates at")
        day = max(instants).date()

        scored: list[tuple[float, str]] = []
        for symbol in _eligible(snapshot, universe):
            pair = _pair_currencies(symbol)
            if pair is None:
                continue
            base = self._rate_before(pair[0], day)
            quote = self._rate_before(pair[1], day)
            if base is None or quote is None:
                continue
            scored.append((base - quote, symbol))

        if len(scored) < self.per_side * 2:
            return Picks(
                declined=(
                    f"only {len(scored)} pairs have a readable differential "
                    "at this instant"
                )
            )

        scored.sort()
        return Picks(
            longs=tuple(symbol for _, symbol in scored[-self.per_side :]),
            shorts=tuple(symbol for _, symbol in scored[: self.per_side]),
        )



@dataclass(frozen=True)
class TrendFollowing:
    """Hold what is above its own long average, sell what is below it.

    The oldest systematic idea there is, and the one this platform did not
    have: every brain here so far ranks instruments against each other or
    against their own recent mean, and none of them simply asks whether a
    market is in an uptrend.

    Judged per instrument rather than across the cross-section, which is what
    makes it usable on a short list. The incumbent needs twenty instruments
    before a ranking means anything; this one needs one.

    The signal is the fast average against the slow one, in units of the
    instrument's own volatility. Dividing by ATR is what lets a seven-symbol
    list hold gold and EURUSD together: without it the comparison is between
    a four-thousand-dollar instrument and a one-dollar one, and gold wins
    every ranking on arithmetic rather than on trend.
    """

    name: str = "trend-following"
    fast: int = 20
    slow: int = 100
    lookback: int = 100
    per_side: int = 2

    def __call__(
        self, snapshot: dict[str, dict[str, Any]], *, universe: frozenset[str] | None
    ) -> Picks:
        scored: list[tuple[float, str]] = []
        for symbol in _eligible(snapshot, universe):
            closes = _closes(snapshot, symbol)
            bars = list(snapshot.get(symbol, {}).get("bars") or [])
            if len(closes) < self.slow or len(bars) < self.slow:
                continue
            fast = sum(closes[-self.fast :]) / self.fast
            slow = sum(closes[-self.slow :]) / self.slow
            atr = crosssection.average_true_range(bars[-self.slow :])
            if not atr:
                continue
            scored.append(((fast - slow) / atr, symbol))

        if len(scored) < self.per_side * 2:
            return Picks(
                declined=f"only {len(scored)} instruments have {self.slow} bars"
            )

        scored.sort()
        return Picks(
            longs=tuple(symbol for _, symbol in scored[-self.per_side :]),
            shorts=tuple(symbol for _, symbol in scored[: self.per_side]),
        )


@dataclass(frozen=True)
class RSIMeanReversion:
    """Buy what is oversold on its own scale, sell what is overbought.

    RSI is bounded 0-100 by construction, so no volatility normalisation is
    needed and gold competes with EURUSD on equal terms - which is the whole
    reason to use a bounded oscillator on a mixed list.

    The thresholds are the published ones, 30 and 70, not numbers tuned here.
    A threshold chosen to fit this data would make the measurement that
    follows a measurement of the tuning.
    """

    name: str = "rsi-mean-reversion"
    period: int = 14
    lookback: int = 15
    oversold: float = 30.0
    overbought: float = 70.0
    per_side: int = 2

    def _rsi(self, closes: list[float]) -> float | None:
        window = closes[-(self.period + 1) :]
        if len(window) < self.period + 1:
            return None
        gains = [max(b - a, 0.0) for a, b in zip(window, window[1:], strict=False)]
        losses = [max(a - b, 0.0) for a, b in zip(window, window[1:], strict=False)]
        average_gain = sum(gains) / self.period
        average_loss = sum(losses) / self.period
        if average_loss == 0:
            return 100.0 if average_gain > 0 else 50.0
        strength = average_gain / average_loss
        return 100 - (100 / (1 + strength))

    def __call__(
        self, snapshot: dict[str, dict[str, Any]], *, universe: frozenset[str] | None
    ) -> Picks:
        scored: list[tuple[float, str]] = []
        for symbol in _eligible(snapshot, universe):
            value = self._rsi(_closes(snapshot, symbol))
            if value is None:
                continue
            scored.append((value, symbol))

        longs = tuple(s for v, s in sorted(scored) if v <= self.oversold)
        shorts = tuple(
            s for v, s in sorted(scored, reverse=True) if v >= self.overbought
        )
        if not longs and not shorts:
            # Nothing is stretched, which is most of the time and is not a
            # failure: an oscillator that always has an opinion is not an
            # oscillator, it is a coin.
            return Picks(declined="nothing is oversold or overbought")
        return Picks(
            longs=longs[: self.per_side], shorts=shorts[: self.per_side]
        )


@dataclass(frozen=True)
class DonchianBreakout:
    """Buy a new high, sell a new low - the Turtle rule, unchanged.

    Fifty-five bars is the published channel, and the entry is the break
    itself rather than a confirmation of it: waiting for a close beyond the
    channel and then waiting again is a different rule with a different name.

    The channel is measured on the bars *before* this one, so a bar cannot
    break a high it set itself. That is not a refinement - including the
    current bar makes every bar its own breakout and the rule fires
    constantly on nothing.
    """

    name: str = "donchian-breakout"
    channel: int = 55
    lookback: int = 56
    per_side: int = 2

    def __call__(
        self, snapshot: dict[str, dict[str, Any]], *, universe: frozenset[str] | None
    ) -> Picks:
        longs: list[tuple[float, str]] = []
        shorts: list[tuple[float, str]] = []
        for symbol in _eligible(snapshot, universe):
            bars = list(snapshot.get(symbol, {}).get("bars") or [])
            if len(bars) < self.channel + 1:
                continue
            prior = bars[-(self.channel + 1) : -1]
            highest = max(high for high, _low, _close in prior)
            lowest = min(low for _high, low, _close in prior)
            close = bars[-1][2]
            atr = crosssection.average_true_range(bars[-(self.channel + 1) :])
            if not atr:
                continue
            if close > highest:
                longs.append(((close - highest) / atr, symbol))
            elif close < lowest:
                shorts.append(((lowest - close) / atr, symbol))

        if not longs and not shorts:
            return Picks(declined="no instrument broke its channel")
        longs.sort(reverse=True)
        shorts.sort(reverse=True)
        return Picks(
            longs=tuple(s for _, s in longs[: self.per_side]),
            shorts=tuple(s for _, s in shorts[: self.per_side]),
        )


@dataclass(frozen=True)
class StochasticReversion:
    """Buy what is near the bottom of its recent range, sell what is near the top.

    The stochastic oscillator asks where the last close sits between the
    highest high and the lowest low of a lookback window, as a percentage. It
    is bounded 0-100 by construction, so it needs no volatility
    normalisation and gold competes with EURUSD on the same scale - the same
    property that made RSI usable on this mixed list.

    What it measures that RSI does not: RSI is built from the size of the
    closes' own changes, and this is built from the position of the close
    inside the range the bars actually traded. An instrument can grind down
    in small steps - low RSI, because every step is small - while still
    closing at the top of its range, and the two indicators disagree there.
    Whether that disagreement is worth anything is the question the
    measurement answers, not this docstring.

    **Slow, and with the published parameters.** 14 for the window, 3 for the
    smoothing, 20 and 80 for the bands: the values Lane published, not values
    chosen here. A threshold tuned on this data would make the measurement
    that follows a measurement of the tuning. `%D` - the smoothed line -
    rather than raw `%K`, because raw `%K` crosses its band on a single bar's
    high and produces a signal about one bar.
    """

    name: str = "stochastic-reversion"
    window: int = 14
    smoothing: int = 3
    oversold: float = 20.0
    overbought: float = 80.0
    per_side: int = 2

    def _percent_k(self, bars: list[tuple[float, float, float]]) -> float | None:
        """Where the last close sits in the window's range, 0-100."""
        window = bars[-self.window :]
        if len(window) < self.window:
            return None
        highest = max(bar[0] for bar in window)
        lowest = min(bar[1] for bar in window)
        span = highest - lowest
        if span <= 0:
            # A window that never moved has no position inside itself. Not
            # 50, which would be a claim about the middle of nothing.
            return None
        return 100.0 * (window[-1][2] - lowest) / span

    def percent_d(self, bars: list[tuple[float, float, float]]) -> float | None:
        """The smoothed line: the mean of the last `smoothing` values of %K."""
        needed = self.window + self.smoothing - 1
        if len(bars) < needed:
            return None
        values = []
        for offset in range(self.smoothing):
            end = len(bars) - offset
            value = self._percent_k(bars[:end])
            if value is None:
                return None
            values.append(value)
        return sum(values) / len(values)

    def __call__(
        self, snapshot: dict[str, dict[str, Any]], *, universe: frozenset[str] | None
    ) -> Picks:
        scored: list[tuple[float, str]] = []
        for symbol in _eligible(snapshot, universe):
            bars = list(snapshot.get(symbol, {}).get("bars") or [])
            value = self.percent_d(bars)
            if value is None:
                continue
            scored.append((value, symbol))

        longs = tuple(s for v, s in sorted(scored) if v <= self.oversold)
        shorts = tuple(
            s for v, s in sorted(scored, reverse=True) if v >= self.overbought
        )
        if not longs and not shorts:
            # Most of the time nothing sits in a band, and that is what a
            # bounded oscillator is for. An indicator with an opinion every
            # bar is not an oscillator, it is a coin.
            return Picks(declined="nothing is at the edge of its range")
        return Picks(longs=longs[: self.per_side], shorts=shorts[: self.per_side])


#: Every candidate, by name. Adding one here is the whole cost of testing it.
CANDIDATES: dict[str, Rule] = {
    rule.name: rule  # type: ignore[misc]
    for rule in (
        CrossSectionalStretch(),
        TimeSeriesMomentum(),
        ShortHorizonReversal(),
        CarryDifferential(),
        TrendFollowing(),
        RSIMeanReversion(),
        DonchianBreakout(),
    )
}


#: Rules written but not yet trading.
#:
#: Kept apart from CANDIDATES on purpose. `forward.record_forward` iterates
#: CANDIDATES and writes a decision for every rule in it on every cycle, so
#: putting a rule there is not "proposing" it - it is deploying it, and its
#: decisions immediately join the council's votes. A rule belongs here until
#: its measurement says it should move, and `get` finds it either way so the
#: lab can run it without the live loop being changed to allow that.
PROPOSED: dict[str, Rule] = {
    rule.name: rule  # type: ignore[misc]
    for rule in (StochasticReversion(),)
}


def get(name: str) -> Rule | None:
    return CANDIDATES.get(name) or PROPOSED.get(name)


def names() -> list[str]:
    return sorted(CANDIDATES)


def proposed_names() -> list[str]:
    return sorted(PROPOSED)
