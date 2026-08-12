"""Historical similarity engine (spec phase 11, §10).

Answers one question: *when this market looked like it looks now, what
happened next?*

The mechanism is a nearest-neighbour search over matured episodes, but the
value is entirely in the guardrails — a similarity engine without them is a
machine for producing confident nonsense.

**Three leaks this module is built to prevent.**

1. *Outcome leakage.* Only episodes whose forward window closed at or before
   `as_of` are searchable. Phase 10's maturity gate does this; here it is
   simply never bypassed.

2. *Normalisation leakage.* Features live on wildly different scales — RSI runs
   0–100, a one-bar log return is ~0.0001 — so distances mean nothing until
   each feature is standardised. The obvious implementation computes those
   scaling statistics over the whole table, which quietly injects the *future*
   distribution of every feature into a past decision. Here the statistics are
   computed from the visible episodes only, so the scale a decision uses is the
   scale it could have known.

3. *False confidence.* Too few neighbours, or neighbours that are not actually
   close, produce an explicit `insufficient` result rather than a percentage.
   "70% of matches rose" over four episodes is four coin flips wearing a
   statistic.

Distance is robust (median / IQR) rather than mean / standard deviation: a
single volatility spike in the history would otherwise stretch the scale and
make every ordinary bar look identical to every other.
"""

from __future__ import annotations

import math
import statistics
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import Timeframe
from app.core.errors import ValidationFailedError
from app.core.logging import get_logger
from app.models.episodes import Episode
from app.services import episodes as episode_service
from app.services import feature_store

log = get_logger(__name__)

# Below this many matured episodes there is nothing to search.
MIN_LIBRARY = 50
# Below this many neighbours, no outcome statistics are reported.
MIN_MATCHES = 20
# Neighbours further than this (in normalised units, averaged per feature) are
# not "similar" in any useful sense and are dropped even if they are the
# closest available. A nearest neighbour is not automatically a near one.
MAX_MEAN_DISTANCE = 2.0


@dataclass
class Match:
    episode: Episode
    distance: float
    similarity: float
    compared_features: int


@dataclass
class SimilarityResult:
    sufficient: bool
    reason: str | None = None
    as_of: datetime | None = None
    library_size: int = 0
    matches: list[Match] = field(default_factory=list)
    outcome: dict[str, Any] = field(default_factory=dict)
    uncertainty: dict[str, Any] = field(default_factory=dict)
    features_used: list[str] = field(default_factory=list)

    def as_payload(self) -> dict[str, Any]:
        return {
            "sufficient": self.sufficient,
            "reason": self.reason,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "library_size": self.library_size,
            "match_count": len(self.matches),
            "features_used": self.features_used,
            "outcome": self.outcome,
            "uncertainty": self.uncertainty,
            "matches": [
                {
                    "event_time": m.episode.event_time.isoformat(),
                    "similarity": round(m.similarity, 4),
                    "distance": round(m.distance, 4),
                    "compared_features": m.compared_features,
                    "forward_return_pct": (
                        float(m.episode.forward_return_pct)
                        if m.episode.forward_return_pct is not None
                        else None
                    ),
                    "max_up_pct": (
                        float(m.episode.max_up_pct)
                        if m.episode.max_up_pct is not None
                        else None
                    ),
                    "max_down_pct": (
                        float(m.episode.max_down_pct)
                        if m.episode.max_down_pct is not None
                        else None
                    ),
                }
                for m in self.matches[:50]
            ],
        }


@dataclass
class Scaler:
    """Per-feature median and IQR, learned from the visible library only."""

    center: dict[str, float]
    spread: dict[str, float]

    @staticmethod
    def fit(library: list[Episode]) -> Scaler:
        values: dict[str, list[float]] = {}
        for ep in library:
            for name, value in (ep.features or {}).items():
                if isinstance(value, int | float):
                    values.setdefault(name, []).append(float(value))

        center: dict[str, float] = {}
        spread: dict[str, float] = {}
        for name, series in values.items():
            if len(series) < MIN_MATCHES:
                continue  # too thin to scale honestly; the feature is skipped
            ordered = sorted(series)
            q1 = ordered[len(ordered) // 4]
            q3 = ordered[(3 * len(ordered)) // 4]
            iqr = q3 - q1
            if iqr <= 0:
                # A feature that never varies carries no information about
                # similarity, and dividing by its spread would be a zero
                # division dressed as insight.
                continue
            center[name] = statistics.median(ordered)
            spread[name] = iqr

        return Scaler(center=center, spread=spread)

    @property
    def features(self) -> list[str]:
        return sorted(self.center)

    def normalise(self, values: dict[str, float | None]) -> dict[str, float]:
        out: dict[str, float] = {}
        for name, value in values.items():
            if value is None or name not in self.center:
                continue
            out[name] = (float(value) - self.center[name]) / self.spread[name]
        return out


def _distance(a: dict[str, float], b: dict[str, float]) -> tuple[float, int]:
    """Mean per-feature distance over the features both sides actually have.

    Averaging rather than summing keeps episodes with a missing feature
    comparable to complete ones: a sum would make an incomplete episode look
    artificially *closer* simply for having fewer terms.
    """
    shared = a.keys() & b.keys()
    if not shared:
        return math.inf, 0
    total = sum((a[k] - b[k]) ** 2 for k in shared)
    return math.sqrt(total / len(shared)), len(shared)


def find_similar(
    session: Session,
    instrument_id: uuid.UUID,
    timeframe: Timeframe,
    as_of: datetime,
    *,
    k: int = 50,
    horizon_bars: int | None = None,
    feature_names: list[str] | None = None,
    library_limit: int = 5000,
) -> SimilarityResult:
    """Find historical moments that resemble the state at `as_of`."""
    if as_of.tzinfo is None:
        raise ValidationFailedError("as_of must be timezone-aware (UTC)")
    as_of = as_of.astimezone(UTC)

    library = episode_service.query(
        session,
        instrument_id,
        timeframe,
        as_of,
        horizon_bars=horizon_bars,
        limit=library_limit,
    )
    if len(library) < MIN_LIBRARY:
        return SimilarityResult(
            sufficient=False,
            as_of=as_of,
            library_size=len(library),
            reason=f"library has {len(library)} matured episodes, needs {MIN_LIBRARY}",
        )

    scaler = Scaler.fit(library)
    if not scaler.features:
        return SimilarityResult(
            sufficient=False,
            as_of=as_of,
            library_size=len(library),
            reason="no feature varies enough across the library to compare on",
        )

    try:
        current = feature_store.compute_at(
            session, instrument_id, timeframe, as_of, feature_names=feature_names
        )
    except Exception as exc:  # noqa: BLE001 - a missing present is not a crash
        return SimilarityResult(
            sufficient=False,
            as_of=as_of,
            library_size=len(library),
            reason=f"cannot describe the present: {exc}",
        )

    target = scaler.normalise(current.values)
    if not target:
        return SimilarityResult(
            sufficient=False,
            as_of=as_of,
            library_size=len(library),
            reason="current state has no comparable features",
        )

    scored: list[Match] = []
    for ep in library:
        vector = scaler.normalise(ep.features or {})
        distance, shared = _distance(target, vector)
        if shared == 0 or not math.isfinite(distance):
            continue
        if distance > MAX_MEAN_DISTANCE:
            continue
        scored.append(
            Match(
                episode=ep,
                distance=distance,
                # A bounded, monotone transform. Not a probability, and not
                # labelled as one.
                similarity=1.0 / (1.0 + distance),
                compared_features=shared,
            )
        )

    scored.sort(key=lambda m: m.distance)
    matches = scored[:k]

    if len(matches) < MIN_MATCHES:
        return SimilarityResult(
            sufficient=False,
            as_of=as_of,
            library_size=len(library),
            matches=matches,
            features_used=scaler.features,
            reason=(
                f"only {len(matches)} episodes were close enough "
                f"(mean distance <= {MAX_MEAN_DISTANCE})"
            ),
        )

    return SimilarityResult(
        sufficient=True,
        as_of=as_of,
        library_size=len(library),
        matches=matches,
        features_used=scaler.features,
        outcome=_outcome(matches),
        uncertainty=_uncertainty(matches),
    )


def _outcome(matches: list[Match]) -> dict[str, Any]:
    forwards = [
        float(m.episode.forward_return_pct)
        for m in matches
        if m.episode.forward_return_pct is not None
    ]
    ups = [float(m.episode.max_up_pct) for m in matches if m.episode.max_up_pct is not None]
    downs = [
        float(m.episode.max_down_pct) for m in matches if m.episode.max_down_pct is not None
    ]
    if not forwards:
        return {"available": False, "reason": "matched episodes carry no outcome"}

    positive = sum(1 for f in forwards if f > 0)
    return {
        "available": True,
        "count": len(forwards),
        "positive_share": round(positive / len(forwards), 4),
        "median_forward_return": round(statistics.median(forwards), 8),
        "mean_max_up": round(statistics.fmean(ups), 8) if ups else None,
        "mean_max_down": round(statistics.fmean(downs), 8) if downs else None,
    }


def _uncertainty(matches: list[Match]) -> dict[str, Any]:
    """How much the matched outcomes disagree with each other.

    Reported as dispersion, never as a confidence figure. Twenty episodes that
    all rose and twenty that split evenly can share a median; only the spread
    tells them apart, and that difference is the whole decision.
    """
    forwards = [
        float(m.episode.forward_return_pct)
        for m in matches
        if m.episode.forward_return_pct is not None
    ]
    if len(forwards) < MIN_MATCHES:
        return {"available": False}

    ordered = sorted(forwards)
    q1 = ordered[len(ordered) // 4]
    q3 = ordered[(3 * len(ordered)) // 4]
    distances = [m.distance for m in matches]

    return {
        "available": True,
        "outcome_iqr": round(q3 - q1, 8),
        "outcome_stdev": round(statistics.pstdev(forwards), 8),
        "p25_forward_return": round(q1, 8),
        "p75_forward_return": round(q3, 8),
        "mean_match_distance": round(statistics.fmean(distances), 4),
        "worst_match_distance": round(max(distances), 4),
    }
