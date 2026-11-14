"""Which timeframes are observed and which are computed, and how to compute one.

MetaTrader 5 has 21 chart periods. The bridge expert (`infra/mql5/MolidoBridge.mq5`,
`Publish` -> `WriteBars`) writes bar files for three of them: M5, M15 and H1. Those
are **native**: a file the terminal wrote. (Stage 7 first listed the seven names in
`TimeframeName`; that function only names periods, it does not decide what is
published, so that list was wrong and is corrected here.) M1 is deliberately not
published, so periods that need it (M2, M3, M4, M6, M12) have no source here.
Every other period is **derived** here from the largest native period that
divides it, and is labelled so a reader never mistakes a computed candle for an observed one.

**No lookahead.** `resample` emits a bucket only when the bucket has ended at
or before `as_of`, and it only reads source bars that themselves closed at or
before `as_of`. The bucket still being written is never returned.

**Gaps are reported, not hidden.** A bucket built from fewer source bars than
it should hold carries `complete=False` and its real `bar_count`; the caller
decides whether a thin candle is usable.

W1 and MN1 are calendar periods with no fixed length. They are labelled derived
(from D1) but `resample` refuses them rather than guessing a week or month
boundary.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from app.core.enums import Timeframe

MT5_BRIDGE_NATIVE: frozenset[Timeframe] = frozenset(
    {
        Timeframe.M5,
        Timeframe.M15,
        Timeframe.H1,
    }
)


class Source(StrEnum):
    NATIVE = "native"
    DERIVED = "derived"


def source_kind(tf: Timeframe, native: frozenset[Timeframe] = MT5_BRIDGE_NATIVE) -> Source:
    return Source.NATIVE if tf in native else Source.DERIVED


def derivation_base(
    tf: Timeframe, native: frozenset[Timeframe] = MT5_BRIDGE_NATIVE
) -> Timeframe | None:
    """The native period a derived one is built from; None if `tf` is native."""
    if tf in native:
        return None
    if tf.is_calendar_based:
        return Timeframe.D1 if Timeframe.D1 in native else None
    target = int(tf.delta.total_seconds())
    best: Timeframe | None = None
    for cand in native:
        if cand.is_calendar_based:
            continue
        step = int(cand.delta.total_seconds())
        if step < target and target % step == 0 and (best is None or cand.delta > best.delta):
            best = cand
    return best


def catalogue(native: frozenset[Timeframe] = MT5_BRIDGE_NATIVE) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for tf in Timeframe:
        base = derivation_base(tf, native)
        out.append(
            {
                "timeframe": tf.value,
                "source": source_kind(tf, native).value,
                "derived_from": base.value if base else None,
                "seconds": None if tf.is_calendar_based else int(tf.delta.total_seconds()),
                "calendar": tf.is_calendar_based,
            }
        )
    return out


class BarLike(Protocol):
    @property
    def open_time(self) -> datetime: ...
    @property
    def open(self) -> float: ...
    @property
    def high(self) -> float: ...
    @property
    def low(self) -> float: ...
    @property
    def close(self) -> float: ...
    @property
    def volume(self) -> float | None: ...


@dataclass(frozen=True)
class DerivedBar:
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    timeframe: Timeframe
    derived_from: Timeframe
    bar_count: int
    expected_count: int
    source: Source = Source.DERIVED

    @property
    def complete(self) -> bool:
        return self.bar_count == self.expected_count


def bucket_start(stamp: datetime, tf: Timeframe, shift_hours: int = 0) -> datetime:
    """Bucket start aligned on the broker clock (`shift_hours` from UTC)."""
    seconds = int(tf.delta.total_seconds())
    shift = shift_hours * 3600
    epoch = int(stamp.astimezone(UTC).timestamp())
    return datetime.fromtimestamp((epoch + shift) // seconds * seconds - shift, tz=UTC)


def resample(
    bars: Iterable[BarLike],
    src: Timeframe,
    dst: Timeframe,
    as_of: datetime,
    *,
    shift_hours: int = 0,
) -> list[DerivedBar]:
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    if src.is_calendar_based or dst.is_calendar_based:
        raise ValueError("calendar periods (W1, MN1) are not resampled here")
    s, d = int(src.delta.total_seconds()), int(dst.delta.total_seconds())
    if d <= s or d % s:
        raise ValueError(f"{dst.value} is not a whole multiple of {src.value}")
    closed = sorted(
        (b for b in bars if b.open_time + src.delta <= as_of), key=lambda b: b.open_time
    )
    groups: dict[datetime, list[BarLike]] = {}
    for b in closed:
        groups.setdefault(bucket_start(b.open_time, dst, shift_hours), []).append(b)
    out: list[DerivedBar] = []
    for start, group in sorted(groups.items()):
        if start + dst.delta > as_of:
            continue
        out.append(_fold(start, group, src, dst, d // s))
    return out


def _fold(
    start: datetime, group: Sequence[BarLike], src: Timeframe, dst: Timeframe, expected: int
) -> DerivedBar:
    vols = [b.volume for b in group if b.volume is not None]
    return DerivedBar(
        open_time=start,
        open=group[0].open,
        high=max(b.high for b in group),
        low=min(b.low for b in group),
        close=group[-1].close,
        volume=sum(vols) if vols else None,
        timeframe=dst,
        derived_from=src,
        bar_count=len(group),
        expected_count=expected,
    )


__all__ = [
    "MT5_BRIDGE_NATIVE",
    "DerivedBar",
    "Source",
    "bucket_start",
    "catalogue",
    "derivation_base",
    "resample",
    "source_kind",
]
