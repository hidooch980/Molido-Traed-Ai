"""Choose the instruments by evidence, and hold back the years that judge it.

The universe was declared by hand: forty-nine symbols in a frozen set. The
historical result that made this rule worth building was measured on
twenty-two of them, because that is what the deep-history feed happened to
carry, and nobody had noticed the measured set and the declared set were
different things.

Then the folded series arrived carrying all forty-nine and measured -0.1064 R
at t = -3.28. Restricted to the same twenty-two it measures -0.0201 at
t = -0.48 - out of significance. The twenty-seven instruments the declaration
adds move the result by 0.086 R, four times the entire claimed edge.

So the universe is not a detail around the rule. It is the largest term
anybody has measured, and it was the one chosen without measurement.

**The obvious fix is the dangerous one.** Score every instrument, keep the
ones that made money, and the result is a beautiful backtest that means
nothing: with forty-nine instruments and a coin, roughly half will look
positive, and selecting them reproduces the coin's history exactly. That is
not a universe, it is a record of which way the coin landed.

So selection here never sees the years it is judged on.

**Split by time, select on the first part, measure on the second.** The
in-sample number is what selection can always produce; the out-of-sample
number is the answer. Both are reported, because the gap between them *is*
the overfitting, and a method that shows only the second is hiding how hard
it looked.

**Stability is required, not just profit.** An instrument that carried the
whole edge in one quarter and lost in the others is a story about that
quarter. Selection asks for a positive contribution in a majority of
sub-periods as well as overall, so a single windfall cannot buy a place.

**A selection that keeps almost everything is a warning, not a success.**
If forty-five of forty-nine survive, the filter is not selecting - it is
agreeing with whatever it was given, and the out-of-sample number will
disappoint in exactly the way the in-sample one did not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.learning.measure import Bar, Measurement, measure

#: Fraction of the timeline used to choose the universe. The rest is never
#: looked at during selection and is the only number reported as a result.
TRAIN_FRACTION = 0.6

#: Sub-periods the training window is cut into when asking for stability.
#: Four is enough to tell a persistent contribution from one good quarter and
#: few enough that each still holds a usable number of instants.
STABILITY_BLOCKS = 4

#: How many of those blocks an instrument must be positive in. Three of four
#: rather than all four: demanding perfection selects for luck as surely as
#: demanding nothing does, because no real instrument is positive every
#: quarter.
STABILITY_REQUIRED = 3

#: Keeping more than this share of what it was given means the filter is
#: agreeing rather than selecting, and the result is reported with that said.
SUSPICIOUS_KEEP_RATE = 0.85


@dataclass(frozen=True)
class InstrumentScore:
    """What one instrument contributed, and how consistently."""

    symbol: str
    edge_r: float
    instants: int
    blocks_positive: int
    blocks_measured: int

    @property
    def stable(self) -> bool:
        if self.blocks_measured < STABILITY_BLOCKS:
            # Too little history to have been consistent about anything. Not
            # a failure and not a pass - it cannot answer the question, and
            # an instrument that cannot answer is not selected.
            return False
        return self.blocks_positive >= STABILITY_REQUIRED

    @property
    def selected(self) -> bool:
        return self.edge_r > 0 and self.stable

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "edge_r": round(self.edge_r, 5),
            "instants": self.instants,
            "blocks_positive": f"{self.blocks_positive}/{self.blocks_measured}",
            "selected": self.selected,
        }


@dataclass
class SelectionResult:
    """The chosen universe, and both numbers that describe it."""

    selected: frozenset[str]
    considered: frozenset[str]
    scores: list[InstrumentScore]
    in_sample: Measurement | None
    out_of_sample: Measurement | None
    split_at: datetime | None
    warnings: list[str] = field(default_factory=list)

    @property
    def keep_rate(self) -> float:
        if not self.considered:
            return 0.0
        return len(self.selected) / len(self.considered)

    @property
    def overfit_gap_r(self) -> float | None:
        """In-sample edge minus out-of-sample edge.

        This is the number selection cannot argue with. A large positive gap
        means the choosing found patterns that did not survive the years it
        was not allowed to see.
        """
        if self.in_sample is None or self.out_of_sample is None:
            return None
        return self.in_sample.edge_r - self.out_of_sample.edge_r

    def as_dict(self) -> dict[str, Any]:
        return {
            "selected": sorted(self.selected),
            "selected_count": len(self.selected),
            "considered_count": len(self.considered),
            "keep_rate": round(self.keep_rate, 3),
            "split_at": self.split_at.isoformat() if self.split_at else None,
            "in_sample": self.in_sample.as_dict() if self.in_sample else None,
            "out_of_sample": (
                self.out_of_sample.as_dict() if self.out_of_sample else None
            ),
            "overfit_gap_r": (
                round(self.overfit_gap_r, 5) if self.overfit_gap_r is not None else None
            ),
            "scores": [score.as_dict() for score in self.scores],
            "warnings": self.warnings,
            "note": (
                "the out-of-sample measurement is the result. The in-sample one "
                "is what selection can always produce, and the gap between them "
                "is how hard it looked"
            ),
        }


def _cut(
    series: dict[str, list[Bar]], *, before: datetime | None = None,
    after: datetime | None = None,
) -> dict[str, list[Bar]]:
    """The same series, restricted in time. Empty instruments are dropped."""
    out: dict[str, list[Bar]] = {}
    for symbol, bars in series.items():
        kept = [
            bar
            for bar in bars
            if (before is None or bar.at < before) and (after is None or bar.at >= after)
        ]
        if kept:
            out[symbol] = kept
    return out


def _span(series: dict[str, list[Bar]]) -> tuple[datetime, datetime] | None:
    stamps = [bar.at for bars in series.values() for bar in bars]
    if not stamps:
        return None
    return min(stamps), max(stamps)


def score_instrument(
    series: dict[str, list[Bar]],
    symbol: str,
    *,
    bar_interval: timedelta,
    universe: frozenset[str],
    blocks: int = STABILITY_BLOCKS,
) -> InstrumentScore:
    """What the rule earned on one instrument, overall and per sub-period.

    Measured with the instrument *in* the cross-section rather than alone: the
    rule ranks instruments against each other, so an instrument measured by
    itself is not being measured under the rule at all.

    That is `universe` wide and `only` narrow. Narrowing the ranking instead
    leaves a cross-section of one, which `rank` refuses as too thin - every
    instant is skipped, `instants` comes back 0 and `edge_r` 0.0, and since
    `selected` asks for `edge_r > 0` the answer is that nothing qualifies. Not
    a thin result: no result at all, reported in the same shape as one.
    """
    mine = frozenset({symbol})
    contribution = measure(
        series, bar_interval=bar_interval, universe=mine | universe, only=mine
    )

    span = _span(series)
    positive = 0
    measured = 0
    if span is not None and blocks > 0:
        start, end = span
        step = (end - start) / blocks
        for index in range(blocks):
            block = _cut(
                series,
                after=start + step * index,
                before=start + step * (index + 1),
            )
            if not block:
                continue
            result = measure(
                block, bar_interval=bar_interval, universe=mine | universe, only=mine
            )
            if result.instants == 0:
                continue
            measured += 1
            if result.edge_r > 0:
                positive += 1

    return InstrumentScore(
        symbol=symbol,
        edge_r=contribution.edge_r,
        instants=contribution.instants,
        blocks_positive=positive,
        blocks_measured=measured,
    )


def select(
    series: dict[str, list[Bar]],
    *,
    bar_interval: timedelta,
    considered: frozenset[str],
    train_fraction: float = TRAIN_FRACTION,
) -> SelectionResult:
    """Choose a universe on the first years, and report it on the last.

    Nothing after `split_at` is read while choosing. That is the whole method:
    the out-of-sample measurement is the only one that is a result, and it is
    only a result because selection could not see it.
    """
    span = _span(series)
    if span is None:
        return SelectionResult(
            selected=frozenset(),
            considered=considered,
            scores=[],
            in_sample=None,
            out_of_sample=None,
            split_at=None,
            warnings=["the series holds no bars, so nothing was selected"],
        )

    start, end = span
    split_at = start + (end - start) * train_fraction
    train = _cut(series, before=split_at)
    test = _cut(series, after=split_at)

    warnings: list[str] = []
    if not train or not test:
        warnings.append(
            "the series does not span enough time to hold back a test window, "
            "so no selection was made - a universe chosen on everything is a "
            "universe nothing can judge"
        )
        return SelectionResult(
            selected=frozenset(),
            considered=considered,
            scores=[],
            in_sample=None,
            out_of_sample=None,
            split_at=split_at,
            warnings=warnings,
        )

    scores = [
        score_instrument(
            train, symbol, bar_interval=bar_interval, universe=considered
        )
        for symbol in sorted(considered)
        if symbol in train
    ]
    chosen = frozenset(score.symbol for score in scores if score.selected)

    if not chosen:
        warnings.append(
            "no instrument was both positive and stable in the training years. "
            "That is a result about the rule rather than about the instruments"
        )

    in_sample = (
        measure(train, bar_interval=bar_interval, universe=chosen) if chosen else None
    )
    out_of_sample = (
        measure(test, bar_interval=bar_interval, universe=chosen) if chosen else None
    )

    result = SelectionResult(
        selected=chosen,
        considered=considered,
        scores=scores,
        in_sample=in_sample,
        out_of_sample=out_of_sample,
        split_at=split_at,
        warnings=warnings,
    )

    if chosen and result.keep_rate > SUSPICIOUS_KEEP_RATE:
        warnings.append(
            f"selection kept {result.keep_rate:.0%} of what it was given, which "
            "is agreeing rather than selecting - expect the out-of-sample "
            "number to disappoint in the way the in-sample one did not"
        )
    gap = result.overfit_gap_r
    if gap is not None and gap > 0 and out_of_sample is not None:
        if out_of_sample.edge_r <= 0:
            warnings.append(
                "the chosen universe is positive in the years it was chosen on "
                "and not in the years it was not. That is the shape of a "
                "selection that found history rather than an edge"
            )

    return result
