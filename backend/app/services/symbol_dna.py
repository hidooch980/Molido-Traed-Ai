"""Symbol DNA (spec phase 8, §7).

What an instrument *does*, measured rather than assumed: how volatile it is,
when it is volatile, how far it travels in a bar, whether its moves persist or
revert, and how it moves relative to other instruments.

Two rules shape every function here.

**Only what the data supports.** The spec lists eleven facets of Symbol DNA.
Six of them — strategy performance, failure patterns, news sensitivity,
execution profile, market memory, regime profile — cannot be computed from bars
alone; they need trade outcomes, a news feed, or the regime engine, none of
which exist yet. Those are reported as `unavailable` with the reason, not
approximated. A plausible-looking "news sensitivity: 0.42" invented from price
noise would be worse than an honest gap, because a later phase would build on
it.

**Everything reads through `get_bars()`.** A profile is a historical claim; if
it could see the future it would be a very good-looking lie.
"""

from __future__ import annotations

import math
import statistics
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import Timeframe, TradingSession
from app.core.errors import InsufficientDataError, ValidationFailedError
from app.core.logging import get_logger
from app.models.instruments import Instrument
from app.models.symbol_dna import SymbolProfile
from app.services.point_in_time import BarView, get_bars
from app.services.sessions import active_sessions

log = get_logger(__name__)

PROFILE_VERSION = 1

# Below this, percentiles and correlations are noise dressed as knowledge.
MIN_SAMPLES = 200
# Per-bucket floor (per session, per weekday). A profile for "Tokyo" built on
# nine bars is not a profile.
MIN_BUCKET_SAMPLES = 30

# Facets the spec asks for that bars alone cannot answer. Listed explicitly so
# the gap is visible in the API response rather than silently absent.
UNAVAILABLE: dict[str, str] = {
    "regime_profile": "needs the regime engine (phase 13)",
    "news_sensitivity": "needs a news/economic-calendar feed (phase 4 providers)",
    "strategy_performance": "needs strategy outcomes (phase 19+)",
    "failure_patterns": "needs trade outcomes (phase 29 journal)",
    "execution_profile": "needs real fills (phase 25+)",
    "market_memory": "needs the memory engine (phase 9)",
}


@dataclass
class Profile:
    kind: str
    data: dict[str, Any]
    sample_size: int
    coverage_start: datetime | None = None
    coverage_end: datetime | None = None
    warnings: list[str] = field(default_factory=list)


def _percentiles(values: list[float], points=(5, 25, 50, 75, 95)) -> dict[str, float]:
    ordered = sorted(values)
    out: dict[str, float] = {}
    for p in points:
        # Nearest-rank: no interpolation between observations, so every
        # reported number is a value the instrument actually printed.
        index = min(len(ordered) - 1, max(0, math.ceil(p / 100 * len(ordered)) - 1))
        out[f"p{p}"] = round(ordered[index], 10)
    return out


def _require(bars: list[BarView], minimum: int = MIN_SAMPLES) -> None:
    if len(bars) < minimum:
        raise InsufficientDataError(
            "Not enough history to characterise this instrument.",
            required=minimum,
            available=len(bars),
        )


# ------------------------------------------------------------------ facets
def volatility_profile(bars: list[BarView]) -> Profile:
    """How much this instrument moves, in scale-free terms.

    Ranges are expressed as a fraction of price so XAUUSD at 2000 and EURUSD at
    1.08 can sit in the same table without one drowning the other.
    """
    _require(bars)
    ranges = [(b.high - b.low) / b.close for b in bars if b.close > 0]
    returns = [
        math.log(b.close / a.close)
        for a, b in zip(bars, bars[1:], strict=False)
        if a.close > 0 and b.close > 0
    ]

    data: dict[str, Any] = {
        "bar_range_pct": _percentiles(ranges),
        "mean_bar_range_pct": round(statistics.fmean(ranges), 10),
        "return_stdev": round(statistics.pstdev(returns), 10) if len(returns) > 1 else None,
        "abs_return_pct": _percentiles([abs(r) for r in returns]) if returns else {},
    }
    return Profile(
        kind="volatility",
        data=data,
        sample_size=len(bars),
        coverage_start=bars[0].event_time,
        coverage_end=bars[-1].event_time,
    )


def session_profile(bars: list[BarView]) -> Profile:
    """Activity by liquidity session.

    Sessions overlap, so a bar can count toward both London and New York. That
    is deliberate: the overlap is a real market condition, and forcing each bar
    into one bucket would erase the busiest window of the day.
    """
    _require(bars)
    buckets: dict[str, list[float]] = {s.value: [] for s in TradingSession}

    for bar in bars:
        if bar.close <= 0:
            continue
        rng = (bar.high - bar.low) / bar.close
        for session in active_sessions(bar.event_time):
            buckets[session.value].append(rng)

    data: dict[str, Any] = {}
    warnings: list[str] = []
    for name, values in buckets.items():
        if len(values) < MIN_BUCKET_SAMPLES:
            if values:
                warnings.append(f"{name}: only {len(values)} bars, omitted")
            continue
        data[name] = {
            "bars": len(values),
            "share_of_bars": round(len(values) / len(bars), 4),
            "mean_range_pct": round(statistics.fmean(values), 10),
            "median_range_pct": round(statistics.median(values), 10),
        }

    if data:
        busiest = max(data, key=lambda k: data[k]["mean_range_pct"])
        data["busiest_session"] = busiest

    return Profile(
        kind="session",
        data=data,
        sample_size=len(bars),
        coverage_start=bars[0].event_time,
        coverage_end=bars[-1].event_time,
        warnings=warnings,
    )


def clock_profile(bars: list[BarView]) -> Profile:
    """Range by UTC hour and weekday — the instrument's daily/weekly rhythm."""
    _require(bars)
    by_hour: dict[int, list[float]] = {}
    by_weekday: dict[int, list[float]] = {}

    for bar in bars:
        if bar.close <= 0:
            continue
        rng = (bar.high - bar.low) / bar.close
        by_hour.setdefault(bar.event_time.hour, []).append(rng)
        by_weekday.setdefault(bar.event_time.weekday(), []).append(rng)

    def summarise(groups: dict[int, list[float]]) -> dict[str, dict[str, float]]:
        return {
            str(key): {
                "bars": len(values),
                "mean_range_pct": round(statistics.fmean(values), 10),
            }
            for key, values in sorted(groups.items())
            if len(values) >= MIN_BUCKET_SAMPLES
        }

    hours = summarise(by_hour)
    data: dict[str, Any] = {"by_utc_hour": hours, "by_weekday": summarise(by_weekday)}
    if hours:
        data["most_active_utc_hour"] = int(
            max(hours, key=lambda k: hours[k]["mean_range_pct"])
        )

    return Profile(
        kind="clock",
        data=data,
        sample_size=len(bars),
        coverage_start=bars[0].event_time,
        coverage_end=bars[-1].event_time,
    )


def structure_profile(bars: list[BarView]) -> Profile:
    """Does this instrument trend or revert, and how does it open?

    Lag-1 autocorrelation of returns is the honest, boring measure: positive
    means moves tend to continue, negative means they tend to reverse. It is
    reported with its sample size and nothing is concluded from it here —
    turning a number into a strategy is the strategy engine's job.
    """
    _require(bars)
    returns = [
        math.log(b.close / a.close)
        for a, b in zip(bars, bars[1:], strict=False)
        if a.close > 0 and b.close > 0
    ]
    if len(returns) < MIN_SAMPLES:
        raise InsufficientDataError(
            "Not enough returns for a structure profile.",
            required=MIN_SAMPLES,
            available=len(returns),
        )

    mean = statistics.fmean(returns)
    variance = statistics.pvariance(returns, mean)
    autocorr = None
    if variance > 0:
        covariance = statistics.fmean(
            [(a - mean) * (b - mean) for a, b in zip(returns, returns[1:], strict=False)]
        )
        autocorr = round(covariance / variance, 6)

    bodies = [
        abs(b.close - b.open) / (b.high - b.low)
        for b in bars
        if b.high > b.low
    ]
    gaps = [
        abs(b.open - a.close) / a.close
        for a, b in zip(bars, bars[1:], strict=False)
        if a.close > 0
    ]
    up = sum(1 for b in bars if b.close > b.open)

    data: dict[str, Any] = {
        "return_autocorrelation_lag1": autocorr,
        "tendency": (
            None
            if autocorr is None
            else "persistent" if autocorr > 0.05
            else "mean_reverting" if autocorr < -0.05
            else "neither"
        ),
        "up_bar_share": round(up / len(bars), 4),
        "body_ratio": _percentiles(bodies) if len(bodies) >= MIN_SAMPLES else {},
        "open_gap_pct": _percentiles(gaps) if len(gaps) >= MIN_SAMPLES else {},
    }
    return Profile(
        kind="structure",
        data=data,
        sample_size=len(bars),
        coverage_start=bars[0].event_time,
        coverage_end=bars[-1].event_time,
    )


def liquidity_profile(bars: list[BarView]) -> Profile:
    """Volume and spread, when the provider supplies them.

    Many FX feeds report tick volume rather than traded volume, and some report
    nothing at all. Reporting `available: false` is the correct answer there —
    inferring liquidity from range would be inventing a measurement.
    """
    _require(bars)
    volumes = [b.volume for b in bars if b.volume is not None and b.volume > 0]
    spreads = [b.spread for b in bars if b.spread is not None and b.spread >= 0]

    data: dict[str, Any] = {
        "volume": (
            {
                "available": True,
                "bars_with_volume": len(volumes),
                "percentiles": _percentiles(volumes),
                "mean": round(statistics.fmean(volumes), 6),
            }
            if len(volumes) >= MIN_SAMPLES
            else {"available": False, "reason": "provider reports no usable volume"}
        ),
        "spread": (
            {
                "available": True,
                "bars_with_spread": len(spreads),
                "percentiles": _percentiles(spreads),
            }
            if len(spreads) >= MIN_SAMPLES
            else {"available": False, "reason": "provider reports no spread on bars"}
        ),
    }
    return Profile(
        kind="liquidity",
        data=data,
        sample_size=len(bars),
        coverage_start=bars[0].event_time,
        coverage_end=bars[-1].event_time,
    )


def correlation_profile(
    session: Session,
    instrument_id: uuid.UUID,
    timeframe: Timeframe,
    as_of: datetime,
    *,
    peers: list[Instrument],
    lookback: int = 1000,
) -> Profile:
    """Return correlation against peer instruments.

    Correlations are computed on **time-aligned** returns only: bars are joined
    on `event_time`, not zipped by position. Two instruments with different
    trading calendars have different bar counts, and zipping them would
    correlate Monday against Tuesday and produce a confident, meaningless
    number.
    """
    base = get_bars(session, instrument_id, timeframe, as_of, lookback=lookback)
    _require(base)
    base_returns = _returns_by_time(base)

    pairs: dict[str, Any] = {}
    warnings: list[str] = []

    for peer in peers:
        if peer.id == instrument_id:
            continue
        peer_bars = get_bars(session, peer.id, timeframe, as_of, lookback=lookback)
        peer_returns = _returns_by_time(peer_bars)

        shared = sorted(set(base_returns) & set(peer_returns))
        if len(shared) < MIN_SAMPLES:
            warnings.append(
                f"{peer.symbol}: only {len(shared)} aligned bars, skipped"
            )
            continue

        xs = [base_returns[t] for t in shared]
        ys = [peer_returns[t] for t in shared]
        value = _pearson(xs, ys)
        if value is not None:
            pairs[peer.symbol] = {"correlation": round(value, 4), "aligned_bars": len(shared)}

    return Profile(
        kind="correlation",
        data={"pairs": pairs},
        sample_size=len(base),
        coverage_start=base[0].event_time,
        coverage_end=base[-1].event_time,
        warnings=warnings,
    )


def _returns_by_time(bars: list[BarView]) -> dict[datetime, float]:
    out: dict[datetime, float] = {}
    for previous, current in zip(bars, bars[1:], strict=False):
        if previous.close > 0 and current.close > 0:
            out[current.event_time] = math.log(current.close / previous.close)
    return out


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    mean_x, mean_y = statistics.fmean(xs), statistics.fmean(ys)
    sx = statistics.pstdev(xs, mean_x)
    sy = statistics.pstdev(ys, mean_y)
    if sx == 0 or sy == 0:
        return None  # a flat series has no correlation, not a correlation of 0
    covariance = statistics.fmean(
        [(x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)]
    )
    return covariance / (sx * sy)


# --------------------------------------------------------------- orchestration
BAR_PROFILES = {
    "volatility": volatility_profile,
    "session": session_profile,
    "clock": clock_profile,
    "structure": structure_profile,
    "liquidity": liquidity_profile,
}


def compute_dna(
    session: Session,
    instrument_id: uuid.UUID,
    timeframe: Timeframe,
    as_of: datetime,
    *,
    lookback: int = 5000,
    include_correlation: bool = True,
) -> dict[str, Profile]:
    """Every computable facet for one instrument at one knowledge cutoff."""
    if as_of.tzinfo is None:
        raise ValidationFailedError("as_of must be timezone-aware (UTC)")
    as_of = as_of.astimezone(UTC)

    bars = get_bars(session, instrument_id, timeframe, as_of, lookback=lookback)
    _require(bars)

    profiles: dict[str, Profile] = {}
    for kind, fn in BAR_PROFILES.items():
        try:
            profiles[kind] = fn(bars)
        except InsufficientDataError as exc:
            log.info("symbol_dna.facet_skipped", kind=kind, reason=exc.message)

    if include_correlation:
        peers = list(
            session.scalars(
                select(Instrument).where(
                    Instrument.id != instrument_id, Instrument.is_active.is_(True)
                )
            )
        )
        if peers:
            try:
                profiles["correlation"] = correlation_profile(
                    session, instrument_id, timeframe, as_of, peers=peers
                )
            except InsufficientDataError:
                pass

    return profiles


def persist_dna(
    session: Session,
    instrument_id: uuid.UUID,
    timeframe: Timeframe,
    as_of: datetime,
    profiles: dict[str, Profile],
) -> int:
    """Store profiles for this exact `as_of`, replacing only that snapshot.

    Snapshots at different cutoffs are kept side by side: overwriting history
    would hide the very drift these profiles exist to reveal.
    """
    written = 0
    now = datetime.now(UTC)

    for kind, profile in profiles.items():
        existing = session.scalar(
            select(SymbolProfile).where(
                SymbolProfile.instrument_id == instrument_id,
                SymbolProfile.timeframe == timeframe,
                SymbolProfile.kind == kind,
                SymbolProfile.profile_version == PROFILE_VERSION,
                SymbolProfile.as_of == as_of,
            )
        )
        payload = dict(profile.data)
        if profile.warnings:
            payload["_warnings"] = profile.warnings

        if existing is None:
            existing = SymbolProfile(
                instrument_id=instrument_id,
                timeframe=timeframe,
                kind=kind,
                profile_version=PROFILE_VERSION,
                as_of=as_of,
            )
            session.add(existing)
            written += 1

        existing.computed_at = now
        existing.sample_size = profile.sample_size
        existing.coverage_start = profile.coverage_start
        existing.coverage_end = profile.coverage_end
        existing.data = payload

    session.flush()
    return written


def latest_dna(
    session: Session,
    instrument_id: uuid.UUID,
    timeframe: Timeframe,
    as_of: datetime,
) -> dict[str, SymbolProfile]:
    """Most recent stored snapshot at or before `as_of`, per facet."""
    rows = session.scalars(
        select(SymbolProfile)
        .where(
            SymbolProfile.instrument_id == instrument_id,
            SymbolProfile.timeframe == timeframe,
            SymbolProfile.as_of <= as_of,
            SymbolProfile.computed_at <= as_of,
        )
        .order_by(SymbolProfile.as_of)
    )
    latest: dict[str, SymbolProfile] = {}
    for row in rows:
        latest[row.kind] = row  # ascending as_of -> last wins
    return latest
