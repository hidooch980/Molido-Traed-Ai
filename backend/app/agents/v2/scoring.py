"""Read-only V2 scorer. Off by default. Never overrides Risk Brain.

Consumes Key Levels, SP2L, Spike & Imbalance, and Pro BTB. Shared feature
families (spike, imbalance/FVG, retest, breakout) contribute once; every
contributing engine is listed. Weights are RESEARCH placeholders.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.agents.analyzers.bars import Candle
from app.agents.pro_btb.adapter import CONSUMERS as PRO_BTB_CONSUMERS
from app.agents.pro_btb.engine import ProBtbEngine
from app.agents.pro_btb.types import PipelineDecision
from app.agents.v2.key_levels.engine import KeyLevelsEngine, KeyLevelsReport
from app.agents.v2.key_levels.rounds import RoundNumberParams
from app.agents.v2.rules import scoring_counts
from app.agents.v2.sp2l.engine import Sp2lEngine, Sp2lReport
from app.agents.v2.spike_imbalance.engine import SpikeImbalanceEngine, SpikeImbalanceReport

ENV_FLAG = "MOLIDO_V2_ENGINES_ENABLED"
_RISK_KEYS = frozenset({
    "risk_decision", "risk_verdict", "risk_brain", "risk_approval_status",
    "risk_gate", "verdict",
})

# Same consumer names as the Pro BTB adapter, so existing hooks can switch
# to the combined payload without a new vocabulary.
CONSUMERS = PRO_BTB_CONSUMERS


def is_enabled(getenv=os.getenv) -> bool:
    raw = (getenv(ENV_FLAG) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Feature:
    family: str
    present: bool
    sources: tuple[str, ...]
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "family": self.family, "present": self.present,
            "sources": list(self.sources), "detail": self.detail,
        }


@dataclass(frozen=True)
class V2Score:
    enabled: bool
    consumer: str
    features: tuple[Feature, ...]
    score: float | None  # None when disabled; RESEARCH equal-weight when on
    may_override_risk_brain: bool = field(default=False)
    key_levels: dict[str, Any] | None = None
    sp2l: dict[str, Any] | None = None
    spike_imbalance: dict[str, Any] | None = None
    pro_btb: dict[str, Any] | None = None
    reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "consumer": self.consumer,
            "features": [f.as_dict() for f in self.features],
            "score": self.score,
            "score_status": "RESEARCH",
            "may_override_risk_brain": False,
            "key_levels": self.key_levels,
            "sp2l": self.sp2l,
            "spike_imbalance": self.spike_imbalance,
            "pro_btb": self.pro_btb,
            "reasons": list(self.reasons),
            "status_counts": scoring_counts(),
            "source": "v2.read_only",
        }


def _collect(
    kl: KeyLevelsReport, sp: Sp2lReport, si: SpikeImbalanceReport, btb,
) -> tuple[Feature, ...]:
    """One row per family. Multiple engines may be listed; the family counts once."""
    spike_sources = []
    if sp.spike is not None and sp.spike.valid:
        spike_sources.append("sp2l")
    if si.spikes:
        spike_sources.append("spike_imbalance")
    fvg_sources = []
    if si.open_imbalances:
        fvg_sources.append("spike_imbalance")
    # Pro BTB does not emit FVGs; no second copy to merge.
    retest_sources = []
    if sp.retest:
        retest_sources.append("sp2l")
    if btb.stages:
        retest_stage = next((s for s in btb.stages if s.stage == "btb_retest"), None)
        if retest_stage is not None and retest_stage.details.get("returned"):
            retest_sources.append("pro_btb")
    breakout_sources = []
    if sp.breakout:
        breakout_sources.append("sp2l")
    if any(r.kind == "breakout" for r in kl.reactions):
        breakout_sources.append("key_levels")
    if btb.confirmation_accepted:
        # A confirmed BTB already required a BO; do not also add a raw BO family
        # from the same event if SP2L already claimed breakout — still list both
        # under breakout only if we didn't already... we add pro_btb as a source.
        breakout_sources.append("pro_btb")
    key_sources = []
    if kl.reactions or (kl.round_numbers and any(r.kind == "major" and r.ticks_from_price == 0
                                                 for r in kl.round_numbers)):
        key_sources.append("key_levels")
    structure_sources = []
    if sp.hl_lh and len(sp.hl_lh) >= 2:
        structure_sources.append("sp2l")

    def feat(family: str, sources: list[str], detail: str) -> Feature:
        unique = tuple(dict.fromkeys(sources))  # preserve order, drop dupes
        return Feature(family, bool(unique), unique, detail)

    return (
        feat("spike", spike_sources, "directional ATR/P-Gap spike"),
        feat("imbalance_fvg", fvg_sources, "unmitigated FVG from the SMC adapter"),
        feat("retest", retest_sources, "return to a level or BTB zone"),
        feat("breakout", breakout_sources, "close beyond a prior extreme or daily H/L"),
        feat(
            "key_level_reaction", key_sources,
            "reaction at a completed daily level or exact major",
        ),
        feat("structure", structure_sources, "HL/LH sequence inside the spike"),
    )


def _equal_weight_score(features: Sequence[Feature]) -> float:
    """RESEARCH placeholder: present families / all families. Not a ranking claim."""
    if not features:
        return 0.0
    return sum(1 for f in features if f.present) / len(features)


def read_only_v2_input(
    consumer: str,
    bars: Sequence[Candle],
    *,
    as_of: datetime,
    symbol: str = "UNKNOWN",
    timeframe: str = "H1",
    bar_delta: timedelta | None = None,
    rounds: RoundNumberParams | None = None,
    enabled: bool | None = None,
) -> V2Score:
    if consumer not in CONSUMERS:
        raise ValueError(f"unknown V2 consumer: {consumer}")
    if enabled is None:
        enabled = is_enabled()
    if not enabled:
        return V2Score(
            enabled=False, consumer=consumer, features=(), score=None,
            may_override_risk_brain=False, reasons=("adapter disabled",),
        )
    delta = bar_delta or timedelta(hours=1)
    kl = KeyLevelsEngine(delta).run(bars, as_of=as_of, rounds=rounds)
    visible = [b for b in bars if b.open_time + delta <= as_of]
    sp = Sp2lEngine().run(visible, as_of=as_of)
    si = SpikeImbalanceEngine().run(visible)
    btb = ProBtbEngine().run(visible, as_of=as_of, symbol=symbol, timeframe=timeframe)
    features = _collect(kl, sp, si, btb)
    present = [f.family for f in features if f.present]
    reasons = [
        f"unique families present: {', '.join(present) or 'none'}",
        "each family counted once; sources listed on the feature",
        "score is an equal-weight RESEARCH placeholder, not a trade permission",
    ]
    if btb.decision is PipelineDecision.STOP:
        reasons.append("Pro BTB pipeline stopped; it does not raise the score on its own")
    return V2Score(
        enabled=True,
        consumer=consumer,
        features=features,
        score=_equal_weight_score(features),
        may_override_risk_brain=False,
        key_levels=kl.as_dict(),
        sp2l=sp.as_dict(),
        spike_imbalance=si.as_dict(),
        pro_btb=btb.as_dict(),
        reasons=tuple(reasons),
    )


def merge_into_extras(extras: Mapping[str, Any] | None, payload: V2Score) -> dict[str, Any]:
    out = dict(extras or {})
    reserved = {k: out[k] for k in _RISK_KEYS if k in out}
    out["v2_engines"] = payload.as_dict()
    out.update(reserved)
    return out
