"""Spike & Imbalance. FVG detection is delegated to the existing SMC helper."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.agents.analyzers.bars import Candle, atr
from app.agents.analyzers.smc import fair_value_gaps
from app.agents.pro_btb.status import RuleStatus
from app.agents.pro_btb.types import Direction
from app.agents.v2.rules import SPIKE_IMBALANCE_BY_ID, spike_imbalance_counts


@dataclass(frozen=True)
class SpikeImbalanceParams:
    atr_period: int = 14
    spike_atr_multiple: float = 2.5  # RESEARCH
    status: RuleStatus = RuleStatus.RESEARCH


@dataclass(frozen=True)
class AtrSpike:
    index: int
    direction: Direction
    range_atr: float
    reasons: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "direction": self.direction.value,
            "range_atr": self.range_atr,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class FvgZone:
    side: str
    low: float
    high: float
    formed_at: int
    mitigated: bool
    mitigated_at: int | None

    def as_dict(self) -> dict:
        return {
            "side": self.side, "low": self.low, "high": self.high,
            "formed_at": self.formed_at, "mitigated": self.mitigated,
            "mitigated_at": self.mitigated_at,
        }


@dataclass(frozen=True)
class SpikeImbalanceReport:
    spikes: tuple[AtrSpike, ...]
    fvgs: tuple[FvgZone, ...]
    open_imbalances: tuple[FvgZone, ...]
    continuation_probability: None  # never invented
    reversal_probability: None
    reasons: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "spikes": [s.as_dict() for s in self.spikes],
            "fvgs": [z.as_dict() for z in self.fvgs],
            "open_imbalances": [z.as_dict() for z in self.open_imbalances],
            "continuation_probability": None,
            "reversal_probability": None,
            "reasons": list(self.reasons),
            "rule_statuses": {k: r.status.value for k, r in SPIKE_IMBALANCE_BY_ID.items()},
            "status_counts": spike_imbalance_counts(),
            "fvg_source": "app.agents.analyzers.smc.fair_value_gaps",
        }


def fvg_is_mitigated(
    bars: Sequence[Candle],
    side: str,
    low: float,
    high: float,
    formed_at: int,
) -> tuple[bool, int | None]:
    """Same fill rule as SM04: later bars trade through the near side of the gap."""
    for j in range(formed_at + 1, len(bars)):
        bar = bars[j]
        if side == "bull" and bar.low <= low:
            return True, j
        if side == "bear" and bar.high >= high:
            return True, j
    return False, None


def detect_atr_spikes(
    bars: Sequence[Candle], params: SpikeImbalanceParams,
) -> tuple[AtrSpike, ...]:
    """ATR at each bar uses only earlier closes (no look-ahead)."""
    out: list[AtrSpike] = []
    for index, bar in enumerate(bars):
        last_atr = atr(tuple(bars[:index]), params.atr_period)
        if last_atr is None or last_atr <= 0:
            continue
        rng = (bar.high - bar.low) / last_atr
        if rng < params.spike_atr_multiple:
            continue
        direction = Direction.BULL if bar.close >= bar.open else Direction.BEAR
        out.append(AtrSpike(
            index, direction, rng,
            (f"bar {index} range {rng:.2f}x prior ATR (threshold RESEARCH)",),
        ))
    return tuple(out)


class SpikeImbalanceEngine:
    def __init__(self, params: SpikeImbalanceParams | None = None) -> None:
        self.params = params or SpikeImbalanceParams()

    def run(self, bars: Sequence[Candle]) -> SpikeImbalanceReport:
        spikes = detect_atr_spikes(bars, self.params)
        raw = fair_value_gaps(tuple(bars))
        fvgs: list[FvgZone] = []
        for side, low, high, formed_at in raw:
            filled, at = fvg_is_mitigated(bars, side, low, high, formed_at)
            fvgs.append(FvgZone(side, low, high, formed_at, filled, at))
        open_ = tuple(z for z in fvgs if not z.mitigated)
        reasons = [
            f"{len(spikes)} ATR spike(s) on the recent bars",
            f"{len(fvgs)} FVG(s) from smc.fair_value_gaps, {len(open_)} still open",
            "continuation/reversal probabilities are not estimated",
        ]
        return SpikeImbalanceReport(
            spikes=spikes, fvgs=tuple(fvgs), open_imbalances=open_,
            continuation_probability=None, reversal_probability=None,
            reasons=tuple(reasons),
        )
