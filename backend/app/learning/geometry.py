"""Is there a stop distance where the edge is larger than collecting it?

The journal answers half the question and the account answers the other half,
and put together they say something the platform had never been asked:

    M15   1459 resolved   +0.108 R gross   55% win
    M5    1311 resolved   +0.079 R gross   54% win
    H1     467 resolved   -0.041 R gross   45% win

The edge is on the fast frames. The cost of entry is also on the fast frames,
because a 2.5x ATR stop is around forty pips at H1 and seven at M15 while the
spread and the fill wander four either way - noise against the first number
and most of the second. Measured against live quotes, entry on M15 costs 0.16
to 0.22 R against an edge of 0.108. The signal is real and smaller than the
price of collecting it, and that single sentence is the whole distance between
a journal showing 56% and an account showing 18%.

There is an obvious thing to try and it had never been tried: keep the fast
signal and widen the stop. Cost in R is spread over stop distance, so it falls
as the stop grows - four times the distance is a quarter of the cost. Whether
the *edge* survives being asked to sit through four times the noise is not
something anybody can reason their way to. It is a measurement, and this is it.

**The discipline matters more than the answer here.** A sweep across geometries
is precisely the machine for manufacturing a result that does not exist: try
twenty stops, keep the best, publish it. So the geometry is chosen on the
training window alone and reported on a window it never saw, the incumbent is
carried through both so the comparison has a floor, and a winner that only wins
in training is reported as a failure rather than quietly dropped. If the honest
answer is that no geometry clears its own cost, that is the finding.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.core.errors import ValidationFailedError
from app.learning import measure as measure_module
from app.workers.forward import STOP_MULTIPLE, TARGET_MULTIPLE

#: Stop distances to try, as multiples of ATR. The incumbent is in the list on
#: purpose: a sweep whose grid excludes the thing it is arguing against cannot
#: be read as a comparison.
STOP_MULTIPLES: tuple[float, ...] = (2.5, 5.0, 7.5, 10.0, 15.0)

#: Targets as multiples of the stop. Below one is a higher win rate bought with
#: a worse payoff and above one is the reverse; both are real designs and the
#: measurement is what says which this signal supports.
TARGET_MULTIPLES: tuple[float, ...] = (0.5, 1.0, 1.5, 2.0)

#: Fraction of the window used to choose. The rest is never looked at until a
#: geometry has already been picked.
TRAIN_FRACTION = 0.6

#: Fewest scored instants a fold may have before its number means anything.
MIN_INSTANTS = 60


@dataclass(frozen=True)
class Trial:
    """One geometry, scored on one window."""

    stop_multiple: float
    target_multiple: float
    instants: int
    trades: int
    gross_r: float
    cost_r: float
    t_statistic: float

    @property
    def net_r(self) -> float:
        """What is left after paying to get in.

        The number the account experiences, and the one the gross figure has
        been standing in for. A gross edge that does not clear its own cost is
        not a small edge, it is a loss with a flattering description.
        """
        return self.gross_r - self.cost_r

    def as_payload(self) -> dict[str, Any]:
        return {
            "stop_multiple": self.stop_multiple,
            "target_multiple": self.target_multiple,
            "instants": self.instants,
            "trades": self.trades,
            "gross_r": round(self.gross_r, 4),
            "cost_r": round(self.cost_r, 4),
            "net_r": round(self.net_r, 4),
            "t_statistic": round(self.t_statistic, 3),
        }


def cost_for(stop_multiple: float, *, cost_at_incumbent: float) -> float:
    """Entry cost in R at this stop, from the cost measured at the incumbent.

    Cost in R is the spread and the slippage divided by the stop distance, and
    the distance is the only term the geometry changes. So the cost scales
    inversely with the multiple - twice the stop is half the cost per R - and
    one measured number fixes the whole curve.

    Taken from live quotes rather than assumed, because the assumed constant
    in this package is a single round-trip figure that does not move with the
    stop, and the entire question here is what happens when the stop moves.
    """
    if stop_multiple <= 0:
        raise ValidationFailedError("a stop multiple must be positive")
    if cost_at_incumbent < 0:
        raise ValidationFailedError("entry cannot cost less than nothing")
    return cost_at_incumbent * (STOP_MULTIPLE / stop_multiple)


def split(
    series: dict[str, list[Any]], *, fraction: float = TRAIN_FRACTION
) -> tuple[datetime | None, datetime | None, datetime | None]:
    """The window's start, the cut, and its end.

    By time rather than by sample, and one cut for every instrument together.
    Splitting per instrument would put the same afternoon in one symbol's
    training set and another's test set, and the cross-sectional rule reads
    them at the same instant - so the test window would contain the answer to
    its own question.
    """
    stamps = sorted({bar.at for bars in series.values() for bar in bars})
    if not stamps:
        return None, None, None
    if not 0 < fraction < 1:
        raise ValidationFailedError("a split has to leave both sides something")
    cut = stamps[int(len(stamps) * fraction)]
    return stamps[0], cut, stamps[-1]


def _window(
    series: dict[str, list[Any]], start: datetime, end: datetime
) -> dict[str, list[Any]]:
    return {
        symbol: [bar for bar in bars if start <= bar.at <= end]
        for symbol, bars in series.items()
    }


def trial(
    series: dict[str, list[Any]],
    *,
    bar_interval: timedelta,
    stop_multiple: float,
    target_multiple: float,
    cost_at_incumbent: float,
    rule: Any = None,
) -> Trial:
    """Score one geometry over one window."""
    result = measure_module.measure(
        series,
        bar_interval=bar_interval,
        rule=rule,
        stop_multiple=stop_multiple,
        target_multiple=target_multiple,
    )
    return Trial(
        stop_multiple=stop_multiple,
        target_multiple=target_multiple,
        instants=result.instants,
        trades=result.trades,
        # The rule against its own control, which is what `edge_r` means here:
        # a coin flip on the same instrument at the same instant under the same
        # geometry. Comparing raw rule return across geometries would reward
        # whichever stop the market happened to suit.
        gross_r=result.edge_r,
        cost_r=cost_for(stop_multiple, cost_at_incumbent=cost_at_incumbent),
        t_statistic=result.t_statistic,
    )


@dataclass(frozen=True)
class Sweep:
    """What training chose, and what the held-out window said about it."""

    chosen: Trial | None
    confirmed: Trial | None
    incumbent_train: Trial | None
    incumbent_test: Trial | None
    train_window: tuple[datetime, datetime] | None
    test_window: tuple[datetime, datetime] | None
    trials: tuple[Trial, ...] = ()
    refusal: str = ""

    @property
    def survived(self) -> bool:
        """Whether the choice is worth acting on.

        Three conditions, and all of them are about the held-out window: the
        chosen geometry has to clear its own cost there, beat the incumbent
        there, and have been scored on enough instants there to mean anything.
        Winning in training is not on the list. That is the part a sweep
        produces for free.
        """
        if self.chosen is None or self.confirmed is None:
            return False
        if self.confirmed.instants < MIN_INSTANTS:
            return False
        if self.confirmed.net_r <= 0:
            return False
        if self.incumbent_test is None:
            return True
        return self.confirmed.net_r > self.incumbent_test.net_r

    def as_payload(self) -> dict[str, Any]:
        return {
            "survived": self.survived,
            "refusal": self.refusal,
            "chosen_in_training": self.chosen.as_payload() if self.chosen else None,
            "on_held_out_data": (
                self.confirmed.as_payload() if self.confirmed else None
            ),
            "incumbent_in_training": (
                self.incumbent_train.as_payload() if self.incumbent_train else None
            ),
            "incumbent_on_held_out_data": (
                self.incumbent_test.as_payload() if self.incumbent_test else None
            ),
            "train_window": (
                [w.isoformat() for w in self.train_window]
                if self.train_window
                else None
            ),
            "test_window": (
                [w.isoformat() for w in self.test_window] if self.test_window else None
            ),
            "every_trial_in_training": [t.as_payload() for t in self.trials],
            "note": (
                "the geometry was chosen on the training window alone and "
                "scored on a window it never saw. A geometry that wins only in "
                "training is reported as a failure here, because that is what "
                "a sweep produces when there is nothing to find"
            ),
        }


def sweep(
    series: dict[str, list[Any]],
    *,
    bar_interval: timedelta,
    cost_at_incumbent: float,
    rule: Any = None,
    stop_multiples: tuple[float, ...] = STOP_MULTIPLES,
    target_multiples: tuple[float, ...] = TARGET_MULTIPLES,
    fraction: float = TRAIN_FRACTION,
) -> Sweep:
    """Choose a geometry on the training window; report it on the held-out one."""
    start, cut, end = split(series, fraction=fraction)
    if start is None or cut is None or end is None:
        return Sweep(None, None, None, None, None, None, refusal="the series is empty")

    train = _window(series, start, cut)
    test = _window(series, cut, end)

    scored: list[Trial] = []
    for stop in stop_multiples:
        for target in target_multiples:
            attempt = trial(
                train,
                bar_interval=bar_interval,
                stop_multiple=stop,
                target_multiple=target,
                cost_at_incumbent=cost_at_incumbent,
                rule=rule,
            )
            # A geometry nobody could measure is not a geometry that failed,
            # and carrying it into the comparison would let a fold of four
            # instants win on noise.
            if attempt.instants >= MIN_INSTANTS:
                scored.append(attempt)

    incumbent_train = next(
        (
            t
            for t in scored
            if t.stop_multiple == STOP_MULTIPLE
            and t.target_multiple == TARGET_MULTIPLE
        ),
        None,
    )
    if not scored:
        return Sweep(
            None,
            None,
            incumbent_train,
            None,
            (start, cut),
            (cut, end),
            refusal=(
                f"no geometry was scored on {MIN_INSTANTS} instants or more in "
                "training, so there is nothing to choose between"
            ),
        )

    chosen = max(scored, key=lambda t: t.net_r)
    confirmed = trial(
        test,
        bar_interval=bar_interval,
        stop_multiple=chosen.stop_multiple,
        target_multiple=chosen.target_multiple,
        cost_at_incumbent=cost_at_incumbent,
        rule=rule,
    )
    incumbent_test = trial(
        test,
        bar_interval=bar_interval,
        stop_multiple=STOP_MULTIPLE,
        target_multiple=TARGET_MULTIPLE,
        cost_at_incumbent=cost_at_incumbent,
        rule=rule,
    )

    result = Sweep(
        chosen=chosen,
        confirmed=confirmed,
        incumbent_train=incumbent_train,
        incumbent_test=incumbent_test,
        train_window=(start, cut),
        test_window=(cut, end),
        trials=tuple(sorted(scored, key=lambda t: -t.net_r)),
    )
    if result.survived:
        return result

    # Said out loud rather than left to be inferred from a flag. The reason a
    # candidate failed is the finding, and "it won in training" is the most
    # common and most misleading way to fail.
    if confirmed.instants < MIN_INSTANTS:
        why = (
            f"the held-out window scored only {confirmed.instants} instants, "
            f"under the {MIN_INSTANTS} needed to mean anything"
        )
    elif confirmed.net_r <= 0:
        why = (
            f"the chosen geometry earned {chosen.net_r:+.4f} R net in training "
            f"and {confirmed.net_r:+.4f} R on data it had not seen - it does "
            "not clear its own cost of entry"
        )
    else:
        beaten = incumbent_test.net_r if incumbent_test else 0.0
        why = (
            f"the chosen geometry earned {confirmed.net_r:+.4f} R on held-out "
            f"data against the incumbent's {beaten:+.4f} R - it is not an "
            "improvement on what is already deployed"
        )
    return Sweep(
        chosen=chosen,
        confirmed=confirmed,
        incumbent_train=incumbent_train,
        incumbent_test=incumbent_test,
        train_window=(start, cut),
        test_window=(cut, end),
        trials=tuple(sorted(scored, key=lambda t: -t.net_r)),
        refusal=why,
    )


@dataclass(frozen=True)
class Stability:
    """The same question asked at several cuts, and what kept its answer.

    One train/test split is one draw. A geometry can clear its own cost on a
    held-out window because the window suited it, and nothing in a single
    split can tell that from an edge - the D1 and M1 runs both scored *better*
    out of sample than in training, which is the shape a favourable period
    makes and not the shape an edge makes.

    Rolling the cut forward asks the question again on a different eight
    years. A geometry that wins at every cut is not proof, but a geometry that
    wins at one cut and loses at the next has been read off the noise, and
    that is worth finding out before a live stop is widened by six times.
    """

    folds: tuple[Sweep, ...]
    #: How many folds each geometry won, keyed by (stop, target).
    tally: dict[tuple[float, float], int]

    @property
    def survivors(self) -> int:
        return sum(1 for f in self.folds if f.survived)

    @property
    def consistent(self) -> tuple[float, float] | None:
        """The geometry chosen at every fold, or None.

        Every fold, not most of them. A geometry that wins three cuts of five
        is a geometry whose case rests on which three, and answering that
        needs the folds nobody has run rather than a majority of the ones
        that happened to be convenient.
        """
        if not self.folds:
            return None
        for key, count in self.tally.items():
            if count == len(self.folds):
                return key
        return None

    def as_payload(self) -> dict[str, Any]:
        return {
            "folds": len(self.folds),
            "survived": self.survivors,
            "chosen_every_fold": list(self.consistent) if self.consistent else None,
            "how_often_each_geometry_was_chosen": {
                f"{stop}/{target}": count
                for (stop, target), count in sorted(
                    self.tally.items(), key=lambda item: -item[1]
                )
            },
            "per_fold": [f.as_payload() for f in self.folds],
            "note": (
                "a geometry that wins at one cut and loses at the next was "
                "read off the noise. Every fold has to choose it, not most"
            ),
        }


def stability(
    series: dict[str, list[Any]],
    *,
    bar_interval: timedelta,
    cost_at_incumbent: float,
    rule: Any = None,
    fractions: tuple[float, ...] = (0.5, 0.6, 0.7, 0.8),
) -> Stability:
    """Run the sweep at several cuts and report what held at all of them.

    Rolling origin rather than k folds: every test window is strictly after
    its training window, which is the only arrangement a trading rule may be
    scored under. Shuffled folds would train on next month and test on last,
    and would report an edge that is only hindsight.
    """
    folds: list[Sweep] = []
    tally: dict[tuple[float, float], int] = {}
    for fraction in fractions:
        result = sweep(
            series,
            bar_interval=bar_interval,
            cost_at_incumbent=cost_at_incumbent,
            rule=rule,
            fraction=fraction,
        )
        folds.append(result)
        if result.chosen is not None:
            key = (result.chosen.stop_multiple, result.chosen.target_multiple)
            tally[key] = tally.get(key, 0) + 1
    return Stability(folds=tuple(folds), tally=tally)


def main(argv: list[str] | None = None) -> int:
    """Run the sweep over a stored series and print what held up.

    A command for the same reason `measure` grew one: a result nobody can
    re-run is a result nobody can check.

        python -m app.learning.geometry --timeframe M15 --cost 0.19
        python -m app.learning.geometry --timeframe M5 --cost 0.16 --provider metatrader

    `--cost` is entry cost in R at the deployed stop, read off live quotes:
    spread plus the expert's deviation limit, over 2.5 ATR. It is required
    rather than defaulted because it is the number that decides whether any of
    this is worth trading, and a default would let somebody run the sweep
    without ever having measured what their own broker charges.
    """
    from app.learning.measure import _yield_to_the_serving_path

    _yield_to_the_serving_path()

    import argparse
    import json

    from app.core.enums import Timeframe
    from app.db.session import session_scope
    from app.learning.measure import load_series

    parser = argparse.ArgumentParser(
        description="Choose a geometry on the first part of a series, "
        "report it on the last."
    )
    parser.add_argument("--provider", default="metatrader")
    parser.add_argument("--timeframe", default="M15")
    parser.add_argument("--cost", type=float, required=True)
    parser.add_argument("--fraction", type=float, default=TRAIN_FRACTION)
    parser.add_argument("--rule", default=None)
    parser.add_argument(
        "--folds",
        action="store_true",
        help="roll the cut forward and report only what every fold chose",
    )
    args = parser.parse_args(argv)

    timeframe = Timeframe(args.timeframe)
    rule = None
    if args.rule:
        from app.learning import rules as rules_module

        rule = rules_module.get(args.rule)
        if rule is None:
            print(json.dumps({"refusal": f"no rule named {args.rule!r}"}, indent=2))
            return 2

    with session_scope() as session:
        series = load_series(
            session, provider_code=args.provider, timeframe=timeframe
        )

    if not series:
        print(
            json.dumps(
                {
                    "refusal": (
                        f"{args.provider} has stored no {args.timeframe} bars, so "
                        "there is nothing to measure"
                    )
                },
                indent=2,
            )
        )
        return 1

    if args.folds:
        rolled = stability(
            series,
            bar_interval=timeframe.delta,
            cost_at_incumbent=args.cost,
            rule=rule,
        )
        payload = rolled.as_payload()
        payload["provider"] = args.provider
        payload["timeframe"] = args.timeframe
        payload["symbols"] = len(series)
        payload["cost_at_incumbent"] = args.cost
        print(json.dumps(payload, indent=2))
        return 0 if rolled.consistent else 1

    result = sweep(
        series,
        bar_interval=timeframe.delta,
        cost_at_incumbent=args.cost,
        rule=rule,
        fraction=args.fraction,
    )
    payload = result.as_payload()
    payload["provider"] = args.provider
    payload["timeframe"] = args.timeframe
    payload["symbols"] = len(series)
    payload["cost_at_incumbent"] = args.cost
    print(json.dumps(payload, indent=2))
    return 0 if result.survived else 1


if __name__ == "__main__":  # pragma: no cover - a command, not a code path
    raise SystemExit(main())
