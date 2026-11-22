"""SP2L (Spike–2Leg) detector. Official process from poursamadi.com; prices WAIT."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.agents.analyzers.bars import Candle, atr, swings
from app.agents.pro_btb.status import RuleStatus
from app.agents.pro_btb.types import Direction, PipelineDecision
from app.agents.v2.rules import SP2L_BY_ID, sp2l_counts


@dataclass(frozen=True)
class Sp2lParams:
    """Numeric cutoffs. All RESEARCH unless a later source pins them."""

    atr_period: int = 14
    min_spike_bars: int = 3
    min_spike_atr: float = 1.8
    min_body_ratio: float = 0.5
    swing_k: int = 2
    status: RuleStatus = RuleStatus.RESEARCH


@dataclass(frozen=True)
class SpikeMove:
    direction: Direction
    start_index: int
    end_index: int
    start_price: float
    end_price: float
    has_pgap: bool
    pgap_index: int | None
    length: float
    valid: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class Sp2lReport:
    direction: Direction
    decision: PipelineDecision
    spike: SpikeMove | None
    leg1: tuple[int, int] | None
    leg2: tuple[int, int] | None
    hl_lh: tuple[float, ...]
    leg_ratio: float | None
    breakout: bool
    false_breakout: bool
    retest: bool
    invalidated: bool
    entry_action: str
    entry: float | None
    stop_loss: float | None
    take_profit: float | None
    risk_reward: float | None
    reasons: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "direction": self.direction.value,
            "decision": self.decision.value,
            "spike": None if self.spike is None else {
                "direction": self.spike.direction.value,
                "start_index": self.spike.start_index,
                "end_index": self.spike.end_index,
                "has_pgap": self.spike.has_pgap,
                "valid": self.spike.valid,
                "reasons": list(self.spike.reasons),
            },
            "leg1": self.leg1,
            "leg2": self.leg2,
            "hl_lh": list(self.hl_lh),
            "leg_ratio": self.leg_ratio,
            "breakout": self.breakout,
            "false_breakout": self.false_breakout,
            "retest": self.retest,
            "invalidated": self.invalidated,
            "entry_action": self.entry_action,
            "entry": self.entry,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "risk_reward": self.risk_reward,
            "reasons": list(self.reasons),
            "rule_statuses": {k: r.status.value for k, r in SP2L_BY_ID.items()},
            "status_counts": sp2l_counts(),
        }


def _body_ratio(window: Sequence[Candle], direction: Direction) -> float:
    signed = total = 0.0
    for bar in window:
        rng = max(bar.high - bar.low, 1e-12)
        total += rng
        body = bar.close - bar.open
        signed += max(body, 0.0) if direction is Direction.BULL else max(-body, 0.0)
    return signed / total if total else 0.0


def _pgap(prev: Candle, bar: Candle, direction: Direction) -> bool:
    """RESEARCH default: a full gap beyond the previous bar's extreme (P-Gap)."""
    if direction is Direction.BULL:
        return bar.open > prev.high
    return bar.open < prev.low


def detect_spike(bars: Sequence[Candle], params: Sp2lParams | None = None) -> SpikeMove | None:
    """Most recent qualifying spike. Invalid if the run has no P-Gap."""
    params = params or Sp2lParams()
    if len(bars) < params.min_spike_bars + 2:
        return None
    last_atr = atr(tuple(bars), params.atr_period)
    if last_atr is None or last_atr <= 0:
        return None
    n = params.min_spike_bars
    # Scan trailing windows, newest first.
    for end in range(len(bars) - 1, n - 1, -1):
        start = end - n + 1
        window = list(bars[start:end + 1])
        up = window[-1].close - window[0].open
        direction = Direction.BULL if up > 0 else Direction.BEAR
        length = abs(
            (max(b.high for b in window) if direction is Direction.BULL
             else min(b.low for b in window))
            - (window[0].low if direction is Direction.BULL else window[0].high)
        )
        if length / last_atr < params.min_spike_atr:
            continue
        if _body_ratio(window, direction) < params.min_body_ratio:
            continue
        # A correction bar is not part of the spike; the second leg starts after it.
        if direction is Direction.BULL and any(b.close < b.open for b in window):
            continue
        if direction is Direction.BEAR and any(b.close > b.open for b in window):
            continue
        gap_i = None
        for i in range(start, end + 1):
            if i == 0:
                continue
            if _pgap(bars[i - 1], bars[i], direction):
                gap_i = i
                break
        start_price = window[0].low if direction is Direction.BULL else window[0].high
        end_price = window[-1].high if direction is Direction.BULL else window[-1].low
        reasons = [
            f"{direction.value} spike {start}->{end}, {length / last_atr:.2f} ATR",
            "P-Gap present" if gap_i is not None else "no P-Gap; spike is not valid",
        ]
        return SpikeMove(
            direction=direction, start_index=start, end_index=end,
            start_price=start_price, end_price=end_price,
            has_pgap=gap_i is not None, pgap_index=gap_i, length=length,
            valid=gap_i is not None, reasons=tuple(reasons),
        )
    return None


def _hl_lh(bars: Sequence[Candle], spike: SpikeMove) -> tuple[float, ...]:
    window = list(bars[spike.start_index:spike.end_index + 1])
    levels: list[float] = []
    if spike.direction is Direction.BULL:
        last = window[0].low
        levels.append(last)
        for bar in window[1:]:
            if bar.low > last:
                levels.append(bar.low)
                last = bar.low
    else:
        last = window[0].high
        levels.append(last)
        for bar in window[1:]:
            if bar.high < last:
                levels.append(bar.high)
                last = bar.high
    return tuple(levels)


def _second_leg(bars: Sequence[Candle], spike: SpikeMove) -> tuple[int, int] | None:
    """Official process: bull correction takes the prior bar's low; bear, the high."""
    start = spike.end_index + 1
    if start >= len(bars):
        return None
    for i in range(start, len(bars)):
        prev = bars[i - 1]
        bar = bars[i]
        if spike.direction is Direction.BULL and bar.low < prev.low:
            return (spike.end_index, i)
        if spike.direction is Direction.BEAR and bar.high > prev.high:
            return (spike.end_index, i)
    return None


def _broke(bars: Sequence[Candle], spike: SpikeMove) -> tuple[bool, float | None]:
    highs, lows = swings(tuple(bars[:spike.start_index + 1]), 2)
    if spike.direction is Direction.BULL:
        prior = [i for i in highs if i < spike.start_index]
        if not prior:
            return False, None
        level = bars[prior[-1]].high
        return any(b.close > level for b in bars[spike.start_index:spike.end_index + 1]), level
    prior = [i for i in lows if i < spike.start_index]
    if not prior:
        return False, None
    level = bars[prior[-1]].low
    return any(b.close < level for b in bars[spike.start_index:spike.end_index + 1]), level


class Sp2lEngine:
    def __init__(self, params: Sp2lParams | None = None) -> None:
        self.params = params or Sp2lParams()

    def run(self, bars: Sequence[Candle], *, as_of: datetime | None = None) -> Sp2lReport:
        del as_of  # caller must already pass only closed bars
        empty = Sp2lReport(
            direction=Direction.NONE, decision=PipelineDecision.WAIT, spike=None,
            leg1=None, leg2=None, hl_lh=(), leg_ratio=None, breakout=False,
            false_breakout=False, retest=False, invalidated=False,
            entry_action="WAIT", entry=None, stop_loss=None, take_profit=None,
            risk_reward=None, reasons=("no qualifying spike",),
        )
        spike = detect_spike(bars, self.params)
        if spike is None:
            return empty
        if not spike.valid:
            return Sp2lReport(
                direction=spike.direction, decision=PipelineDecision.STOP, spike=spike,
                leg1=(spike.start_index, spike.end_index), leg2=None, hl_lh=_hl_lh(bars, spike),
                leg_ratio=None, breakout=False, false_breakout=False, retest=False,
                invalidated=False, entry_action="WAIT", entry=None, stop_loss=None,
                take_profit=None, risk_reward=None,
                reasons=spike.reasons + ("assessment stopped: P-Gap required",),
            )
        leg2 = _second_leg(bars, spike)
        hl_lh = _hl_lh(bars, spike)
        broke, level = _broke(bars, spike)
        false_bo = False
        if broke and level is not None:
            after = bars[spike.end_index + 1:]
            if spike.direction is Direction.BULL:
                false_bo = any(b.close < level for b in after)
            else:
                false_bo = any(b.close > level for b in after)
        retest = False
        if hl_lh and spike.end_index + 1 < len(bars):
            last_level = hl_lh[-1]
            later = bars[spike.end_index + 1:]
            retest = any(b.low <= last_level <= b.high for b in later)
        invalidated = False
        after = bars[spike.end_index + 1:]
        if spike.direction is Direction.BULL:
            invalidated = any(b.close < spike.start_price for b in after)
        else:
            invalidated = any(b.close > spike.start_price for b in after)
        ratio = None
        if leg2 is not None:
            a, b = bars[leg2[0]], bars[leg2[1]]
            correction = abs((a.high if spike.direction is Direction.BULL else a.low)
                             - (b.low if spike.direction is Direction.BULL else b.high))
            if spike.length:
                ratio = correction / spike.length
        reasons = list(spike.reasons)
        reasons.append("leg 2 started" if leg2 else "still waiting for the second-leg correction")
        reasons.append("breakout of prior swing" if broke else "no prior-swing breakout")
        if false_bo:
            reasons.append("false breakout: close back through the level")
        if retest:
            reasons.append("price retested an HL/LH")
        if invalidated:
            reasons.append("invalidated: close through the spike origin")
        reasons.append(
            "WAIT: entry/SL/TP are not emitted; official SL/TP wording exists "
            "but published encodings disagree (rules remain RESEARCH)"
        )
        return Sp2lReport(
            direction=spike.direction,
            decision=PipelineDecision.STOP if invalidated else PipelineDecision.WAIT,
            spike=spike,
            leg1=(spike.start_index, spike.end_index),
            leg2=leg2,
            hl_lh=hl_lh,
            leg_ratio=ratio,
            breakout=broke,
            false_breakout=false_bo,
            retest=retest,
            invalidated=invalidated,
            entry_action="WAIT",
            entry=None, stop_loss=None, take_profit=None, risk_reward=None,
            reasons=tuple(reasons),
        )
