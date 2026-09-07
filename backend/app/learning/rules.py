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

import bisect
import math
import statistics
from dataclasses import dataclass, field
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

    #: How strongly the rule wanted each pick, 0..1, by symbol.
    #:
    #: Called strength rather than conviction because
    #: `app.execution.conviction` already owns that word for something else -
    #: the multiplier that shrinks a permitted order at execution time. This
    #: is upstream of that and different in kind: it is what the rule saw,
    #: before any gate has had an opinion.
    #:
    #: Every rule here already computes a number to choose by - a return, a
    #: rate differential, an oscillator reading - and every one of them threw
    #: it away at the last step, leaving a set with no strength attached. The
    #: cost of that was not obvious: `app.brain.calibration` exists to measure
    #: whether a confidence behaves like a probability, and it had nothing to
    #: measure, so `calibrated` stayed false forever and the risk brain halved
    #: every order for it. A penalty the system cannot ever work off is not a
    #: penalty, it is a constant.
    #:
    #: **This is a strength, not a probability**, and the distinction is the
    #: whole point: calibration measures whether it deserves to be read as
    #: one. If a high strength wins no more often than a low one, that is a
    #: finding about the rule, and it can only be found once the number is
    #: written down.
    #:
    #: Empty when a rule has no natural strength to report. Absent is not
    #: 0.5 - a made-up middle would enter the reliability curve as evidence.
    scores: dict[str, float] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not self.longs and not self.shorts


class Rule(Protocol):
    """Sees a snapshot cut at the instant, names what it wants to hold."""

    name: str

    def __call__(
        self, snapshot: dict[str, dict[str, Any]], *, universe: frozenset[str] | None
    ) -> Picks: ...


def history_needed(rule: Rule | None) -> int:
    """How many bars this rule has to see before it can say anything.

    The harness used to cut every snapshot to a fixed 80 bars. Two rules in
    live service need more than that - `trend-following` compares a 100-bar
    average and `time-series-momentum` looks back 252 - so every instrument
    was skipped at every instant and both answered "no measurement: no
    instant in the window could be ranked" on every provider and every
    timeframe tried.

    They were trading the whole time. Twenty-six decisions each sat in the
    forward record from rules the apparatus that decides whether a rule has
    an edge could not see at all, which is the one combination this project
    exists to prevent.

    Read off the rule rather than configured, because a number kept in two
    places drifts and this is the number that decides whether a measurement
    happens.
    """
    if rule is None:
        return 0
    return max(
        int(getattr(rule, "lookback", 0) or 0) + 1,
        int(getattr(rule, "slow", 0) or 0),
        int(getattr(rule, "window", 0) or 0),
        int(getattr(rule, "period", 0) or 0) + 1,
    )


def _closes(snapshot: dict[str, dict[str, Any]], symbol: str) -> list[float]:
    return list(snapshot.get(symbol, {}).get("closes") or [])


#: Where stretch strength saturates, in ATR.
#:
#: Two ATR from the cross-sectional mean is a wide move on any instrument on
#: any day. Named here rather than written at each use because the incumbent
#: is scored in two places - the rule and the forward recorder - and two
#: copies of a scale is two scales the moment one of them is edited.
STRETCH_FULL_AT = 2.0


def _tail_strength(
    scored: list[tuple[float, str]],
    *,
    picked: tuple[str, ...],
    strong_when_high: bool,
) -> dict[str, float]:
    """Where each pick sits in the cross-section it was chosen from, 0..1.

    Every rule below ranks a list and takes from one end. How far into that
    end a pick sits is the strength the rule already used and then discarded,
    so this recovers it rather than inventing anything.

    `strong_when_high` is the rule's own orientation and cannot be guessed
    from the list: momentum buys the top of the ranking and reversal buys the
    bottom, and reading the position without knowing which would report the
    weakest reversal pick as the strongest one - a number that is exactly
    backwards is worse for a measurement than no number at all.

    The extreme pick scores 1.0 and the median 0.5. A cross-section of one
    carries no position to report, so it reports nothing.
    """
    if len(scored) < 2:
        return {}
    ordered = sorted(value for value, _ in scored)
    last = len(ordered) - 1
    out: dict[str, float] = {}
    for value, symbol in scored:
        if symbol not in picked:
            continue
        # Fraction of the cross-section this value sits above. `bisect_left`
        # on ties puts equal values at the same place, so two instruments with
        # identical readings get identical strengths rather than an order
        # that came out of the sort.
        below = bisect.bisect_left(ordered, value)
        position = below / last
        out[symbol] = round(position if strong_when_high else 1.0 - position, 4)
    return out


def _strength(
    scored: list[tuple[float, str]],
    *,
    longs: tuple[str, ...],
    shorts: tuple[str, ...],
    buy_high: bool,
) -> dict[str, float]:
    """Conviction for both sides of one ranking.

    The two sides read the same ranking from opposite ends, so they need
    opposite orientations: a momentum short taken from the bottom of the list
    is a *strong* short, and scoring it by the long's orientation would record
    the rule's best short as its weakest signal.
    """
    return {
        **_tail_strength(scored, picked=longs, strong_when_high=buy_high),
        **_tail_strength(scored, picked=shorts, strong_when_high=not buy_high),
    }


def scaled_strength(
    magnitudes: dict[str, float], *, full_at: float
) -> dict[str, float]:
    """Conviction from a magnitude on a fixed scale, saturating at `full_at`.

    For rules whose picks are not ends of a shared ranking - a breakout is
    against its own channel, not against its peers - there is no position in
    a cross-section to read. Normalising by the strongest pick in the cycle
    would look like an answer and is not one: it makes the best pick of every
    cycle exactly 1.0, however weak the day was, and a forecast whose meaning
    moves from cycle to cycle cannot be calibrated against anything.

    So the scale is absolute and stated by the caller in the rule's own units.
    """
    if full_at <= 0:
        return {}
    return {
        symbol: strength_from(value, full_at=full_at)
        for symbol, value in magnitudes.items()
    }


def strength_from(value: float, *, full_at: float) -> float:
    """One magnitude on that same scale.

    The forward recorder scores the incumbent without going through the rule
    object, so it needs the scalar. Same function underneath, so the two
    cannot come to disagree about what a strength of 0.7 means.
    """
    return round(min(abs(value) / full_at, 1.0), 4)


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
            # Stretch is already in ATR units, which is an absolute scale and
            # the reason it is used directly. Two ATR from the mean is a wide
            # move on any instrument on any day, so that is where strength
            # saturates.
            scores=scaled_strength(
                {
                    pick.symbol: pick.stretch
                    for pick in (*ranked.longs, *ranked.shorts)
                },
                full_at=STRETCH_FULL_AT,
            ),
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
        longs = tuple(symbol for _, symbol in scored[-self.per_side :])
        shorts = tuple(symbol for _, symbol in scored[: self.per_side])
        return Picks(
            longs=longs,
            shorts=shorts,
            scores=_strength(scored, longs=longs, shorts=shorts, buy_high=True),
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
        longs = tuple(symbol for _, symbol in scored[: self.per_side])
        shorts = tuple(symbol for _, symbol in scored[-self.per_side :])
        return Picks(
            longs=longs,
            shorts=shorts,
            # Buys what fell, so the bottom of the ranking is the strong end.
            scores=_strength(scored, longs=longs, shorts=shorts, buy_high=False),
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
        longs = tuple(symbol for _, symbol in scored[-self.per_side :])
        shorts = tuple(symbol for _, symbol in scored[: self.per_side])
        return Picks(
            longs=longs,
            shorts=shorts,
            scores=_strength(scored, longs=longs, shorts=shorts, buy_high=True),
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
        longs = tuple(symbol for _, symbol in scored[-self.per_side :])
        shorts = tuple(symbol for _, symbol in scored[: self.per_side])
        return Picks(
            longs=longs,
            shorts=shorts,
            scores=_strength(scored, longs=longs, shorts=shorts, buy_high=True),
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
        kept_longs = longs[: self.per_side]
        kept_shorts = shorts[: self.per_side]
        return Picks(
            longs=kept_longs,
            shorts=kept_shorts,
            # An oscillator buys the bottom of its own range, so the low end
            # is the strong end for a long. Position is read against every
            # instrument that had a reading, not only the ones that crossed a
            # threshold: what calibration asks is how far into the tail this
            # pick sat, and a threshold is not the tail.
            scores=_strength(
                scored, longs=kept_longs, shorts=kept_shorts, buy_high=False
            ),
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
        kept = [*longs[: self.per_side], *shorts[: self.per_side]]
        return Picks(
            longs=tuple(s for _, s in longs[: self.per_side]),
            shorts=tuple(s for _, s in shorts[: self.per_side]),
            # A breakout is measured against its own channel, not against the
            # other instruments, so there is no cross-section to take a
            # position in. The distance past the channel in ATR is the
            # strength, and half an ATR beyond a 55-bar extreme is already a
            # decisive break - beyond that the rule is not more sure, the
            # instrument is just more volatile.
            scores=scaled_strength(
                {symbol: distance for distance, symbol in kept}, full_at=0.5
            ),
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
        kept_longs = longs[: self.per_side]
        kept_shorts = shorts[: self.per_side]
        return Picks(
            longs=kept_longs,
            shorts=kept_shorts,
            # An oscillator buys the bottom of its own range, so the low end
            # is the strong end for a long. Position is read against every
            # instrument that had a reading, not only the ones that crossed a
            # threshold: what calibration asks is how far into the tail this
            # pick sat, and a threshold is not the tail.
            scores=_strength(
                scored, longs=kept_longs, shorts=kept_shorts, buy_high=False
            ),
        )


#: Every candidate, by name. Adding one here is the whole cost of testing it.
@dataclass(frozen=True)
class SwingStructure:
    """Buy what has made a higher high and a higher low; sell the mirror.

    HYPOTHESIS: an instrument whose recent swing sits entirely above its
    previous one continues in that direction more often than chance, because
    the two conditions together say something a single extreme does not - a
    higher high alone is a spike, and a higher low alone is a pullback that
    held. Both at once is the definition traders have used for an uptrend for
    a century, and the point of this rule is to find out whether that
    definition survives a control.

    Market Structure is one of the three families in the brief with no
    representative here, and this is its plainest member: no indicator, no
    smoothing, no threshold. Two halves of a window, four numbers, one
    comparison.

    ENTRY   the recent half's highest high above the older half's, and the
            recent half's lowest low above the older half's -> long. Both
            below -> short. Anything else is not a structure and is skipped.
    EXIT    the harness geometry, as for every rule here: the stop and target
            live outside the rule, so the comparison is about the signal.
    RANK    the smaller of the two displacements, in ATR - a structure is only
            as decisive as its weaker half, and taking the larger would let a
            spike in the high carry a low that barely moved.

    EXPECTED FAILURE MODE: a range. Inside one the two halves swap leadership
    constantly, the rule flips side every few bars and pays the spread each
    time. If it fails it should fail hardest in the low-volatility slices,
    and `robustness.regime_segments` is where that will show.
    """

    name: str = "swing-structure"
    #: Bars in the window, split into two halves. Forty rather than a tuned
    #: number: it is two twenty-bar swings, and twenty is the span the
    #: ordinary description of swing structure uses.
    lookback: int = 40
    per_side: int = 2

    def __call__(
        self, snapshot: dict[str, dict[str, Any]], *, universe: frozenset[str] | None
    ) -> Picks:
        longs: list[tuple[float, str]] = []
        shorts: list[tuple[float, str]] = []
        half = self.lookback // 2
        for symbol in _eligible(snapshot, universe):
            bars = list(snapshot.get(symbol, {}).get("bars") or [])
            if len(bars) < self.lookback:
                continue
            window = bars[-self.lookback :]
            older, recent = window[:half], window[half:]
            atr = crosssection.average_true_range(window)
            if not atr:
                continue
            high_shift = max(h for h, _l, _c in recent) - max(h for h, _l, _c in older)
            low_shift = min(low for _h, low, _c in recent) - min(
                low for _h, low, _c in older
            )
            if high_shift > 0 and low_shift > 0:
                longs.append((min(high_shift, low_shift) / atr, symbol))
            elif high_shift < 0 and low_shift < 0:
                shorts.append((min(-high_shift, -low_shift) / atr, symbol))

        if not longs and not shorts:
            return Picks(declined="no instrument had a shifted swing")
        longs.sort(reverse=True)
        shorts.sort(reverse=True)
        kept = [*longs[: self.per_side], *shorts[: self.per_side]]
        return Picks(
            longs=tuple(sym for _, sym in longs[: self.per_side]),
            shorts=tuple(sym for _, sym in shorts[: self.per_side]),
            # Measured against its own history, not against the other
            # instruments, so there is no shared ranking to take a position
            # in. Half an ATR of shift in both the high and the low is
            # already a decisive structure; past that the instrument is only
            # more volatile.
            scores=scaled_strength({sym: size for size, sym in kept}, full_at=0.5),
        )


@dataclass(frozen=True)
class VolatilityExpansion:
    """Follow the close of a bar that traded far wider than its neighbours.

    HYPOTHESIS: when one bar's range is a large multiple of the recent
    average, something arrived - and where that bar closed inside its own
    range says which side won the argument. A wide bar closing on its high is
    a different event from a wide bar closing in its middle, and the second
    is not a signal at all.

    Volatility is the second family the brief names with no representative
    here. This is its expansion half; contraction is a different hypothesis
    and gets its own rule rather than a parameter on this one.

    ENTRY   the bar's range at least `expansion` times the preceding ATR, and
            its close within the top or bottom `tail` of that range.
    RANK    how far past the threshold the expansion went, in ATR.

    Why the close's position and not the direction of the move: a bar can
    open with a gap, travel the other way for hours and still close above its
    open. Where it closed inside the range it actually traded is a fact about
    that bar; the open is a fact about the one before it.

    EXPECTED FAILURE MODE: scheduled news. If this works at all it should
    work at the release hours and not otherwise, which is what
    `robustness.by_hour` and `by_session` will say - and §18 of the brief
    becomes answerable rather than assumed.
    """

    name: str = "volatility-expansion"
    lookback: int = 20
    #: How many times the average range the bar must trade. Two, the ordinary
    #: textbook definition of a wide-range bar, not a value picked here.
    expansion: float = 2.0
    #: How near its own extreme the close must sit, as a share of the range.
    #: A third is the standard "closed in the top third" reading.
    tail: float = 1.0 / 3.0
    per_side: int = 2

    def __call__(
        self, snapshot: dict[str, dict[str, Any]], *, universe: frozenset[str] | None
    ) -> Picks:
        longs: list[tuple[float, str]] = []
        shorts: list[tuple[float, str]] = []
        for symbol in _eligible(snapshot, universe):
            bars = list(snapshot.get(symbol, {}).get("bars") or [])
            if len(bars) < self.lookback + 1:
                continue
            atr = crosssection.average_true_range(bars[-(self.lookback + 1) : -1])
            if not atr:
                continue
            high, low, close = bars[-1]
            span = high - low
            if span <= 0 or span < atr * self.expansion:
                continue
            position = (close - low) / span
            past = (span - atr * self.expansion) / atr
            if position >= 1.0 - self.tail:
                longs.append((past, symbol))
            elif position <= self.tail:
                shorts.append((past, symbol))

        if not longs and not shorts:
            return Picks(declined="no bar expanded and closed at its extreme")
        longs.sort(reverse=True)
        shorts.sort(reverse=True)
        kept = [*longs[: self.per_side], *shorts[: self.per_side]]
        return Picks(
            longs=tuple(sym for _, sym in longs[: self.per_side]),
            shorts=tuple(sym for _, sym in shorts[: self.per_side]),
            scores=scaled_strength({sym: size for size, sym in kept}, full_at=1.0),
        )


@dataclass(frozen=True)
class ResidualReversion:
    """Fade what moved away from what its peers did, not from its own past.

    HYPOTHESIS: most of any one pair's move over a few bars is the move the
    whole list made - the dollar, or risk appetite. What is left after
    subtracting that common move is the instrument's own, and that part
    reverts even where the raw price does not.

    **Not the same measurement as the incumbent, which is the reason it is
    here.** `cross-sectional-stretch` ranks each instrument by its distance
    from *its own* rolling mean; this ranks it by its distance from *what its
    peers did over the same bars*. A list drifting together is a large
    stretch on every member and a residual of zero on all of them, and the
    two readings disagree in exactly the case that matters - a common move,
    which is the one thing a mean-reversion rule must not fade.

    ENTRY   residual = the instrument's log return over `lookback` bars minus
            the cross-sectional mean of those returns. Buy the largest
            negative residuals, sell the largest positive ones.
    RANK    the residual in units of the cross-section's own dispersion, so a
            quiet list and a violent one are read on the same scale.

    EXPECTED FAILURE MODE: a genuine idiosyncratic repricing - a rate
    decision on one currency - is identical to a residual on the bar it
    happens, and fading it is the wrong side of a move that does not come
    back. If this fails it should fail on the days carrying those events.
    """

    name: str = "residual-reversion"
    lookback: int = 24
    per_side: int = 2

    def __call__(
        self, snapshot: dict[str, dict[str, Any]], *, universe: frozenset[str] | None
    ) -> Picks:
        returns: dict[str, float] = {}
        for symbol in _eligible(snapshot, universe):
            closes = _closes(snapshot, symbol)
            if len(closes) < self.lookback + 1:
                continue
            past, now = closes[-self.lookback - 1], closes[-1]
            if past <= 0 or now <= 0:
                continue
            returns[symbol] = math.log(now / past)

        # Fewer than this and the "common move" is the average of a handful
        # of instruments, which is not a factor - it is noise with a mean.
        if len(returns) < crosssection.MIN_CROSS_SECTION:
            return Picks(declined=f"only {len(returns)} instruments could be returned")

        common = sum(returns.values()) / len(returns)
        residuals = {sym: value - common for sym, value in returns.items()}
        spread = statistics.pstdev(residuals.values())
        if not spread:
            return Picks(declined="every residual is identical")

        scored = sorted((value / spread, sym) for sym, value in residuals.items())
        longs = tuple(sym for _, sym in scored[: self.per_side])
        shorts = tuple(sym for _, sym in scored[-self.per_side :])
        return Picks(
            longs=longs,
            shorts=shorts,
            # Buy the low end: this is a reversion rule, so the ranking runs
            # the opposite way to a momentum one and `buy_high` says so.
            scores=_strength(scored, longs=longs, shorts=shorts, buy_high=False),
        )


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
        # Moved from PROPOSED on 2026-09-03, after the measurement rather
        # than before it: +0.0991 R over its control at t = 4.90 on 21 years
        # of daily bars, p = 0.00025 against a sign-flipped null, and a block
        # bootstrap interval of [+0.0322, +0.1852] that clears zero - which
        # the incumbent's does not. Every one of the three periods is
        # positive and significant, where the incumbent's edge is carried by
        # three years out of twenty.
        #
        # It is still NOT_ROBUST by this project's own standard: 2025 is
        # negative and 2013 significantly so. It joins the council to vote
        # and to build its own forward record, which is what the registry
        # needs and what no amount of re-cutting history can supply.
        StochasticReversion(),
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
    for rule in (
        # Written 2026-09-08 for the three families the brief names that
        # had no representative at all: Market Structure, Volatility and
        # Statistical. Here rather than in CANDIDATES because CANDIDATES
        # is deployment - the forward loop writes a decision for
        # everything in it on every cycle - and nothing has measured
        # these yet.
        SwingStructure(),
        VolatilityExpansion(),
        ResidualReversion(),
    )
}


def get(name: str) -> Rule | None:
    return CANDIDATES.get(name) or PROPOSED.get(name)


def names() -> list[str]:
    return sorted(CANDIDATES)


def proposed_names() -> list[str]:
    return sorted(PROPOSED)
