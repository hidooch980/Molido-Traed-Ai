"""Market memory (spec phase 9, §8).

Three horizons of the same question — *what has this market been doing?* —
answered over recent days, recent months, and multiple years. The spec's
Meta-Brain (phase 16) will decide which horizon matters for a given decision;
this module's job is to make all three available and comparable.

**No table.** Memory is a pure function of a bar window, like a feature, and
recomputing it costs one query. Persisting it would create a second source of
truth that can drift from the bars it claims to summarise, and a stale memory
is worse than none — it looks authoritative. Historical *episodes*, which do
need storage because they carry outcomes, are phase 10.

Horizons are defined in **calendar duration**, not bar counts, so "short-term"
means the same span whether the caller asks on M15 or D1. A horizon with too
few bars is reported as unavailable with its reason; the alternative — a
three-year memory built from nine bars — is a confident lie.
"""

from __future__ import annotations

import math
import statistics
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import Timeframe
from app.core.errors import ValidationFailedError
from app.services.point_in_time import BarView, get_bars


class MemoryHorizon(StrEnum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


# (duration, minimum bars). The minimums are deliberately modest — enough for
# the statistics to mean something, not so high that a young instrument has no
# memory at all.
HORIZONS: dict[MemoryHorizon, tuple[timedelta, int]] = {
    MemoryHorizon.SHORT: (timedelta(days=3), 20),
    MemoryHorizon.MEDIUM: (timedelta(days=90), 100),
    MemoryHorizon.LONG: (timedelta(days=365 * 3), 250),
}

# How many bars we are willing to pull for the long horizon. Three years of M1
# would be millions of rows; the cap keeps a "give me everything" request from
# turning into an accidental table scan.
MAX_BARS = 20000


@dataclass
class MemorySnapshot:
    """What one horizon remembers, as of a knowledge cutoff."""

    horizon: MemoryHorizon
    available: bool
    reason: str | None = None

    bars: int = 0
    window_start: datetime | None = None
    window_end: datetime | None = None

    open: float | None = None
    close: float | None = None
    high: float | None = None
    low: float | None = None

    return_pct: float | None = None
    realized_vol: float | None = None
    # Where the latest close sits between the window's low and high: 0 at the
    # low, 1 at the high. The single most useful number for "is this cheap or
    # expensive relative to what this market has been doing".
    position_in_range: float | None = None
    max_drawdown_pct: float | None = None
    max_runup_pct: float | None = None
    bars_since_high: int | None = None
    bars_since_low: int | None = None
    # net move divided by the noise around it — closer to a t-statistic than a
    # verdict. Direction only becomes a label above a threshold.
    trend_strength: float | None = None
    trend: str | None = None

    def as_dict(self) -> dict[str, Any]:
        if not self.available:
            return {
                "horizon": self.horizon.value,
                "available": False,
                "reason": self.reason,
            }
        return {
            "horizon": self.horizon.value,
            "available": True,
            "bars": self.bars,
            "window_start": self.window_start.isoformat() if self.window_start else None,
            "window_end": self.window_end.isoformat() if self.window_end else None,
            "open": self.open,
            "close": self.close,
            "high": self.high,
            "low": self.low,
            "return_pct": self.return_pct,
            "realized_vol": self.realized_vol,
            "position_in_range": self.position_in_range,
            "max_drawdown_pct": self.max_drawdown_pct,
            "max_runup_pct": self.max_runup_pct,
            "bars_since_high": self.bars_since_high,
            "bars_since_low": self.bars_since_low,
            "trend_strength": self.trend_strength,
            "trend": self.trend,
        }


def _unavailable(horizon: MemoryHorizon, reason: str) -> MemorySnapshot:
    return MemorySnapshot(horizon=horizon, available=False, reason=reason)


def summarise(horizon: MemoryHorizon, bars: list[BarView]) -> MemorySnapshot:
    """Reduce a bar window to what is worth remembering about it."""
    _, minimum = HORIZONS[horizon]
    if len(bars) < minimum:
        return _unavailable(
            horizon,
            f"needs {minimum} bars, has {len(bars)}",
        )

    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]

    high = max(highs)
    low = min(lows)
    first_open = bars[0].open
    last_close = closes[-1]

    returns = [
        math.log(b / a) for a, b in zip(closes, closes[1:], strict=False) if a > 0 and b > 0
    ]
    vol = statistics.pstdev(returns) if len(returns) > 1 else None

    # Peak-to-trough and trough-to-peak on closes, walked once.
    peak = trough = closes[0]
    max_drawdown = max_runup = 0.0
    for close in closes:
        peak = max(peak, close)
        trough = min(trough, close)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - close) / peak)
        if trough > 0:
            max_runup = max(max_runup, (close - trough) / trough)

    span = high - low
    position = (last_close - low) / span if span > 0 else None

    net_return = (
        math.log(last_close / first_open) if first_open > 0 and last_close > 0 else None
    )
    # Net move measured against the noise it travelled through. Dividing by
    # sqrt(n) makes windows of different lengths comparable — otherwise a long
    # window always looks more "trending" simply for having more bars.
    strength = None
    if net_return is not None and vol and vol > 0:
        strength = net_return / (vol * math.sqrt(len(returns)))

    return MemorySnapshot(
        horizon=horizon,
        available=True,
        bars=len(bars),
        window_start=bars[0].event_time,
        window_end=bars[-1].event_time,
        open=round(first_open, 10),
        close=round(last_close, 10),
        high=round(high, 10),
        low=round(low, 10),
        return_pct=round(net_return, 10) if net_return is not None else None,
        realized_vol=round(vol, 10) if vol is not None else None,
        position_in_range=round(position, 6) if position is not None else None,
        max_drawdown_pct=round(max_drawdown, 10),
        max_runup_pct=round(max_runup, 10),
        bars_since_high=len(bars) - 1 - highs.index(high),
        bars_since_low=len(bars) - 1 - lows.index(low),
        trend_strength=round(strength, 6) if strength is not None else None,
        trend=_label(strength),
    )


def _label(strength: float | None) -> str | None:
    """Turn a strength number into a word — or refuse to.

    The threshold is 1.0: the net move is at least as large as the typical
    noise of the window. Below that, "sideways" is not a hedge, it is the
    honest reading — the market went nowhere it had not already been.
    """
    if strength is None:
        return None
    if strength >= 1.0:
        return "up"
    if strength <= -1.0:
        return "down"
    return "sideways"


def recall(
    session: Session,
    instrument_id: uuid.UUID,
    timeframe: Timeframe,
    as_of: datetime,
    horizon: MemoryHorizon,
    *,
    provider_id: uuid.UUID | None = None,
) -> MemorySnapshot:
    """What one horizon remembers at `as_of`."""
    if as_of.tzinfo is None:
        raise ValidationFailedError("as_of must be timezone-aware (UTC)")
    as_of = as_of.astimezone(UTC)

    duration, _ = HORIZONS[horizon]
    if timeframe.is_calendar_based:
        raise ValidationFailedError(
            "Weekly and monthly bars have no fixed grid; recall on an intraday "
            "or daily timeframe instead.",
            timeframe=timeframe.value,
        )

    wanted = int(duration / timeframe.delta) + 1
    bars = get_bars(
        session,
        instrument_id,
        timeframe,
        as_of,
        start=as_of - duration,
        lookback=min(wanted, MAX_BARS),
        provider_id=provider_id,
    )
    if not bars:
        return _unavailable(horizon, "no bars in the window")
    return summarise(horizon, bars)


def recall_all(
    session: Session,
    instrument_id: uuid.UUID,
    timeframe: Timeframe,
    as_of: datetime,
    *,
    provider_id: uuid.UUID | None = None,
) -> dict[MemoryHorizon, MemorySnapshot]:
    """All three horizons at one cutoff.

    Every horizon is present in the result, including the ones that could not
    be computed — an absent key would be indistinguishable from a horizon the
    caller forgot to ask for.
    """
    return {
        horizon: recall(
            session, instrument_id, timeframe, as_of, horizon, provider_id=provider_id
        )
        for horizon in MemoryHorizon
    }


# Snapshots are pure functions of (instrument, timeframe, as_of, provider): the
# three-year horizon reads several thousand bars, and one decision used to pay
# for that six times over - three horizons, fetched once by the world state and
# again by the regime classifier, which had no way to know the work was already
# done. Callers that need both now read once and hand the result to both.
MemorySnapshots = dict[MemoryHorizon, MemorySnapshot]


def agreement(snapshots: dict[MemoryHorizon, MemorySnapshot]) -> dict[str, Any]:
    """Do the horizons tell the same story?

    Reported as a fact, not a signal. A short-term move against a long-term
    trend is the single most common shape in markets; whether that is a
    pullback to buy or a reversal to respect is a judgement this layer has no
    business making — and no evidence to make it with.
    """
    labels = {
        horizon.value: snap.trend
        for horizon, snap in snapshots.items()
        if snap.available and snap.trend is not None
    }
    directional = {k: v for k, v in labels.items() if v in ("up", "down")}

    if len(directional) < 2:
        return {
            "trends": labels,
            "aligned": None,
            "note": "not enough directional horizons to compare",
        }

    values = set(directional.values())
    return {
        "trends": labels,
        "aligned": len(values) == 1,
        "direction": next(iter(values)) if len(values) == 1 else None,
        "conflict": sorted(directional) if len(values) > 1 else [],
    }
