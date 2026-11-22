"""Market Key Levels engine. Shadow only. No orders."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.agents.analyzers.bars import Candle
from app.agents.v2.key_levels.calendar import visible_bars
from app.agents.v2.key_levels.daily import (
    DayRange,
    LevelReaction,
    completed_day,
    developing_day,
    previous_ny_close,
    reactions_to_completed,
)
from app.agents.v2.key_levels.rounds import RoundLevel, RoundNumberParams, nearby_round_numbers
from app.agents.v2.key_levels.stubs import ResearchStub, valid_break_even_stub, weekly_map_stub
from app.agents.v2.rules import KEY_LEVEL_BY_ID, key_level_counts


@dataclass(frozen=True)
class KeyLevelsReport:
    as_of: datetime
    prev_ny_close: float | None
    prev_ny_close_at: datetime | None
    completed: DayRange
    developing: DayRange
    reactions: tuple[LevelReaction, ...]
    round_numbers: tuple[RoundLevel, ...]
    weekly_map: ResearchStub
    valid_break_even: ResearchStub
    reasons: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "as_of": self.as_of.isoformat(),
            "prev_ny_close": self.prev_ny_close,
            "prev_ny_close_at": None if self.prev_ny_close_at is None
            else self.prev_ny_close_at.isoformat(),
            "completed": self.completed.as_dict(),
            "developing": self.developing.as_dict(),
            "reactions": [r.as_dict() for r in self.reactions],
            "round_numbers": [r.as_dict() for r in self.round_numbers],
            "weekly_map": self.weekly_map.as_dict(),
            "valid_break_even": self.valid_break_even.as_dict(),
            "reasons": list(self.reasons),
            "rule_statuses": {k: r.status.value for k, r in KEY_LEVEL_BY_ID.items()},
            "status_counts": key_level_counts(),
        }


class KeyLevelsEngine:
    def __init__(self, bar_delta: timedelta | None = None) -> None:
        self.bar_delta = bar_delta or timedelta(hours=1)

    def run(
        self,
        bars: Sequence[Candle],
        *,
        as_of: datetime,
        price: float | None = None,
        rounds: RoundNumberParams | None = None,
    ) -> KeyLevelsReport:
        visible = visible_bars(bars, as_of, self.bar_delta)
        close, close_at = previous_ny_close(visible, as_of, self.bar_delta)
        completed = completed_day(visible, as_of, self.bar_delta)
        developing = developing_day(visible, as_of, self.bar_delta)
        reactions = reactions_to_completed(visible, completed, as_of, self.bar_delta)
        last_price = price if price is not None else (visible[-1].close if visible else None)
        levels = ()
        if rounds is not None and last_price is not None:
            levels = nearby_round_numbers(last_price, rounds)
        reasons = [
            f"prev NY close {close} at {close_at.isoformat()}" if close is not None
            else "no bar closed at the last NY cutover",
            f"completed day H/L {completed.high}/{completed.low} ({completed.bar_count} bars)",
            f"developing day is incomplete ({developing.bar_count} bars)",
            f"{len(reactions)} reactions vs completed H/L",
            "weekly MAP and valid break-even remain RESEARCH stubs",
        ]
        return KeyLevelsReport(
            as_of=as_of,
            prev_ny_close=close,
            prev_ny_close_at=close_at,
            completed=completed,
            developing=developing,
            reactions=reactions,
            round_numbers=levels,
            weekly_map=weekly_map_stub(),
            valid_break_even=valid_break_even_stub(),
            reasons=tuple(reasons),
        )
