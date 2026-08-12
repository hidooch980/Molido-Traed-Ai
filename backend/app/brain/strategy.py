"""Strategy engine (spec phase 19, §18).

Modular strategy families, each regime-aware, each declaring the conditions it
needs. A strategy here answers one question — *does my setup exist in this
world state?* — and nothing else. It does not size, does not authorize, and
does not decide whether the trade is worth taking.

**Regime-awareness is a refusal, not a discount.** A mean-reversion strategy in
a strong trend does not return a weaker signal; it returns nothing. Letting a
strategy fire everywhere and shrinking its weight afterwards is how a system
ends up trading its worst setups in its worst conditions.

**A strategy fires or it does not.** There is no partial match. A setup that
"almost" exists is not a setup, and encoding "almost" is how thresholds erode
until every bar qualifies.

Strategies are deterministic and declared, not discovered. When the research
loop starts proposing them, they will carry a different `origin` and their
performance will be tracked separately from these.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.core.enums import Decision, Regime

ORIGIN = "declared"


@dataclass
class Setup:
    """One strategy's reading of one world state."""

    strategy: str
    family: str
    fired: bool
    direction: Decision = Decision.WAIT
    reason: str = ""
    conditions_met: list[str] = field(default_factory=list)
    conditions_failed: list[str] = field(default_factory=list)
    suitable_regimes: list[str] = field(default_factory=list)
    origin: str = ORIGIN
    version: int = 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "family": self.family,
            "fired": self.fired,
            "direction": self.direction.value,
            "reason": self.reason,
            "conditions_met": self.conditions_met,
            "conditions_failed": self.conditions_failed,
            "suitable_regimes": self.suitable_regimes,
            "origin": self.origin,
            "version": self.version,
        }


StrategyFn = Callable[[dict], Setup]
_REGISTRY: dict[str, StrategyFn] = {}


def strategy(name: str) -> Callable[[StrategyFn], StrategyFn]:
    def wrap(fn: StrategyFn) -> StrategyFn:
        _REGISTRY[name] = fn
        return fn

    return wrap


def names() -> list[str]:
    return sorted(_REGISTRY)


def _features(state: dict) -> dict:
    block = state.get("features", {})
    return block.get("values", {}) if block.get("available") else {}


def _regime(state: dict) -> str:
    return (state.get("regime") or {}).get("regime", Regime.UNCERTAIN.value)


def _wrong_regime(name: str, family: str, suitable: list[str], actual: str) -> Setup:
    return Setup(
        strategy=name,
        family=family,
        fired=False,
        reason=f"regime is {actual}; this strategy only applies in {', '.join(suitable)}",
        suitable_regimes=suitable,
    )


# ---------------------------------------------------------------- strategies
@strategy("trend_pullback")
def trend_pullback(state: dict) -> Setup:
    """Buy a dip inside an established uptrend (or mirror for downtrend)."""
    suitable = [Regime.TREND_UP.value, Regime.TREND_DOWN.value]
    regime = _regime(state)
    if regime not in suitable:
        return _wrong_regime("trend_pullback", "trend_following", suitable, regime)

    f = _features(state)
    rsi, cos = f.get("rsi_14"), f.get("close_over_sma_20")
    if rsi is None or cos is None:
        return Setup(
            "trend_pullback", "trend_following", False,
            reason="RSI or trend position unavailable", suitable_regimes=suitable,
        )

    met: list[str] = []
    failed: list[str] = []
    up = regime == Regime.TREND_UP.value

    if up:
        (met if cos > 1 else failed).append("price above its 20-bar average")
        (met if 40 <= rsi <= 60 else failed).append("RSI pulled back into 40-60")
    else:
        (met if cos < 1 else failed).append("price below its 20-bar average")
        (met if 40 <= rsi <= 60 else failed).append("RSI recovered into 40-60")

    fired = not failed
    return Setup(
        "trend_pullback", "trend_following", fired,
        direction=(Decision.BUY if up else Decision.SELL) if fired else Decision.WAIT,
        reason="pullback within an established trend" if fired else "conditions not met",
        conditions_met=met, conditions_failed=failed, suitable_regimes=suitable,
    )


@strategy("range_fade")
def range_fade(state: dict) -> Setup:
    """Fade the edge of an established range."""
    suitable = [Regime.RANGE.value]
    regime = _regime(state)
    if regime not in suitable:
        return _wrong_regime("range_fade", "mean_reversion", suitable, regime)

    f = _features(state)
    position, rsi = f.get("position_in_range_20"), f.get("rsi_14")
    if position is None or rsi is None:
        return Setup(
            "range_fade", "mean_reversion", False,
            reason="range position or RSI unavailable", suitable_regimes=suitable,
        )

    met: list[str] = []
    failed: list[str] = []
    at_top = position >= 0.85
    at_bottom = position <= 0.15

    if at_top:
        met.append(f"price at the top of its range ({position:.0%})")
        (met if rsi >= 65 else failed).append("RSI confirms the extreme")
    elif at_bottom:
        met.append(f"price at the bottom of its range ({position:.0%})")
        (met if rsi <= 35 else failed).append("RSI confirms the extreme")
    else:
        failed.append("price is not at a range extreme")

    fired = bool(met) and not failed
    return Setup(
        "range_fade", "mean_reversion", fired,
        direction=(Decision.SELL if at_top else Decision.BUY) if fired else Decision.WAIT,
        reason="fading a range extreme" if fired else "conditions not met",
        conditions_met=met, conditions_failed=failed, suitable_regimes=suitable,
    )


@strategy("breakout_continuation")
def breakout_continuation(state: dict) -> Setup:
    """Join a breakout that volatility confirms."""
    suitable = [Regime.BREAKOUT.value]
    regime = _regime(state)
    if regime not in suitable:
        return _wrong_regime("breakout_continuation", "breakout", suitable, regime)

    f = _features(state)
    position = f.get("position_in_range_20")
    if position is None:
        return Setup(
            "breakout_continuation", "breakout", False,
            reason="range position unavailable", suitable_regimes=suitable,
        )

    met = [f"price at a range extreme ({position:.0%})"]
    failed: list[str] = []

    # The regime engine only calls a breakout when volatility is expanding, so
    # that condition is already carried; re-checking it here would double-count
    # the same evidence.
    memory = (state.get("memory") or {}).get("horizons", {})
    short = memory.get("short", {})
    if short.get("available") and short.get("trend") in ("up", "down"):
        met.append(f"short horizon agrees ({short['trend']})")
    else:
        failed.append("no short-horizon direction to join")

    fired = not failed
    return Setup(
        "breakout_continuation", "breakout", fired,
        direction=(
            Decision.BUY if position >= 0.5 else Decision.SELL
        ) if fired else Decision.WAIT,
        reason="breakout with volatility expansion" if fired else "conditions not met",
        conditions_met=met, conditions_failed=failed, suitable_regimes=suitable,
    )


@strategy("volatility_stand_aside")
def volatility_stand_aside(state: dict) -> Setup:
    """A strategy whose setup is *not trading*.

    The spec asks for a dedicated no-trade engine (§26). Encoding stand-aside
    as a first-class strategy means the reason for inaction is recorded in the
    same place and format as the reason for action, instead of being an absence
    nobody can audit.
    """
    suitable = [Regime.HIGH_VOLATILITY.value, Regime.UNCERTAIN.value]
    regime = _regime(state)
    if regime not in suitable:
        return _wrong_regime("volatility_stand_aside", "no_trade", suitable, regime)

    return Setup(
        "volatility_stand_aside", "no_trade", True,
        direction=Decision.WAIT,
        reason=f"regime is {regime}: the setup here is to take no position",
        conditions_met=[f"regime {regime}"],
        suitable_regimes=suitable,
    )


def evaluate(state: dict) -> list[Setup]:
    """Run every strategy against one world state."""
    return [_REGISTRY[name](state) for name in names()]


def fired(state: dict) -> list[Setup]:
    return [s for s in evaluate(state) if s.fired]
