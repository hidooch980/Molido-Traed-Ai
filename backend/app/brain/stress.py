"""Risk of ruin and stress testing (spec phase 24, §24).

Every layer above this one reasons about a single trade: is the setup worth
taking, at what size, given what is already open. This layer asks the only
question that outlives any individual trade — *if the next twenty go badly, is
there still an account?*

The two are less related than intuition suggests. A strategy with a genuine
edge still destroys an account that sizes it wrongly: the edge decides where
the equity curve ends up, the size decides whether it survives the path there.
Ruin is a property of the path, and the path is where the account lives.

Five commitments hold this module together.

**A ruin probability computed from an imagined win rate is worse than no ruin
probability at all.** It is a percentage, it looks measured, and it is the
number an operator will quote back when arguing for a larger position. So
`risk_of_ruin` refuses unless the win rate came from a calibrated source with
enough resolved trades behind it — `available: false` and the reason, never a
plausible-looking figure. It refuses at the other end too: an answer smaller
than the estimator can resolve is reported as negligible, because a printed
0.0 is the most confident lie in the module.

**Uncorrelated is a measurement, and a measurement is a number.** Under stress,
positions that looked independent stop being independent; that is most of what
the word "stress" means. So correlation enters as a measured coefficient, never
as a flag a caller can set to assert independence into existence. Unmeasured
means 1.0 in *every* scenario, including the base case. And measuring it never
makes the worst case cheaper: when every stop fills on the same morning the
book loses the arithmetic sum of its stops, whatever the correlation was.
Correlation changes how often that morning arrives, not what it costs.

**The open book has three states.** Measured, partly measured, and not supplied
at all. The third is the most likely caller mistake and it used to collapse into
an empty book worth 0 R — the most permissive answer in the module, handed over
in silence. An unsupplied book now yields `survives: null`, never `cleared`.

**A stress case is built on the severe run, not the median one.** Half of all
horizons are worse than the median, which is a strange thing for a scenario
named "extreme" to be built on. Both runs are always reported; the two severe
scenarios project from the one-in-twenty.

**The answer is a size, and the size has to work.** A scenario that runs
through the drawdown ceiling also reports the per-trade risk at which it would
not, because "0.4% instead of 1%" is actionable where "blocked" is merely
frustrating — and re-running the scenario at that number returns `survives:
true`, which a suggestion sitting exactly on the failing boundary did not.
Risk already committed in open positions is held out of that division: stops
already in the market do not move when the next trade is sized smaller.

Four scenarios are run rather than one, and all four are reported — a report
showing only the failure hides how much margin the others had. And, as
everywhere else in this system: nothing here authorises anything. It projects,
and it refuses. Execution is phase 25 and does not exist.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.brain.risk import HardLimits
from app.core.enums import RiskVerdict

# Below this many resolved trades there is no win rate, only a handful of
# outcomes. Thirty is not a magic number; it is the point below which the
# standard error on a hit rate is wider than any edge worth trading.
MIN_TRADES_FOR_RUIN = 30

# The forward window the drawdown projection covers. Short on purpose: a
# projection over a thousand trades is a statement about the strategy, while
# the account is destroyed by the next twenty.
HORIZON_TRADES = 20
MAX_HORIZON_TRADES = 500

# The typical streak is the one more likely than not to occur in the horizon;
# the severe streak is the one-in-twenty. Both are always reported, because a
# drawdown is caused by the run that actually happened and not by the average
# run — and the severe scenarios *project* from the severe one.
TYPICAL_STREAK_P = 0.5
SEVERE_STREAK_P = 0.05

# Thresholds that turn a measurement into a reduction. None of them can turn a
# breach back into an approval.
RUIN_WARNING = 0.01
DRAWDOWN_WARNING = 0.10
DAILY_LOSS_WARNING = 0.20
MAX_CONCENTRATION_SHARE = 0.5

# Below this, ruin is reported as negligible rather than as a number. Two
# reasons, and the second matters more: `root ** units` underflows to an exact
# 0.0 once the account is a few hundred units deep, and long before that the
# figure is finer than the win rate underneath it — one standard error on a hit
# rate measured over a few hundred trades moves a 1e-20 ruin probability by ten
# orders of magnitude. Publishing it would be the same confident lie the
# `win_rate >= 1.0` refusal exists to prevent.
MIN_REPORTABLE_RUIN = 1e-12

# The suggested survivable size is shaded by this before it is published.
# Survival is a strict inequality, so the exact solution of "projected drawdown
# equals the remaining ceiling" is the largest size that still fails. A
# suggestion an operator cannot act on is worse than no suggestion.
SURVIVABLE_MARGIN = 0.99


# ------------------------------------------------------------------ open book


class _UnknownOpenBook:
    """The type of `UNKNOWN_OPEN_BOOK`; not instantiated anywhere else."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "UNKNOWN_OPEN_BOOK"


# The open book has three states, not two: measured (a list, possibly empty),
# partly measured (entries that are None), and never supplied. Defaulting the
# parameter to `[]` collapsed the third into the first and handed the most
# permissive answer in the module to the most common caller mistake, so the
# default is this instead and it can only tighten the result.
UNKNOWN_OPEN_BOOK = _UnknownOpenBook()

# A position whose risk could not be read is None, not 0.0. A stop at breakeven
# genuinely risks nothing and must stay distinguishable from one nobody
# measured.
OpenBook = Sequence[float | None] | _UnknownOpenBook

# Either the mean pairwise correlation of the open book, or the measured
# pairwise coefficients keyed by position index. None means unmeasured — which
# in this module is a correlation of 1.0, not a correlation of 0.
CorrelationInput = float | Mapping[tuple[int, int], float] | None


# ------------------------------------------------------------------ scenarios


@dataclass(frozen=True)
class StressScenario:
    """How much worse than measured history a scenario assumes things get.

    Multipliers on the measured behaviour rather than absolute figures. A fixed
    "assume a 15% drawdown" scenario says nothing useful about a strategy whose
    worst measured drawdown is 3%, and nothing frightening enough about one
    whose worst is 12%.
    """

    name: str
    # How much larger the average loss becomes — gaps, slippage and stops that
    # fill worse than they were placed.
    loss_multiplier: float
    # How far the hit rate degrades, in probability points. Negative.
    win_rate_delta: float
    # How far a *measured* correlation collapses toward 1. 0 leaves the book as
    # measured; 1 treats every open position as the same position.
    correlation_shock: float
    # Which losing run the projection is built on, expressed as its chance of
    # occurring inside the horizon. The mild scenarios describe the ordinary
    # path; the severe ones must describe the one-in-twenty, because half of
    # all horizons are worse than the median and a scenario named "extreme"
    # built on the median is a mild scenario wearing the name.
    streak_probability: float = TYPICAL_STREAK_P

    def shocked_win_rate(self, win_rate: float) -> float:
        return min(1.0, max(0.0, win_rate + self.win_rate_delta))

    def stressed_correlation(self, measured: float | None) -> float:
        """How correlated this scenario assumes the book is.

        Unmeasured is 1.0 in every scenario including the base case: assuming
        independence understates the worst day by exactly the amount that
        matters. A measured coefficient is collapsed the rest of the way toward
        1 in proportion to the shock, which is what a correlation shock is —
        diversification evaporating, not a new correlation appearing.

        A measured negative correlation is floored at 0. Under the liquidity
        events this module exists to survive, the hedge that was negative on
        Friday is the first thing to fail on Monday.
        """
        if measured is None:
            return 1.0
        rho = min(1.0, max(0.0, measured))
        return rho + self.correlation_shock * (1.0 - rho)


BASE = StressScenario(
    "base", loss_multiplier=1.0, win_rate_delta=0.0, correlation_shock=0.0
)
ADVERSE = StressScenario(
    "adverse", loss_multiplier=1.25, win_rate_delta=-0.05, correlation_shock=0.30
)
STRESS = StressScenario(
    "stress",
    loss_multiplier=1.5,
    win_rate_delta=-0.10,
    correlation_shock=0.60,
    streak_probability=SEVERE_STREAK_P,
)
# A correlation shock of 1.0 is not pessimism for its own sake. In every
# liquidity event on record, the diversification in a book evaporated on the
# same morning the book needed it. A scenario that stops short of that is not
# the extreme; it is a second stress case wearing the name.
EXTREME = StressScenario(
    "extreme",
    loss_multiplier=2.0,
    win_rate_delta=-0.20,
    correlation_shock=1.0,
    streak_probability=SEVERE_STREAK_P,
)

SCENARIOS: tuple[StressScenario, ...] = (BASE, ADVERSE, STRESS, EXTREME)


@dataclass(frozen=True)
class TradeHistory:
    """Measured outcomes — counts of trades that actually resolved.

    Deliberately not a backtest summary. A backtest produces the same fields
    and none of the evidence, and this module has no way to tell the two apart,
    so the distinction has to be enforced by whoever constructs this object.

    Frozen and validated at construction. Impossible counts — more wins than
    trades, a negative average loss — used to flow all the way through to a
    fabricated 0.0% drawdown with `survives: true`, which is the worst possible
    response to a corrupt trade table. They now fail loudly at the boundary,
    where the caller still knows which query produced them.
    """

    trades: int = 0
    wins: int = 0
    average_win_r: float | None = None
    average_loss_r: float | None = None
    # Whether phase 20 has certified the source of this win rate. Default False
    # because an uncalibrated history is the normal state of a young system.
    calibrated: bool = False

    def __post_init__(self) -> None:
        if self.trades < 0:
            raise ValueError(f"resolved trades cannot be negative, got {self.trades}")
        if self.wins < 0:
            raise ValueError(f"winning trades cannot be negative, got {self.wins}")
        if self.wins > self.trades:
            raise ValueError(
                f"{self.wins} wins out of {self.trades} resolved trades is not a hit "
                "rate above 1, it is a broken join"
            )
        if self.average_win_r is not None and self.average_win_r <= 0:
            raise ValueError(
                f"average win must be positive when measured, got {self.average_win_r}"
            )
        # Carried as a positive magnitude in R. A zero or negative average loss
        # divides into the ruin walk and the streak projection alike.
        if self.average_loss_r is not None and self.average_loss_r <= 0:
            raise ValueError(
                f"average loss must be a positive magnitude in R, got {self.average_loss_r}"
            )

    @property
    def win_rate(self) -> float | None:
        """None until the sample is large enough to mean something.

        Ten trades with six winners is not a 60% win rate; it is six winners.
        Returning 0.6 there is precisely the fabrication this module exists to
        prevent, so the property returns None and every consumer is forced by
        the type to say so out loud.
        """
        if self.trades < MIN_TRADES_FOR_RUIN:
            return None
        return self.wins / self.trades

    @property
    def payoff_ratio(self) -> float | None:
        """How many average losses one average win pays for.

        None rather than a default when either side is unmeasured: the ruin
        walk takes this as the size of an up-step, and a substituted 1.0 there
        is an assumption about the strategy dressed as an observation.
        """
        if self.average_win_r is None or self.average_loss_r is None:
            return None
        return self.average_win_r / self.average_loss_r


# ----------------------------------------------------------------- risk of ruin


@dataclass
class RuinEstimate:
    available: bool
    reason: str | None = None
    # True when the walk ran and landed below MIN_REPORTABLE_RUIN. That is a
    # different refusal from "we cannot estimate this": the sizing is fine and
    # the answer is simply finer than the sample can resolve. A caller must be
    # able to tell "too small to state" from "unknown".
    negligible: bool = False
    probability: float | None = None
    # True when the probability is 1.0 because the sequence has no edge, rather
    # than because the sizing is aggressive. The distinction matters: the first
    # is a statement about the strategy, the second about the position size,
    # and only the second can be fixed by trading smaller.
    certain: bool = False
    win_rate: float | None = None
    payoff_ratio: float | None = None
    units: float | None = None
    trades_observed: int = 0
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        if not self.available:
            payload: dict[str, Any] = {"available": False, "reason": self.reason}
            if self.negligible:
                payload.update(
                    negligible=True,
                    below=MIN_REPORTABLE_RUIN,
                    win_rate=self.win_rate,
                    payoff_ratio=self.payoff_ratio,
                    units_of_capital=self.units,
                    trades_observed=self.trades_observed,
                )
            return payload
        return {
            "available": True,
            "probability": self.probability,
            "certain": self.certain,
            "win_rate": self.win_rate,
            "payoff_ratio": self.payoff_ratio,
            "units_of_capital": self.units,
            "trades_observed": self.trades_observed,
            "note": self.note,
        }


def _ruin_unavailable(reason: str, trades: int = 0) -> RuinEstimate:
    return RuinEstimate(available=False, reason=reason, trades_observed=trades)


def _ruin_root(win_rate: float, payoff_ratio: float) -> float:
    """The chance of ever being one unit lower than the current level.

    First-step analysis on a walk whose step distribution does not depend on
    where it is: from here, either the next trade loses the unit outright, or
    it wins `b` units and the walk must then give back `b + 1` — each of those
    give-backs being an independent copy of the same problem. Hence

        r = q + p · r^(b+1)

    r = 1 always satisfies that equation, which is the formal way of saying
    that a sequence without an edge reaches any drawdown eventually. The root
    worth having is the smaller one, and it exists only when p·b > q.
    """

    def f(r: float) -> float:
        return (1.0 - win_rate) + win_rate * r ** (payoff_ratio + 1.0) - r

    lo, hi = 1e-12, 1.0 - 1e-12
    for _ in range(100):
        mid = (lo + hi) / 2.0
        if f(mid) > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def risk_of_ruin(
    *,
    win_rate: float | None,
    payoff_ratio: float | None,
    risk_fraction: float,
    average_loss_r: float | None,
    calibrated: bool,
    trades_observed: int,
    ruin_drawdown_pct: float = 1.0,
) -> RuinEstimate:
    """Probability of losing `ruin_drawdown_pct` of the account, ever.

    The walk steps down by *one average loss*, so the capital has to be counted
    in average losses too. `risk_fraction` is what one R costs as a fraction of
    equity and `average_loss_r` is how many R one losing trade costs, so the
    account is worth `ruin_drawdown_pct / (risk_fraction · average_loss_r)`
    steps. Counting it in R instead made three strategies whose average losses
    were 0.5 R, 1 R and 2 R return byte-identical ruin — and understated it
    precisely as a scenario grew harsher, since a harsher scenario is one whose
    steps are bigger.

    The refusals come first and they are the point of the function. A ruin
    figure derived from an uncalibrated or small-sample win rate is the single
    most dangerous number a trading system can display: it is precise, it is
    reassuring, and it is invented.
    """
    if not calibrated:
        return _ruin_unavailable(
            "win rate is not from a calibrated source — a ruin probability built "
            "on an assumed hit rate is invented precision",
            trades_observed,
        )
    if trades_observed < MIN_TRADES_FOR_RUIN:
        return _ruin_unavailable(
            f"{trades_observed} resolved trades, needs {MIN_TRADES_FOR_RUIN} before "
            "a win rate supports a ruin estimate",
            trades_observed,
        )
    if win_rate is None:
        return _ruin_unavailable("no measured win rate", trades_observed)
    if payoff_ratio is None or payoff_ratio <= 0:
        return _ruin_unavailable(
            "average win and average loss are not both measured", trades_observed
        )
    if average_loss_r is None or average_loss_r <= 0:
        return _ruin_unavailable(
            "average loss per trade is not measured — the walk has no step size",
            trades_observed,
        )
    if not 0.0 < risk_fraction <= 1.0:
        return _ruin_unavailable(
            "risk per trade must be a positive fraction of equity", trades_observed
        )
    if not 0.0 < ruin_drawdown_pct <= 1.0:
        return _ruin_unavailable(
            "ruin threshold must be a positive fraction of equity", trades_observed
        )
    if win_rate >= 1.0:
        # A sample that has never lost puts no bound on ruin. The formula would
        # happily return 0.0, which is the most confident lie available here.
        return _ruin_unavailable(
            "sample contains no losing trades — ruin cannot be bounded from it",
            trades_observed,
        )

    units = ruin_drawdown_pct / (risk_fraction * average_loss_r)
    edge = win_rate * payoff_ratio - (1.0 - win_rate)

    if edge <= 0:
        return RuinEstimate(
            available=True,
            probability=1.0,
            certain=True,
            win_rate=round(win_rate, 6),
            payoff_ratio=round(payoff_ratio, 6),
            units=round(units, 4),
            trades_observed=trades_observed,
            note="expectancy is not positive — ruin is certain given enough trades",
        )

    # In log space on purpose. `root ** units` underflows to an exact 0.0 at
    # ordinary sizes on a large account — 0.05% per trade was enough — and a
    # published 0.0 is a stronger claim than any sample here can support.
    log_probability = units * math.log(_ruin_root(win_rate, payoff_ratio))
    if log_probability < math.log(MIN_REPORTABLE_RUIN):
        return RuinEstimate(
            available=False,
            negligible=True,
            reason=(
                f"ruin is below {MIN_REPORTABLE_RUIN:g}, finer than a win rate measured "
                f"over {trades_observed} trades can resolve — negligible, not zero"
            ),
            win_rate=round(win_rate, 6),
            payoff_ratio=round(payoff_ratio, 6),
            units=round(units, 4),
            trades_observed=trades_observed,
        )

    return RuinEstimate(
        available=True,
        probability=min(1.0, math.exp(log_probability)),
        win_rate=round(win_rate, 6),
        payoff_ratio=round(payoff_ratio, 6),
        units=round(units, 4),
        trades_observed=trades_observed,
    )


# ------------------------------------------------------------------- streaks


def consecutive_loss_probability(win_rate: float, streak: int, trades: int) -> float | None:
    """Chance that a run of at least `streak` losses occurs within `trades` trades.

    Exact, by walking the distribution of the current run length rather than by
    the usual `q^streak · trades` shorthand. That shorthand double-counts
    overlapping runs and overshoots badly at the lengths that matter — which is
    the direction that quietly makes a book look more fragile than it is, and
    an estimate that is wrong in either direction is not worth having.

    Returns None for inputs that admit no answer, and 0.0 when a run simply
    cannot fit in the window. A caller must be able to tell those apart.
    """
    if not 0.0 <= win_rate <= 1.0:
        return None
    if streak <= 0 or trades <= 0:
        return None
    if streak > trades:
        return 0.0

    loss = 1.0 - win_rate
    # states[j] = probability of sitting on a run of exactly j losses without
    # ever having reached `streak`.
    states = [0.0] * streak
    states[0] = 1.0
    reached = 0.0

    for _ in range(trades):
        nxt = [0.0] * streak
        nxt[0] = math.fsum(states) * win_rate
        for j in range(streak - 1):
            nxt[j + 1] = states[j] * loss
        reached += states[streak - 1] * loss
        states = nxt

    return min(1.0, reached)


def _streak_at_probability(win_rate: float, trades: int, threshold: float) -> int:
    """Longest losing run whose chance of occurring in `trades` is at least `threshold`.

    Reported instead of an expected drawdown because the account is drawn down
    by the run that happened, not by the mean of the runs that could have.
    """
    if win_rate <= 0.0:
        return trades
    longest = 0
    for streak in range(1, trades + 1):
        probability = consecutive_loss_probability(win_rate, streak, trades)
        if probability is None or probability < threshold:
            break
        longest = streak
    return longest


def daily_loss_probability(
    *,
    win_rate: float,
    average_win_r: float,
    average_loss_r: float,
    trades_per_day: int,
    limit_r: float,
) -> float | None:
    """Chance that one day's trades reach the daily-loss limit.

    Taken over the exact binomial rather than by counting consecutive losses: a
    day is lost on its net result, and four losses scattered around two wins
    spend the limit just as thoroughly as four in a row.
    """
    if not 0.0 <= win_rate <= 1.0:
        return None
    if trades_per_day <= 0 or limit_r <= 0:
        return None
    # Both averages are magnitudes. A non-positive one is not a small win or a
    # small loss, it is a broken input, and it lands directly in the net below.
    if average_loss_r <= 0 or average_win_r <= 0:
        return None

    total = 0.0
    for losses in range(trades_per_day + 1):
        wins = trades_per_day - losses
        net = wins * average_win_r - losses * average_loss_r
        if net > -limit_r:
            continue
        total += math.comb(trades_per_day, losses) * win_rate**wins * (1.0 - win_rate) ** losses
    return min(1.0, total)


# -------------------------------------------------------------- concentration


@dataclass
class Concentration:
    """What the open book loses at once, and how much of it is one bet.

    `known` is the first thing a consumer must read. Everything else is None
    when it is False, so an unsupplied or partly measured book cannot be
    mistaken for a book that genuinely risks nothing.
    """

    known: bool
    reason: str | None = None
    positions: int | None = None
    total_risk_r: float | None = None
    # None rather than 0.0 when there are no positions: an empty book has no
    # concentration, which is not the same measurement as a perfectly spread one.
    largest_share: float | None = None
    herfindahl: float | None = None
    effective_positions: float | None = None
    # The arithmetic sum under the scenario's loss multiplier — what the book
    # costs if every stop fills on the same morning. This is the worst case and
    # the only one of the two figures that may be checked against a ceiling.
    worst_case_loss_r: float | None = None
    # The equicorrelation loss at the correlation actually used. Smaller than
    # the worst case whenever the book is measurably less than fully
    # correlated; it describes the ordinary bad day, not the ceiling.
    correlated_loss_r: float | None = None
    correlation_used: float | None = None
    correlation_measured: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "known": self.known,
            "reason": self.reason,
            "positions": self.positions,
            "total_risk_r": self.total_risk_r,
            "largest_share": self.largest_share,
            "herfindahl": self.herfindahl,
            "effective_positions": self.effective_positions,
            "worst_case_loss_r": self.worst_case_loss_r,
            "correlated_loss_r": self.correlated_loss_r,
            "correlation_used": self.correlation_used,
            "correlation_measured": self.correlation_measured,
        }


def mean_pairwise_correlation(
    positions: int, measured: CorrelationInput
) -> tuple[float | None, str | None]:
    """`(mean pairwise correlation, why it cannot be used)` — exactly one is None.

    A book is only as measured as its least measured pair, so a mapping with
    gaps is refused rather than averaged over the pairs that happen to be
    present: the average of the measured half is a number about a different
    book.
    """
    if measured is None:
        return None, (
            "correlation between open positions unmeasured — the book is stressed "
            "as a single position"
        )
    # bool is an int, and `correlations_measured=True` was exactly the flag
    # this parameter replaced. Naming it beats silently reading it as rho=1.
    if isinstance(measured, bool):
        return None, "correlation must be a measured coefficient, not a flag"
    if isinstance(measured, int | float):
        value = float(measured)
        if not -1.0 <= value <= 1.0:
            return None, f"{value} is not a correlation coefficient"
        return value, None

    pairs = {(i, j) for i in range(positions) for j in range(i + 1, positions)}
    found: dict[tuple[int, int], float] = {}
    for pair, value in measured.items():
        low, high = sorted(pair)
        if (low, high) not in pairs:
            return None, f"correlation supplied for {pair}, which is not a pair in this book"
        if not -1.0 <= value <= 1.0:
            return None, f"{value} is not a correlation coefficient (pair {pair})"
        found[(low, high)] = float(value)

    if len(found) < len(pairs):
        return None, (
            f"{len(pairs) - len(found)} of {len(pairs)} position pairs have no measured "
            "correlation — a partly measured book is stressed as a single position"
        )
    return math.fsum(found.values()) / len(found), None


def concentration(
    open_risk_r: OpenBook, *, correlation: float | None, loss_multiplier: float = 1.0
) -> Concentration:
    """What the open book loses at once, and how much of it is one bet.

    Two different losses, and the difference is the whole point. The worst case
    is the arithmetic sum: independent stops can all trigger on the same
    morning, and four independent 1 R positions lose 4 R when they do.
    Independence makes that morning rarer; it does not make it cheaper. The
    quadrature figure this module used to publish as the loss is the standard
    deviation of a sum of independent P&Ls, which is not a loss at all.

    `correlated_loss_r` is the standard equicorrelation form,
    sqrt((1-rho)·Σr² + rho·G²) — the shape of an ordinary bad day at the
    correlation supplied. A linear blend between quadrature and the sum sits
    below it at every rho by the concavity of sqrt, so it was permissive
    everywhere and most permissive in the middle, where real books live.
    """
    if isinstance(open_risk_r, _UnknownOpenBook):
        return Concentration(
            known=False,
            reason=(
                "open positions were not supplied — an unknown book is not an empty "
                "one, and survival cannot be assessed without it"
            ),
        )

    unmeasured = sum(1 for risk in open_risk_r if risk is None)
    if unmeasured:
        return Concentration(
            known=False,
            positions=len(open_risk_r),
            reason=(
                f"{unmeasured} of {len(open_risk_r)} open positions have no measured risk "
                "— survival cannot be assessed without them"
            ),
        )

    risks = [abs(risk) for risk in open_risk_r if risk is not None]
    gross = math.fsum(risks)
    rho = 1.0 if correlation is None else min(1.0, max(0.0, correlation))
    measured = correlation is not None

    if not risks or gross <= 0:
        # An empty book and a book of breakeven stops both genuinely lose
        # nothing and genuinely have no concentration. Both are measurements.
        return Concentration(
            known=True,
            positions=len(risks),
            total_risk_r=0.0,
            worst_case_loss_r=0.0,
            correlated_loss_r=0.0,
            correlation_used=rho,
            correlation_measured=measured,
        )

    sum_squares = math.fsum(risk * risk for risk in risks)
    hhi = sum_squares / (gross * gross)
    equicorrelated = math.sqrt((1.0 - rho) * sum_squares + rho * gross * gross)

    return Concentration(
        known=True,
        positions=len(risks),
        total_risk_r=round(gross, 6),
        largest_share=round(max(risks) / gross, 6),
        herfindahl=round(hhi, 6),
        effective_positions=round(1.0 / hhi, 4),
        worst_case_loss_r=round(gross * loss_multiplier, 6),
        correlated_loss_r=round(equicorrelated * loss_multiplier, 6),
        correlation_used=rho,
        correlation_measured=measured,
    )


# --------------------------------------------------------- scenario projection


def _floor_to(value: float, places: int) -> float:
    """Round *down*. Rounding a survivable size up is how it stops surviving."""
    scale = 10.0**places
    return math.floor(value * scale) / scale


@dataclass
class ScenarioResult:
    scenario: str
    verdict: RiskVerdict
    available: bool
    reason: str | None = None

    # Named "assumed" because they are the scenario's shocked figures, not
    # measurements: for EXTREME a measured 0.55 hit rate appears here as 0.35.
    # The report-level ruin publishes the measured values under `win_rate`, and
    # one payload must not carry two meanings under one name.
    assumed_win_rate: float | None = None
    assumed_average_loss_r: float | None = None

    typical_streak: int | None = None
    severe_streak: int | None = None
    # Which of the two the projection below was built on, and its probability.
    projection_streak: int | None = None
    projection_streak_probability: float | None = None
    streak_drawdown_r: float | None = None
    # Always reported, even when the projection runs on the typical streak, so
    # the one-in-twenty cost of every scenario is visible without re-running.
    severe_streak_drawdown_r: float | None = None

    open_book_known: bool = False
    open_book_loss_r: float | None = None
    open_book_correlated_loss_r: float | None = None

    projected_drawdown_r: float | None = None
    projected_drawdown_pct: float | None = None
    # None when the open book is unknown: the streak is only part of the
    # answer, and a scenario cannot be said to survive a book nobody supplied.
    survives: bool | None = None
    # The per-trade risk, as a fraction of equity, at which this scenario's
    # projected drawdown would fit inside the remaining ceiling — reported only
    # when the scenario does not survive. This module never suggests sizing up.
    survivable_r_value_pct: float | None = None
    drawdown_probability: float | None = None
    daily_loss_probability: float | None = None
    ruin: RuinEstimate | None = None
    concentration: Concentration | None = None
    breaches: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "verdict": self.verdict.value,
            "available": self.available,
            "reason": self.reason,
            "assumed_win_rate": self.assumed_win_rate,
            "assumed_average_loss_r": self.assumed_average_loss_r,
            "typical_streak": self.typical_streak,
            "severe_streak": self.severe_streak,
            "projection_streak": self.projection_streak,
            "projection_streak_probability": self.projection_streak_probability,
            "streak_drawdown_r": self.streak_drawdown_r,
            "severe_streak_drawdown_r": self.severe_streak_drawdown_r,
            "open_book_known": self.open_book_known,
            "open_book_loss_r": self.open_book_loss_r,
            "open_book_correlated_loss_r": self.open_book_correlated_loss_r,
            "projected_drawdown_r": self.projected_drawdown_r,
            "projected_drawdown_pct": self.projected_drawdown_pct,
            "survives": self.survives,
            "survivable_r_value_pct": self.survivable_r_value_pct,
            "drawdown_probability": self.drawdown_probability,
            "daily_loss_probability": self.daily_loss_probability,
            "risk_of_ruin": self.ruin.as_dict() if self.ruin else None,
            "concentration": self.concentration.as_dict() if self.concentration else None,
            "breaches": self.breaches,
            "warnings": self.warnings,
        }


def evaluate(
    scenario: StressScenario,
    *,
    history: TradeHistory,
    r_value_pct: float,
    open_risk_r: OpenBook = UNKNOWN_OPEN_BOOK,
    current_drawdown_pct: float = 0.0,
    horizon_trades: int = HORIZON_TRADES,
    trades_per_day: int | None = None,
    measured_correlation: CorrelationInput = None,
    hard: HardLimits | None = None,
) -> ScenarioResult:
    """Project one scenario onto the account and say whether it survives.

    `r_value_pct` is what one R costs as a fraction of equity — the number that
    converts a drawdown measured in R into a drawdown measured against the
    ceiling. Without it nothing here can be checked, so it is required rather
    than defaulted.

    A scenario that cannot be evaluated returns REDUCE, never APPROVE: a stress
    test that did not run is not a stress test that passed. So does a scenario
    whose open book is unknown — `survives` is null there, not true. Only a
    measured breach of the hard drawdown ceiling returns BLOCK, and no argument
    in this function can turn one back into an approval.
    """
    hard = hard or HardLimits()
    breaches: list[str] = []
    warnings: list[str] = []

    # Correlation is only a question once there are two positions to correlate;
    # a single position is fully "correlated" with itself under every scenario
    # and warning about it would be noise.
    rho: float | None = None
    if not isinstance(open_risk_r, _UnknownOpenBook) and len(open_risk_r) >= 2:
        rho, unusable = mean_pairwise_correlation(len(open_risk_r), measured_correlation)
        if unusable is not None:
            warnings.append(unusable)

    conc = concentration(
        open_risk_r,
        correlation=scenario.stressed_correlation(rho) if rho is not None else None,
        loss_multiplier=scenario.loss_multiplier,
    )
    if conc.reason is not None:
        warnings.append(conc.reason)
    if (
        conc.largest_share is not None
        and conc.effective_positions is not None
        and conc.largest_share > MAX_CONCENTRATION_SHARE
    ):
        warnings.append(
            f"{conc.largest_share:.0%} of open risk sits in one position — "
            f"{conc.effective_positions:.1f} effective positions, not {conc.positions}"
        )

    def refuse(reason: str) -> ScenarioResult:
        return ScenarioResult(
            scenario=scenario.name,
            verdict=RiskVerdict.BLOCK if breaches else RiskVerdict.REDUCE,
            available=False,
            reason=reason,
            open_book_known=conc.known,
            open_book_loss_r=conc.worst_case_loss_r,
            open_book_correlated_loss_r=conc.correlated_loss_r,
            concentration=conc,
            breaches=breaches,
            warnings=warnings,
        )

    if not 0.0 < r_value_pct <= 1.0:
        return refuse("one R must be a positive fraction of equity to be compared to a ceiling")
    # Every other invalid input in this module is refused with a reason. A
    # horizon of 0 used to be rewritten to 1, which yields a streak of 0 and a
    # 0.0% projected drawdown that survives everything.
    if not 0 < horizon_trades <= MAX_HORIZON_TRADES:
        return refuse(
            f"horizon must be between 1 and {MAX_HORIZON_TRADES} trades, got {horizon_trades}"
        )
    if not 0.0 <= current_drawdown_pct < 1.0:
        return refuse("current drawdown must be a fraction of equity between 0 and 1")

    ceiling = hard.max_total_drawdown_pct
    remaining = ceiling - current_drawdown_pct

    if remaining <= 0:
        breaches.append(f"already at the {ceiling:.0%} drawdown ceiling before any stress")
    # Checked before the history is consulted, because the open book's shocked
    # loss is a fact about the positions rather than a projection from past
    # performance. If it alone runs through the ceiling, nothing measured later
    # can rescue the scenario.
    elif conc.worst_case_loss_r is not None:
        open_loss_pct = conc.worst_case_loss_r * r_value_pct
        if open_loss_pct >= remaining:
            breaches.append(
                f"open positions alone lose {open_loss_pct:.1%} under {scenario.name} if "
                f"every stop fills, against {remaining:.1%} of remaining ceiling"
            )

    win_rate = history.win_rate
    average_loss = history.average_loss_r
    if win_rate is None or average_loss is None:
        return refuse(
            f"{history.trades} resolved trades, needs {MIN_TRADES_FOR_RUIN} before a "
            "win rate means anything"
            if win_rate is None
            else "average loss per trade is not measured"
        )

    payoff = history.payoff_ratio
    if payoff is not None and payoff * win_rate <= (1.0 - win_rate):
        warnings.append(
            "measured expectancy is not positive — no position size makes this survivable"
        )

    assumed_win_rate = scenario.shocked_win_rate(win_rate)
    assumed_loss_r = average_loss * scenario.loss_multiplier

    typical = _streak_at_probability(assumed_win_rate, horizon_trades, TYPICAL_STREAK_P)
    severe = _streak_at_probability(assumed_win_rate, horizon_trades, SEVERE_STREAK_P)
    projection_streak = _streak_at_probability(
        assumed_win_rate, horizon_trades, scenario.streak_probability
    )

    streak_drawdown_r = projection_streak * assumed_loss_r
    streak_pct = streak_drawdown_r * r_value_pct

    open_worst_r = conc.worst_case_loss_r
    projected_r: float | None
    projected_pct: float | None
    survives: bool | None
    if open_worst_r is None:
        projected_r = None
        projected_pct = None
        # The streak alone is a floor, so it can still condemn the scenario —
        # uncertainty may tighten the answer, never loosen it — but it can
        # never clear one.
        survives = False if streak_pct >= remaining else None
    else:
        projected_r = streak_drawdown_r + open_worst_r
        projected_pct = projected_r * r_value_pct
        survives = projected_pct < remaining

    if survives is False and remaining > 0:
        if projected_pct is not None and projected_r is not None:
            breaches.append(
                f"{scenario.name} projects a {projected_pct:.1%} drawdown "
                f"({projected_r:.1f} R) against {remaining:.1%} of remaining ceiling"
            )
        else:
            breaches.append(
                f"{scenario.name} projects at least a {streak_pct:.1%} drawdown "
                f"({streak_drawdown_r:.1f} R) from the losing run alone, against "
                f"{remaining:.1%} of remaining ceiling"
            )

    # The streak that would take the account through what is left of the
    # ceiling, and how likely such a streak is inside the horizon. This is the
    # spec's drawdown probability, and it is a finite-horizon question — unlike
    # ruin, which asks what happens eventually.
    committed_r = open_worst_r if open_worst_r is not None else 0.0
    room_r = remaining / r_value_pct - committed_r
    if room_r <= 0:
        probability_floor: float | None = 1.0
    else:
        needed = math.ceil(room_r / assumed_loss_r)
        probability_floor = consecutive_loss_probability(
            assumed_win_rate, needed, horizon_trades
        )
    if probability_floor is not None and probability_floor >= DRAWDOWN_WARNING:
        qualifier = "" if conc.known else " counting the losing run alone"
        warnings.append(
            f"{probability_floor:.0%} chance of reaching the drawdown ceiling within "
            f"{horizon_trades} trades under {scenario.name}{qualifier}"
        )
    # Published only when the book behind it is known. With an unknown book the
    # figure omits the open positions entirely, which makes it a lower bound —
    # fine for raising the warning above, not fine as an answer.
    drawdown_probability = probability_floor if conc.known else None

    daily_probability: float | None = None
    average_win = history.average_win_r
    if trades_per_day is None:
        warnings.append("trades per day not measured — daily-loss risk not estimated")
    elif average_win is None:
        warnings.append("average win not measured — daily-loss risk not estimated")
    else:
        daily_probability = daily_loss_probability(
            win_rate=assumed_win_rate,
            average_win_r=average_win,
            average_loss_r=assumed_loss_r,
            trades_per_day=trades_per_day,
            limit_r=hard.max_daily_loss_r,
        )
        if daily_probability is not None and daily_probability >= DAILY_LOSS_WARNING:
            warnings.append(
                f"{daily_probability:.0%} chance of spending the "
                f"{hard.max_daily_loss_r:.0f} R daily loss limit under {scenario.name}"
            )

    ruin = risk_of_ruin(
        win_rate=assumed_win_rate,
        payoff_ratio=(
            average_win / assumed_loss_r if average_win is not None and average_win > 0 else None
        ),
        risk_fraction=r_value_pct,
        average_loss_r=assumed_loss_r,
        calibrated=history.calibrated,
        trades_observed=history.trades,
        # What is left to lose, not the whole account: an account already 9%
        # down has 91% of its capital in front of the walk, not 100%.
        ruin_drawdown_pct=1.0 - current_drawdown_pct,
    )
    # A certain ruin under a shocked scenario is a restatement of the shock,
    # not a finding, so it does not drive the verdict — the measured-expectancy
    # warning above covers the case where the strategy itself is the problem.
    if ruin.probability is not None and not ruin.certain and ruin.probability >= RUIN_WARNING:
        warnings.append(f"risk of ruin {ruin.probability:.1%} under {scenario.name}")

    # Only the streak scales with the per-trade size. The stops already in the
    # market do not move when the next trade is sized smaller, so the risk
    # committed to open positions is held out of the division; dividing the
    # whole projection by it was optimistic by exactly the open book.
    survivable: float | None = None
    if survives is False and open_worst_r is not None and streak_drawdown_r > 0:
        headroom = remaining - open_worst_r * r_value_pct
        if headroom > 0:
            survivable = _floor_to(headroom * SURVIVABLE_MARGIN / streak_drawdown_r, 6)
            if survivable <= 0:
                survivable = None
        if survivable is None:
            warnings.append(
                f"no per-trade size survives {scenario.name} — the risk already committed "
                "to open positions does not shrink with the next trade"
            )

    if breaches:
        verdict = RiskVerdict.BLOCK
    elif warnings or survives is None:
        verdict = RiskVerdict.REDUCE
    else:
        verdict = RiskVerdict.APPROVE

    return ScenarioResult(
        scenario=scenario.name,
        verdict=verdict,
        available=True,
        assumed_win_rate=round(assumed_win_rate, 6),
        assumed_average_loss_r=round(assumed_loss_r, 6),
        typical_streak=typical,
        severe_streak=severe,
        projection_streak=projection_streak,
        projection_streak_probability=scenario.streak_probability,
        streak_drawdown_r=round(streak_drawdown_r, 6),
        severe_streak_drawdown_r=round(severe * assumed_loss_r, 6),
        open_book_known=conc.known,
        open_book_loss_r=conc.worst_case_loss_r,
        open_book_correlated_loss_r=conc.correlated_loss_r,
        projected_drawdown_r=round(projected_r, 6) if projected_r is not None else None,
        projected_drawdown_pct=round(projected_pct, 6) if projected_pct is not None else None,
        survives=survives,
        survivable_r_value_pct=survivable,
        drawdown_probability=(
            round(drawdown_probability, 6) if drawdown_probability is not None else None
        ),
        daily_loss_probability=(
            round(daily_probability, 6) if daily_probability is not None else None
        ),
        ruin=ruin,
        concentration=conc,
        breaches=breaches,
        warnings=warnings,
    )


@dataclass
class StressReport:
    verdict: RiskVerdict
    # True only when every scenario ran, every one of them is known to survive,
    # and none of them breached. A REDUCE verdict with `cleared` true means
    # "survivable, trade smaller"; a REDUCE with `cleared` false means "we could
    # not tell", and the two must not be collapsed into one flag. An unknown
    # open book lands in the second, which is the whole reason `survives` is a
    # three-state field.
    cleared: bool
    scenarios: dict[str, ScenarioResult] = field(default_factory=dict)
    ruin: RuinEstimate | None = None
    breaches: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "cleared": self.cleared,
            "risk_of_ruin": self.ruin.as_dict() if self.ruin else None,
            "breaches": self.breaches,
            "warnings": self.warnings,
            "scenarios": {name: r.as_dict() for name, r in self.scenarios.items()},
            # Stated on every response so no consumer can mistake a surviving
            # stress test for permission to place an order.
            "authorises_execution": False,
            "note": "execution engine is phase 25 and does not exist yet",
        }


_SEVERITY: dict[RiskVerdict, int] = {
    RiskVerdict.APPROVE: 0,
    RiskVerdict.REDUCE: 1,
    RiskVerdict.BLOCK: 2,
}


def run_all(
    *,
    history: TradeHistory,
    r_value_pct: float,
    open_risk_r: OpenBook = UNKNOWN_OPEN_BOOK,
    current_drawdown_pct: float = 0.0,
    horizon_trades: int = HORIZON_TRADES,
    trades_per_day: int | None = None,
    measured_correlation: CorrelationInput = None,
    hard: HardLimits | None = None,
    scenarios: tuple[StressScenario, ...] = SCENARIOS,
) -> StressReport:
    """Run every scenario; return the worst verdict and all of the detail.

    The passing scenarios are returned alongside the failing one on purpose. A
    report that shows only the breach hides whether the account cleared the
    others comfortably or by a hair, and that margin is most of what an
    operator needs in order to act on the answer.
    """
    results = {
        scenario.name: evaluate(
            scenario,
            history=history,
            r_value_pct=r_value_pct,
            open_risk_r=open_risk_r,
            current_drawdown_pct=current_drawdown_pct,
            horizon_trades=horizon_trades,
            trades_per_day=trades_per_day,
            measured_correlation=measured_correlation,
            hard=hard,
        )
        for scenario in scenarios
    }

    worst = RiskVerdict.APPROVE
    for result in results.values():
        if _SEVERITY[result.verdict] > _SEVERITY[worst]:
            worst = result.verdict

    breaches = [f"{name}: {b}" for name, r in results.items() for b in r.breaches]
    warnings = [f"{name}: {w}" for name, r in results.items() for w in r.warnings]

    # Reported from the measured history rather than from any scenario: ruin is
    # a property of the strategy and its sizing, and a version of it computed
    # under a hypothetical shock answers a question nobody asked.
    ruin = risk_of_ruin(
        win_rate=history.win_rate,
        payoff_ratio=history.payoff_ratio,
        risk_fraction=r_value_pct,
        average_loss_r=history.average_loss_r,
        calibrated=history.calibrated,
        trades_observed=history.trades,
        ruin_drawdown_pct=1.0 - current_drawdown_pct,
    )

    return StressReport(
        verdict=worst,
        cleared=(
            all(r.available and r.survives is True for r in results.values())
            and not breaches
        ),
        scenarios=results,
        ruin=ruin,
        breaches=breaches,
        warnings=warnings,
    )
