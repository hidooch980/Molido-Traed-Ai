"""Configurable thresholds. Every value is RESEARCH unless a source names it.

These numbers let the detectors run deterministically in tests. They are not
final Pro BTB rules and must not be presented as such.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agents.pro_btb.status import RuleStatus

PARAM_STATUS = RuleStatus.RESEARCH


@dataclass(frozen=True)
class ProBtbParams:
    """All numeric knobs. Status of every field: RESEARCH."""

    atr_period: int = 14
    swing_k: int = 2
    min_history_bars: int = 20
    min_leg_bars: int = 3
    min_leg_atr: float = 1.5
    min_body_ratio: float = 0.45
    max_overlap_ratio: float = 0.55
    extended_leg_atr: float = 4.0
    max_single_bar_share: float = 0.7
    close_extreme_frac: float = 0.25
    min_bars_after_bo: int = 1
    microchannel_bars: int = 3
    spike_max_bars: int = 5
    spike_min_atr: float = 1.8
    spike_max_overlap: float = 0.35
    channel_min_bars: int = 5
    channel_max_overlap: float = 0.7
    range_min_overlap: float = 0.55
    range_two_sided_max: float = 0.35  # |up_share - 0.5| below this => two-sided

    def __post_init__(self) -> None:
        if self.atr_period < 1 or self.swing_k < 1 or self.min_history_bars < 3:
            raise ValueError("history and indicator windows must be positive")
        if not 0 < self.close_extreme_frac <= 0.5:
            raise ValueError("close_extreme_frac must be in (0, 0.5]")
        if self.microchannel_bars < 2:
            raise ValueError("a microchannel needs at least two bars")
