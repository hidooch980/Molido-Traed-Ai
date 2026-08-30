"""Regime engine (spec phase 13, §12).

Classifies the market into one of the spec's regimes from measurements that
already exist — volatility percentiles from Symbol DNA, trend strength from
market memory, range position and ATR from the feature store.

Three commitments, all of which cost accuracy on paper and buy safety in
practice.

**UNCERTAIN is an answer.** The spec requires risk to fall when regime
confidence drops. An engine that always names a regime makes that impossible,
so this one refuses when the evidence is thin or the readings disagree.

**Classification is deterministic and rule-based, not learned.** Every output
carries `method: "rule_based"`. Nothing here is trained, so nothing here should
be described as a model. When a learned classifier arrives it will report a
different method, and the difference will be visible in the audit trail.

**Confidence is a stated margin, not a probability.** It measures how far the
winning reading was ahead of the runner-up. Calling it a probability would
imply a calibration that does not exist — that machinery is phase 20, and it
needs outcomes this engine has not yet accumulated.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import Regime, Timeframe
from app.core.errors import InsufficientDataError
from app.services import feature_store, market_memory, symbol_dna
from app.services.market_memory import MemoryHorizon

METHOD = "rule_based"
CLASSIFIER_VERSION = 1

# A regime claim needs this much separation from the runner-up before it is
# stated rather than reported as uncertain.
MIN_MARGIN = 0.15


@dataclass
class RegimeScore:
    regime: Regime
    score: float
    evidence: list[str] = field(default_factory=list)


@dataclass
class RegimeResult:
    regime: Regime
    confidence: float
    method: str = METHOD
    version: int = CLASSIFIER_VERSION
    as_of: datetime | None = None
    scores: list[RegimeScore] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "regime": self.regime.value,
            "confidence": round(self.confidence, 4),
            "method": self.method,
            "version": self.version,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "evidence": self.evidence,
            "missing_inputs": self.missing,
            "reason": self.reason,
            "scores": [
                {
                    "regime": s.regime.value,
                    "score": round(s.score, 4),
                    "evidence": s.evidence,
                }
                for s in sorted(self.scores, key=lambda x: -x.score)
            ],
        }


def _uncertain(reason: str, missing: list[str] | None = None) -> RegimeResult:
    return RegimeResult(
        regime=Regime.UNCERTAIN,
        confidence=0.0,
        reason=reason,
        missing=missing or [],
    )


def classify(
    session: Session,
    instrument_id: uuid.UUID,
    timeframe: Timeframe,
    as_of: datetime | None = None,
    memory: dict | None = None,
) -> RegimeResult:
    """Name the regime at `as_of`, or refuse to.

    `memory` is the same optimisation as in `world_state.build`: the horizons
    are a pure function of the cutoff, and a caller doing both used to read
    several thousand bars twice. Snapshots from a different cutoff would name
    this instant's regime from another instant's memory, so only a caller that
    recalled at this exact `as_of` may pass them.
    """
    cutoff = (as_of or datetime.now(UTC)).astimezone(UTC)
    missing: list[str] = []

    try:
        features = feature_store.compute_at(session, instrument_id, timeframe, cutoff).values
    except InsufficientDataError as exc:
        return _uncertain(f"features unavailable: {exc.message}", ["features"])

    horizons = memory or market_memory.recall_all(
        session, instrument_id, timeframe, cutoff
    )
    short = horizons[MemoryHorizon.SHORT]
    medium = horizons[MemoryHorizon.MEDIUM]
    if not short.available:
        missing.append("short_memory")

    profiles = symbol_dna.latest_dna(session, instrument_id, timeframe, cutoff)
    vol_profile = profiles.get("volatility")
    if vol_profile is None:
        missing.append("volatility_profile")

    atr_pct = features.get("atr_14_pct")
    position = features.get("position_in_range_20")
    close_over_sma = features.get("close_over_sma_20")
    rsi = features.get("rsi_14")

    if atr_pct is None or position is None:
        return _uncertain("core features could not be computed", [*missing, "atr_or_range"])

    scores: list[RegimeScore] = []
    percentiles = (vol_profile.data or {}).get("bar_range_pct", {}) if vol_profile else {}
    p25, p75 = percentiles.get("p25"), percentiles.get("p75")

    # Volatility, measured against this instrument's own history. A fixed
    # threshold would call every crypto "high volatility" and every JPY cross
    # "low"; the percentile makes the claim relative to what this instrument
    # normally does.
    if p25 is not None and p75 is not None:
        if atr_pct >= p75:
            scores.append(
                RegimeScore(
                    Regime.HIGH_VOLATILITY,
                    min(1.0, 0.5 + (atr_pct - p75) / max(p75, 1e-9)),
                    [f"ATR% {atr_pct:.5f} at or above its own p75 {p75:.5f}"],
                )
            )
        elif atr_pct <= p25:
            scores.append(
                RegimeScore(
                    Regime.LOW_VOLATILITY,
                    min(1.0, 0.5 + (p25 - atr_pct) / max(p25, 1e-9)),
                    [f"ATR% {atr_pct:.5f} at or below its own p25 {p25:.5f}"],
                )
            )

    # Trend, taken from the short horizon's earned label rather than re-derived.
    if short.available and short.trend_strength is not None:
        strength = abs(short.trend_strength)
        if short.trend == "up":
            scores.append(
                RegimeScore(
                    Regime.TREND_UP,
                    min(1.0, strength / 3.0),
                    [f"short-horizon trend strength +{short.trend_strength:.2f}"],
                )
            )
        elif short.trend == "down":
            scores.append(
                RegimeScore(
                    Regime.TREND_DOWN,
                    min(1.0, strength / 3.0),
                    [f"short-horizon trend strength {short.trend_strength:.2f}"],
                )
            )
        else:
            scores.append(
                RegimeScore(
                    Regime.RANGE,
                    min(1.0, 1.0 - strength),
                    [
                        "short-horizon move stayed within its own noise "
                        f"({short.trend_strength:.2f})"
                    ],
                )
            )

    if 0.35 <= position <= 0.65:
        scores.append(
            RegimeScore(
                Regime.RANGE,
                0.4 + (1 - abs(position - 0.5) * 4) * 0.2,
                [f"price sits mid-range ({position:.2f})"],
            )
        )
    elif position >= 0.95 or position <= 0.05:
        # An edge alone is not a breakout: price can sit at the top of a range
        # for days. Volatility expansion is what separates the two.
        expanding = p75 is not None and atr_pct >= p75
        if expanding:
            scores.append(
                RegimeScore(
                    Regime.BREAKOUT,
                    0.7,
                    [
                        f"price at range extreme ({position:.2f})",
                        "with volatility above its own p75",
                    ],
                )
            )
        else:
            scores.append(
                RegimeScore(
                    Regime.RANGE,
                    0.35,
                    [
                        f"price at range extreme ({position:.2f})",
                        "but volatility is not expanding, so an edge is not a breakout",
                    ],
                )
            )

    if short.available and medium.available and short.trend and medium.trend:
        if {short.trend, medium.trend} == {"up", "down"}:
            scores.append(
                RegimeScore(
                    Regime.REVERSAL,
                    0.5,
                    [f"short horizon {short.trend} against medium horizon {medium.trend}"],
                )
            )

    # Momentum extremes reinforce an existing trend reading; they never create
    # one on their own, because an extreme RSI in a range is noise.
    if rsi is not None and close_over_sma is not None:
        for s in scores:
            if rsi >= 70 and close_over_sma > 1 and s.regime == Regime.TREND_UP:
                s.score = min(1.0, s.score + 0.1)
                s.evidence.append(f"RSI {rsi:.0f} with price above its 20-bar average")
            elif rsi <= 30 and close_over_sma < 1 and s.regime == Regime.TREND_DOWN:
                s.score = min(1.0, s.score + 0.1)
                s.evidence.append(f"RSI {rsi:.0f} with price below its 20-bar average")

    if not scores:
        return _uncertain("no rule produced a reading", missing)

    merged: dict[Regime, RegimeScore] = {}
    for s in scores:
        current = merged.get(s.regime)
        if current is None or s.score > current.score:
            merged[s.regime] = RegimeScore(
                s.regime,
                s.score,
                list(s.evidence),
            )
        else:
            current.evidence.extend(s.evidence)

    ranked = sorted(merged.values(), key=lambda x: -x.score)

    # Structural market regimes compete with structural regimes.
    # Volatility is context and must not invalidate an otherwise valid
    # structural classification such as RANGE or TREND_UP.
    structural_regimes = {
        Regime.TREND_UP,
        Regime.TREND_DOWN,
        Regime.RANGE,
        Regime.BREAKOUT,
        Regime.REVERSAL,
    }

    structural = [s for s in ranked if s.regime in structural_regimes]

    # Prefer structural classification whenever one exists.
    # Volatility remains visible in `scores` as supporting context.
    candidates = structural if structural else ranked

    best = candidates[0]
    runner_up = candidates[1].score if len(candidates) > 1 else 0.0
    margin = best.score - runner_up

    if len(candidates) > 1 and margin < MIN_MARGIN:
        runner_name = candidates[1].regime.value
        result = _uncertain(
            f"top two structural readings are "
            f"{best.regime.value} and {runner_name}, "
            f"{margin:.4f} apart, below the {MIN_MARGIN:.2f} margin",
            missing,
        )
        result.as_of = cutoff
        result.scores = ranked
        return result

    # With only one structural reading there is no runner-up margin.
    # Use the rule score itself as confidence instead of manufacturing
    # certainty from `best.score - 0`.
    confidence = (
        min(1.0, best.score)
        if len(candidates) == 1
        else min(1.0, margin * 2)
    )

    return RegimeResult(
        regime=best.regime,
        # The margin, scaled — explicitly not a probability.
        confidence=confidence,
        as_of=cutoff,
        scores=ranked,
        evidence=best.evidence,
        missing=missing,
    )
