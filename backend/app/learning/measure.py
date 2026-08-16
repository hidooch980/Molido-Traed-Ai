"""Run the cross-sectional rule over a stored series and report the result.

This should have existed from the start. The number the whole project turns on
- +0.0212 R over a random control at t = 3.69 - was produced by a script that
no longer exists, which means the single most consequential figure here could
not be reproduced from this repository. A result nobody can re-run is a result
nobody can check, including the person who produced it.

Everything that decides the answer is imported rather than restated:

    ranking      app.brain.crosssection.rank
    geometry     app.workers.forward.STOP_MULTIPLE, TARGET_MULTIPLE
    resolution   app.workers.resolve._outcome, HORIZON
    control      app.learning.control.entry_for

A historical measurement scored under its own copy of those constants is not a
comparison with the forward series, it is a second unrelated measurement
wearing the same name. Copying any of them here to "keep this module
self-contained" would break the only property that makes the two numbers
comparable.

**Clustering is not optional and not a refinement.** The rule opens both tails
at every instant, so the trades inside one instant are one market move seen
from several angles. Counting them as independent evidence inflated the daily
significance figure from -0.12 to 3.95 in the original work - a factor of
thirty-two, and in the direction that manufactures a discovery. So the unit of
evidence is the instant: every instant contributes one number, the mean R of
everything opened then, rule minus control.

**The result is paired.** Rule and control run on the same instants with the
same geometry, so the difference removes the common market factor. An unpaired
comparison of two arms that saw the same bars overstates the variance and
understates the edge - the direction to be wrong in, but wrong.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.brain import crosssection
from app.learning import control as control_module
from app.workers.forward import STOP_MULTIPLE, TARGET_MULTIPLE
from app.workers.resolve import HORIZON, _outcome

#: Round-trip cost in R, the same figure the edge registry charges. Subtracted
#: from the edge rather than from the rule alone: the control pays it too, and
#: charging one arm and not the other invents an edge worth exactly the cost.
COST_R = 0.01


@dataclass(frozen=True)
class Bar:
    """One bar of a stored series."""

    at: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class Measurement:
    """What the rule did over a window, clustered by instant."""

    instants: int
    trades: int
    rule_r: float
    control_r: float
    spread_r: float
    t_statistic: float
    unclustered_t: float
    dropped_undecided: int
    window: tuple[datetime, datetime] | None

    @property
    def edge_r(self) -> float:
        return self.rule_r - self.control_r

    @property
    def net_r(self) -> float:
        return self.edge_r - COST_R

    @property
    def significant(self) -> bool:
        return abs(self.t_statistic) >= 1.96

    def as_dict(self) -> dict[str, Any]:
        return {
            # The unit of evidence, stated first because every other number
            # here is meaningless without knowing which one it counts.
            "instants": self.instants,
            "trades": self.trades,
            "trades_per_instant": (
                round(self.trades / self.instants, 2) if self.instants else None
            ),
            "rule_r": round(self.rule_r, 4),
            "control_r": round(self.control_r, 4),
            "edge_r": round(self.edge_r, 4),
            "net_of_costs_r": round(self.net_r, 4),
            "spread_r": round(self.spread_r, 4),
            "t": round(self.t_statistic, 2),
            "required_t": 1.96,
            "significant": self.significant,
            # Published so the inflation is visible rather than merely
            # corrected for. In the original work these were -0.12 and 3.95.
            "unclustered_t": round(self.unclustered_t, 2),
            "clustering_inflation": (
                round(abs(self.unclustered_t / self.t_statistic), 1)
                if self.t_statistic
                else None
            ),
            "dropped_undecided": self.dropped_undecided,
            "window": (
                [self.window[0].isoformat(), self.window[1].isoformat()]
                if self.window
                else None
            ),
            "geometry": {
                "stop_multiple": STOP_MULTIPLE,
                "target_multiple": TARGET_MULTIPLE,
                "horizon_bars": HORIZON,
                "cost_r": COST_R,
            },
            "note": (
                "one instant is one observation. The rule opens both tails at "
                "every instant, so the trades inside one are one market move "
                "seen from several angles - counting them as independent "
                "evidence inflated the original daily figure from -0.12 to "
                "3.95, in the direction that manufactures a discovery"
            ),
        }


def _resolve(
    series: Sequence[Bar],
    index: int,
    *,
    side: int,
    entry: float,
    stop: float,
    target: float,
) -> float | None:
    """What the bars after `index` did to this entry, in R.

    Strictly after: the entry bar's own high and low say nothing about what
    happened next, and using them is lookahead wearing the costume of a fill.
    Shares `_outcome` with the live resolver so the two cannot drift.
    """
    window = series[index + 1 : index + 1 + HORIZON]
    if not window:
        return None
    verdict = _outcome(
        list(window), side=side, entry=entry, stop=stop, target=target
    )
    return None if verdict is None else verdict[1]


def measure(
    series: dict[str, list[Bar]],
    *,
    bar_interval: timedelta,
    min_history: int = 80,
    universe: frozenset[str] | None = crosssection.RANKED_UNIVERSE,
) -> Measurement:
    """Walk every instant in a stored series and score both arms.

    `series` maps a symbol to its bars, ascending. Every instrument is cut at
    the instant being decided on, never at the end of the series - the same
    point-in-time rule the live recorder follows, and the one whose absence
    would flatter every result here silently.
    """
    index_of: dict[str, dict[datetime, int]] = {
        symbol: {bar.at: i for i, bar in enumerate(bars)}
        for symbol, bars in series.items()
    }

    instants = sorted({bar.at for bars in series.values() for bar in bars})

    rule_by_instant: list[float] = []
    control_by_instant: list[float] = []
    per_trade: list[float] = []
    trades = 0
    dropped = 0

    for moment in instants:
        snapshot: dict[str, dict[str, Any]] = {}
        for symbol, bars in series.items():
            position = index_of[symbol].get(moment)
            if position is None or position < min_history:
                continue
            # Cut at the instant, not at the end. A window that reaches past
            # the moment being decided on puts future prices into the mean and
            # into the ATR, and the whole result becomes a measurement of that.
            window = bars[position - min_history + 1 : position + 1]
            snapshot[symbol] = {
                "closes": [b.close for b in window],
                "bars": [(b.high, b.low, b.close) for b in window],
                "last_at": window[-1].at,
            }

        if len(snapshot) < crosssection.MIN_CROSS_SECTION:
            continue

        ranked = crosssection.rank(
            snapshot, at=moment, bar_interval=bar_interval, universe=universe
        )
        if not ranked.available:
            continue

        rule_here: list[float] = []
        control_here: list[float] = []

        for picks, side_name in ((ranked.longs, "long"), (ranked.shorts, "short")):
            side = 1 if side_name == "long" else -1
            for pick in picks:
                position = index_of[pick.symbol][moment]
                bars = series[pick.symbol]
                distance = pick.atr * STOP_MULTIPLE

                outcome = _resolve(
                    bars,
                    position,
                    side=side,
                    entry=pick.price,
                    stop=pick.price - distance * side,
                    target=pick.price + distance * TARGET_MULTIPLE * side,
                )

                entry = control_module.entry_for(
                    symbol=pick.symbol,
                    at=moment,
                    price=pick.price,
                    stop_distance=distance,
                    target_multiple=TARGET_MULTIPLE,
                )
                control_outcome = (
                    None
                    if entry is None
                    else _resolve(
                        bars,
                        position,
                        side=entry.side,
                        entry=entry.entry,
                        stop=entry.stop,
                        target=entry.target,
                    )
                )

                if outcome is None or control_outcome is None:
                    # Either arm undecided drops the pair, not the arm. Keeping
                    # one side of a pair whose partner was dropped is a bias,
                    # and it is the bias that favours whichever arm resolves
                    # faster - which is the rule, because its geometry is the
                    # one the ranking chose.
                    dropped += 1
                    continue

                rule_here.append(outcome)
                control_here.append(control_outcome)
                per_trade.append(outcome - control_outcome)
                trades += 1

        if not rule_here:
            continue

        # One number per instant: the mean of everything opened then. This is
        # the clustering, and it is the difference between t = 3.95 and
        # t = -0.12 on the same trades.
        rule_by_instant.append(sum(rule_here) / len(rule_here))
        control_by_instant.append(sum(control_here) / len(control_here))

    return _summarise(
        rule_by_instant,
        control_by_instant,
        per_trade,
        trades=trades,
        dropped=dropped,
        window=(instants[0], instants[-1]) if instants else None,
    )


def _paired_t(differences: Sequence[float]) -> tuple[float, float]:
    """Paired t and the spread it came from, or zeros for too small a sample."""
    n = len(differences)
    if n < 2:
        return 0.0, 0.0
    mean = sum(differences) / n
    variance = sum((d - mean) ** 2 for d in differences) / (n - 1)
    spread = math.sqrt(variance)
    if spread <= 0:
        return 0.0, 0.0
    return mean / (spread / math.sqrt(n)), spread


def _summarise(
    rule: list[float],
    control: list[float],
    per_trade: list[float],
    *,
    trades: int,
    dropped: int,
    window: tuple[datetime, datetime] | None,
) -> Measurement:
    if not rule:
        return Measurement(
            instants=0,
            trades=0,
            rule_r=0.0,
            control_r=0.0,
            spread_r=0.0,
            t_statistic=0.0,
            unclustered_t=0.0,
            dropped_undecided=dropped,
            window=window,
        )

    differences = [r - c for r, c in zip(rule, control, strict=True)]
    t_statistic, spread = _paired_t(differences)
    unclustered, _ = _paired_t(per_trade)

    return Measurement(
        instants=len(rule),
        trades=trades,
        rule_r=sum(rule) / len(rule),
        control_r=sum(control) / len(control),
        spread_r=spread,
        t_statistic=t_statistic,
        unclustered_t=unclustered,
        dropped_undecided=dropped,
        window=window,
    )


def load_series(
    session: Any,
    *,
    provider_code: str,
    timeframe: Any,
    start: datetime | None = None,
    end: datetime | None = None,
    symbols: Sequence[str] | None = None,
) -> dict[str, list[Bar]]:
    """Read one provider's stored series into the shape `measure` wants.

    One provider, never a merge. Three sources now price the same instrument
    and they disagree - the broker and the public feed differ by 33-39% of a
    stop distance on every major pair - so a measurement assembled from
    whichever source happened to have each bar would be a measurement of the
    assembly.
    """
    from sqlalchemy import select

    from app.models.instruments import Instrument, Provider
    from app.models.market_data import Bar as StoredBar

    provider_id = session.scalar(
        select(Provider.id).where(Provider.code == provider_code)
    )
    if provider_id is None:
        return {}

    query = (
        select(Instrument.symbol, StoredBar)
        .join(Instrument, Instrument.id == StoredBar.instrument_id)
        .where(
            StoredBar.provider_id == provider_id,
            StoredBar.timeframe == timeframe.value,
        )
        .order_by(Instrument.symbol, StoredBar.event_time)
    )
    if start is not None:
        query = query.where(StoredBar.event_time >= start)
    if end is not None:
        query = query.where(StoredBar.event_time < end)
    if symbols:
        query = query.where(Instrument.symbol.in_(list(symbols)))

    built: dict[str, list[Bar]] = {}
    for symbol, row in session.execute(query):
        built.setdefault(symbol, []).append(
            Bar(
                at=row.event_time,
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
            )
        )
    return built


def main(argv: list[str] | None = None) -> int:
    """Run the rule over a stored series and print what it did.

    A command rather than a notebook, for the reason this module exists: the
    original result came from a script nobody can find, so the way to get this
    number must be something anybody can type and re-type.

        python -m app.learning.measure --provider dukascopy --timeframe D1
        python -m app.learning.measure --provider yfinance --timeframe H1 --from 2024

    The provider is required and has no default. A measurement whose source
    was implicit is a measurement whose source will be misremembered, and the
    three sources here disagree by more than the effect being looked for.
    """
    import argparse
    import json

    from app.core.enums import Timeframe
    from app.db.session import session_scope

    parser = argparse.ArgumentParser(
        description="Measure the cross-sectional rule over a stored series."
    )
    parser.add_argument("--provider", required=True)
    parser.add_argument("--timeframe", default="H1", choices=["M1", "M15", "H1", "D1"])
    parser.add_argument("--from", dest="start_year", type=int, default=None)
    parser.add_argument("--to", dest="end_year", type=int, default=None)
    parser.add_argument(
        "--universe",
        default="ranked",
        choices=["ranked", "all"],
        help="'ranked' is the measured universe; 'all' is an explicit experiment",
    )
    args = parser.parse_args(argv)

    timeframe = Timeframe(args.timeframe)
    start = datetime(args.start_year, 1, 1, tzinfo=UTC) if args.start_year else None
    end = datetime(args.end_year, 1, 1, tzinfo=UTC) if args.end_year else None

    with session_scope() as session:
        series = load_series(
            session,
            provider_code=args.provider,
            timeframe=timeframe,
            start=start,
            end=end,
        )

    if not series:
        # Named rather than reported as a result of zero. "No bars for that
        # provider" and "the rule found nothing" are different facts, and a
        # table of zeros for the first would be read as the second.
        print(
            f"no {timeframe.value} bars stored under provider {args.provider!r}. "
            "Nothing measured - this is not a result of zero"
        )
        return 1

    bars = sum(len(v) for v in series.values())
    print(
        f"measuring {len(series)} instruments, {bars} {timeframe.value} bars, "
        f"provider {args.provider}"
    )

    result = measure(
        series,
        bar_interval=timeframe.delta,
        universe=(
            crosssection.RANKED_UNIVERSE if args.universe == "ranked" else None
        ),
    )
    print(json.dumps(result.as_dict(), indent=2))

    # Stated in words as well as numbers, and stated the same way whichever
    # direction it came out. A negative result reported quietly and a positive
    # one reported loudly is how a registry fills up with edges.
    if result.instants == 0:
        print()
        print("No instant produced a scored pair. Nothing was measured.")
    elif result.significant:
        print()
        direction = "beat" if result.edge_r > 0 else "lost to"
        print(
            f"Over {result.instants} instants the rule {direction} its control "
            f"by {result.edge_r:+.4f} R at t = {result.t_statistic:.2f}. "
            f"Net of costs: {result.net_r:+.4f} R."
        )
    else:
        print()
        print(
            f"Over {result.instants} instants the rule differed from its "
            f"control by {result.edge_r:+.4f} R at t = {result.t_statistic:.2f}, "
            "which does not clear 1.96. Not distinguishable from a coin flip."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
