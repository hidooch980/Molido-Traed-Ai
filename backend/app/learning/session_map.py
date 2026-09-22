"""The golden-hour map: each brain's live edge, cut by trading session - proposed, not applied.

`brain_selection` answers "which brain" from the journal. This asks the next
question of the same rows: does a brain earn everywhere, or only while one
market is open? If one session carries the edge and another bleeds it, an
hour filter at the gate is a documented removal rather than a guess - and
until the journal says so with enough positions, nothing is removed.

The arithmetic is `brain_selection`'s, cut four ways:

  * **Broker prices, H1, rule arm, each position once.** `weekly.position_heads`
    collapses the recorder's repeats; the session is the one the position
    opened in.
  * **After cost.** `brain_selection.COST_R` comes off every position.
  * **Beside its own control** in the same session, as `brain_selection` reads it.
  * **Enough positions per cell.** Below `MIN_POSITIONS` a cell is thin and
    says nothing either way.

**The bar is raised for the table, not for the cell.** Four sessions per
brain over several brains is a sweep, and the best cell of a sweep beats
1.96 by luck often enough to fill a filter list with noise. A cell is called
only when its t clears `robustness.required_t` for every thick cell tested.

Session boundaries are `robustness.session_of`: UTC hours, no daylight saving.
It changes no setting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.learning import weekly
from app.learning.brain_selection import COST_R, MIN_POSITIONS, SOURCE
from app.learning.measure import _paired_t
from app.learning.robustness import required_t, session_of
from app.models.journal import ARM_CONTROL, ARM_RULE, JournalEntry

#: The timeframe the live brains trade. Other timeframes are recorded for
#: measurement and would mix a different cost-to-range ratio into the cell.
TIMEFRAME = "H1"

SESSIONS: tuple[str, ...] = ("tokyo", "london", "overlap", "new-york")

#: Verdicts a cell can carry. Only GOLDEN and AVOID are findings.
THIN = "thin"
GOLDEN = "golden"
AVOID = "avoid"
UNCLEAR = "unclear"


@dataclass(frozen=True)
class Cell:
    """One brain in one session."""

    strategy: str
    session: str
    returns: tuple[float, ...]
    control_mean_r: float | None

    @property
    def positions(self) -> int:
        return len(self.returns)

    @property
    def thin(self) -> bool:
        return self.positions < MIN_POSITIONS

    @property
    def mean_r(self) -> float | None:
        return sum(self.returns) / len(self.returns) if self.returns else None

    @property
    def net_r(self) -> float | None:
        return None if self.mean_r is None else self.mean_r - COST_R

    @property
    def over_control(self) -> float | None:
        if self.mean_r is None or self.control_mean_r is None:
            return None
        return self.mean_r - self.control_mean_r

    @property
    def t(self) -> float:
        """t of the net R against zero. Zero when the sample cannot give one."""
        return _paired_t([r - COST_R for r in self.returns])[0]

    def verdict(self, bar: float) -> str:
        if self.thin:
            return THIN
        if self.t >= bar and self.over_control is not None and self.over_control > 0:
            return GOLDEN
        if self.t <= -bar:
            return AVOID
        return UNCLEAR

    def as_dict(self, bar: float) -> dict[str, Any]:
        def r(value: float | None) -> float | None:
            return None if value is None else round(value, 3)

        return {
            "strategy": self.strategy,
            "session": self.session,
            "positions": self.positions,
            "mean_r": r(self.mean_r),
            "net_r": r(self.net_r),
            "control_mean_r": r(self.control_mean_r),
            "over_control": r(self.over_control),
            "t": round(self.t, 2),
            "verdict": self.verdict(bar),
        }


@dataclass(frozen=True)
class SessionMap:
    cells: list[Cell]

    @property
    def tested(self) -> int:
        """Thick cells: the hypotheses this table actually put to the data."""
        return sum(1 for c in self.cells if not c.thin)

    @property
    def bar(self) -> float:
        return required_t(self.tested)

    def findings(self, verdict: str) -> list[Cell]:
        return [c for c in self.cells if c.verdict(self.bar) == verdict]

    def as_dict(self) -> dict[str, Any]:
        return {
            "timeframe": TIMEFRAME,
            "cost_r": COST_R,
            "min_positions": MIN_POSITIONS,
            "cells_tested": self.tested,
            "required_t": round(self.bar, 2),
            "cells": [c.as_dict(self.bar) for c in self.cells],
            "golden": [f"{c.strategy}@{c.session}" for c in self.findings(GOLDEN)],
            "avoid": [f"{c.strategy}@{c.session}" for c in self.findings(AVOID)],
        }


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def build(session: Session, *, source: str = SOURCE, timeframe: str = TIMEFRAME) -> SessionMap:
    """Every brain in every session, from the journal."""
    rule_rows = session.scalars(
        select(JournalEntry).where(
            JournalEntry.arm == ARM_RULE,
            JournalEntry.price_source == source,
            JournalEntry.timeframe == timeframe,
        )
    ).all()
    control_rows = session.scalars(
        select(JournalEntry).where(
            JournalEntry.arm == ARM_CONTROL,
            JournalEntry.price_source == source,
            JournalEntry.timeframe == timeframe,
            JournalEntry.r_multiple.is_not(None),
        )
    ).all()

    returns: dict[tuple[str, str], list[float]] = {}
    for head in weekly.position_heads(list(rule_rows)):
        if head.r_multiple is None:
            continue
        key = (head.strategy, session_of(_aware(head.opened_at)))
        returns.setdefault(key, []).append(float(head.r_multiple))

    control: dict[tuple[str, str], list[float]] = {}
    for row in control_rows:
        key = (row.strategy, session_of(_aware(row.opened_at)))
        control.setdefault(key, []).append(float(row.r_multiple or 0.0))

    strategies = sorted({strategy for strategy, _ in returns})
    cells = []
    for strategy in strategies:
        for name in SESSIONS:
            values = control.get((strategy, name)) or []
            cells.append(
                Cell(
                    strategy=strategy,
                    session=name,
                    returns=tuple(returns.get((strategy, name), ())),
                    control_mean_r=sum(values) / len(values) if values else None,
                )
            )
    return SessionMap(cells=cells)


_SESSION_FA = {
    "tokyo": "توکیو",
    "london": "لندن",
    "overlap": "هم‌پوشانی",
    "new-york": "نیویورک",
}


def compose(result: SessionMap) -> str:
    lines = [
        "نقشهٔ ساعت طلایی — لبهٔ هر مغز به تفکیک جلسه (هیچ فیلتری اعمال نشد)",
        f"H1، قیمت بروکر، خالص پس از {COST_R:g}R هزینه؛ حد t برای "
        f"{result.tested} خانهٔ آزموده: {result.bar:.2f}",
        "",
    ]
    if not result.cells:
        lines.append("هنوز هیچ پوزیشن حل‌شده‌ای در ژورنال نیست.")
    current = None
    for cell in result.cells:
        if cell.strategy != current:
            current = cell.strategy
            lines.append(f"• {current}")
        label = _SESSION_FA[cell.session]
        if cell.thin:
            lines.append(f"  {label}: {cell.positions} پوزیشن — کمتر از {MIN_POSITIONS}، حکمی نیست")
            continue
        over = "—" if cell.over_control is None else f"{cell.over_control:+.2f}"
        lines.append(
            f"  {label}: {cell.positions} پوزیشن، خالص {cell.net_r:+.2f}R، "
            f"از سکه {over}R، t={cell.t:+.2f} → {cell.verdict(result.bar)}"
        )
    golden = result.findings(GOLDEN)
    avoid = result.findings(AVOID)
    lines.append("")
    if not golden and not avoid:
        lines.append("هیچ جلسه‌ای معنادار نشد؛ فیلتر ساعتی پیشنهاد نمی‌شود.")
    for cell in golden:
        lines.append(f"طلایی: {cell.strategy} در {_SESSION_FA[cell.session]}")
    for cell in avoid:
        lines.append(
            f"پیشنهاد حذف: {cell.strategy} در {_SESSION_FA[cell.session]} "
            "(پس از هزینه به‌طور معنادار زیان‌ده)"
        )
    return "\n".join(lines)


def run(*, send: bool = True) -> dict[str, Any]:
    from app.db.session import session_scope
    from app.integrations import notify, telegram

    with session_scope() as session:
        result = build(session)
        text = compose(result)
        delivery = None
        if send:
            delivery = telegram.send(
                notify.Message(
                    urgency=notify.Urgency.INFO,
                    title="MolidoTrade — نقشهٔ ساعت طلایی",
                    body=text,
                    at=datetime.now(UTC),
                ),
                session=session,
            )
    return {
        "applied": False,
        **result.as_dict(),
        "sent": bool(getattr(delivery, "sent", False)),
        "text": text,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run(send=False), ensure_ascii=False, indent=1))
