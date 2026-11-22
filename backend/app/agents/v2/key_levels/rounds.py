"""Tick-aligned major and minor round numbers. Default steps are RESEARCH."""

from __future__ import annotations

from dataclasses import dataclass

from app.agents.pro_btb.status import RuleStatus


@dataclass(frozen=True)
class RoundLevel:
    price: float
    kind: str  # "major" or "minor"
    ticks_from_price: int

    def as_dict(self) -> dict:
        return {"price": self.price, "kind": self.kind,
                "ticks_from_price": self.ticks_from_price}


@dataclass(frozen=True)
class RoundNumberParams:
    tick_size: float
    major_step: float
    minor_step: float
    radius_steps: int = 8  # how many minor steps either side of price
    step_status: RuleStatus = RuleStatus.RESEARCH

    def __post_init__(self) -> None:
        if self.tick_size <= 0 or self.major_step <= 0 or self.minor_step <= 0:
            raise ValueError("tick and step sizes must be positive")
        if self.major_step < self.minor_step:
            raise ValueError("major_step must be >= minor_step")
        # Steps must be integer tick multiples so levels sit on the grid.
        for name, step in (("major_step", self.major_step), ("minor_step", self.minor_step)):
            n = round(step / self.tick_size)
            if abs(n * self.tick_size - step) > self.tick_size * 1e-9:
                raise ValueError(f"{name} must be an integer multiple of tick_size")


def _snap(value: float, step: float) -> float:
    return round(round(value / step) * step, 12)


def nearby_round_numbers(price: float, params: RoundNumberParams) -> tuple[RoundLevel, ...]:
    """Levels within radius_steps minor steps of price, tick-aligned, unique."""
    tick = params.tick_size
    centre = _snap(price, params.minor_step)
    out: list[RoundLevel] = []
    seen: set[float] = set()
    for i in range(-params.radius_steps, params.radius_steps + 1):
        raw = centre + i * params.minor_step
        level = _snap(raw, tick)
        if level in seen:
            continue
        seen.add(level)
        major = abs(_snap(level, params.major_step) - level) <= tick * 0.5
        ticks = int(round(abs(level - price) / tick))
        out.append(RoundLevel(level, "major" if major else "minor", ticks))
    return tuple(sorted(out, key=lambda item: (item.ticks_from_price, item.price)))
