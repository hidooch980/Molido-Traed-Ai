"""What the live journal says about managing trades after entry - proposed, not applied.

`geometry.sweep_exits` answers the question on replayed history, which is too
heavy to run on the trading box. The journal now records, for every closed
trade, the furthest it went in its favour and against itself before the bar
that closed it (`best_r_before_close`, `worst_r_before_close`). Two cheap
readings follow from those, per brain:

  * **Losers that were once ahead.** A losing trade that had reached +0.7 R
    before its stop is one a stop moved to entry would have scratched.
  * **Winners that were once deep.** A winning trade that had gone to -0.7 R
    before its target is one a shorter stop would have lost.

Neither is a verdict alone - moving the stop to entry also scratches winners
that dip back - so this proposes only when one side is large and the other
small, and says nothing below `MIN_POSITIONS`. It changes no setting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.journal import ARM_RULE, JournalEntry

#: Closed positions with a recorded path a brain needs before anything is said.
MIN_POSITIONS = 30

#: Levels the readings are taken at, in R.
AHEAD_LEVELS: tuple[float, ...] = (0.5, 0.7, 1.0)
DEEP_LEVELS: tuple[float, ...] = (-0.5, -0.7)

#: A reading is worth proposing on when this share of one side crossed a level
#: and at most `QUIET_SHARE` of the other side would have been hurt by acting.
LOUD_SHARE = 0.4
QUIET_SHARE = 0.2

SOURCE = "metatrader"


@dataclass(frozen=True)
class BrainEvidence:
    strategy: str
    winners: int
    losers: int
    losers_ahead: dict[float, int]
    winners_ahead: dict[float, int]
    winners_deep: dict[float, int]

    @property
    def positions(self) -> int:
        return self.winners + self.losers

    def proposals(self) -> list[str]:
        if self.positions < MIN_POSITIONS or not self.losers or not self.winners:
            return []
        out: list[str] = []
        for level in AHEAD_LEVELS:
            saved = self.losers_ahead[level] / self.losers
            # A winner that had been at +level and then dipped to entry before
            # its target is one a stop-to-entry would cost; `winners_deep` at
            # -0.5 is the nearest recorded proxy for "dipped back".
            cost = self.winners_deep[DEEP_LEVELS[0]] / self.winners
            if saved >= LOUD_SHARE and cost <= QUIET_SHARE:
                out.append(
                    f"move the stop to entry at +{level:g}R: {saved:.0%} of losers had "
                    f"reached it, and only {cost:.0%} of winners went below -0.5R"
                )
                break
        deep = self.winners_deep[DEEP_LEVELS[-1]] / self.winners
        early = self.losers_ahead[AHEAD_LEVELS[0]] / self.losers
        if deep <= QUIET_SHARE / 2 and early < QUIET_SHARE:
            out.append(
                f"a shorter stop looks affordable: only {deep:.0%} of winners went "
                f"below {DEEP_LEVELS[-1]:g}R before their target"
            )
        return out

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "positions": self.positions,
            "winners": self.winners,
            "losers": self.losers,
            "losers_ahead": {str(k): v for k, v in self.losers_ahead.items()},
            "winners_ahead": {str(k): v for k, v in self.winners_ahead.items()},
            "winners_deep": {str(k): v for k, v in self.winners_deep.items()},
            "proposals": self.proposals(),
        }


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def evidence(
    session: Session, *, days: int | None = None, source: str = SOURCE
) -> list[BrainEvidence]:
    """Per brain, from closed rule-arm positions that carry a recorded path."""
    query = select(JournalEntry).where(
        JournalEntry.arm == ARM_RULE,
        JournalEntry.price_source == source,
        JournalEntry.r_multiple.is_not(None),
    )
    if days is not None:
        query = query.where(JournalEntry.opened_at >= datetime.now(UTC) - timedelta(days=days))

    # One observation per position: the recorder rewrites a held view every
    # cycle, so rows sharing brain, symbol and side that open while an earlier
    # one is still open are the same trade.
    keyed: dict[tuple[str, str, str], list[JournalEntry]] = {}
    for row in session.scalars(query).all():
        after = row.after if isinstance(row.after, dict) else {}
        if "best_r_before_close" not in after or "worst_r_before_close" not in after:
            continue
        keyed.setdefault((row.strategy, row.symbol, row.decision), []).append(row)

    tallies: dict[str, dict[str, Any]] = {}
    for (strategy, _symbol, _side), rows in keyed.items():
        rows.sort(key=lambda r: _aware(r.opened_at))
        open_until: datetime | None = None
        for row in rows:
            opened = _aware(row.opened_at)
            closed = _aware(row.closed_at) if row.closed_at else opened
            if open_until is not None and opened <= open_until:
                open_until = max(open_until, closed)
                continue
            open_until = closed
            t = tallies.setdefault(
                strategy,
                {
                    "winners": 0,
                    "losers": 0,
                    "losers_ahead": dict.fromkeys(AHEAD_LEVELS, 0),
                    "winners_ahead": dict.fromkeys(AHEAD_LEVELS, 0),
                    "winners_deep": dict.fromkeys(DEEP_LEVELS, 0),
                },
            )
            path = row.after if isinstance(row.after, dict) else {}
            best = float(path["best_r_before_close"])
            worst = float(path["worst_r_before_close"])
            if float(row.r_multiple or 0.0) > 0:
                t["winners"] += 1
                for level in AHEAD_LEVELS:
                    t["winners_ahead"][level] += best >= level
                for level in DEEP_LEVELS:
                    t["winners_deep"][level] += worst <= level
            else:
                t["losers"] += 1
                for level in AHEAD_LEVELS:
                    t["losers_ahead"][level] += best >= level

    return sorted(
        (BrainEvidence(strategy=name, **values) for name, values in tallies.items()),
        key=lambda b: -b.positions,
    )


def compose(brains: list[BrainEvidence]) -> str:
    lines = ["مدیریت حد سود و ضرر — شواهد هفتگی از ژورنال (هیچ تنظیمی عوض نشد)", ""]
    if not brains:
        lines.append("هنوز هیچ معاملهٔ بسته‌شده‌ای مسیرش را ثبت نکرده است.")
    for b in brains:
        head = f"• {b.strategy}: {b.positions} پوزیشن ({b.winners} برد، {b.losers} باخت)"
        if b.positions < MIN_POSITIONS:
            lines.append(f"{head} — کمتر از {MIN_POSITIONS}، حکمی نیست")
            continue
        lines.append(head)
        if b.losers:
            lines.append(
                "  باخت‌هایی که قبلش جلو بودند: "
                + "، ".join(f"+{k:g}R {v / b.losers:.0%}" for k, v in b.losers_ahead.items())
            )
        if b.winners:
            lines.append(
                "  بردهایی که قبلش عمیق رفتند: "
                + "، ".join(f"{k:g}R {v / b.winners:.0%}" for k, v in b.winners_deep.items())
            )
        for proposal in b.proposals():
            lines.append(f"  پیشنهاد: {proposal}")
    return "\n".join(lines)


def run(*, send: bool = True) -> dict[str, Any]:
    from app.db.session import session_scope
    from app.integrations import notify, telegram

    with session_scope() as session:
        brains = evidence(session)
        text = compose(brains)
        delivery = None
        if send:
            delivery = telegram.send(
                notify.Message(
                    urgency=notify.Urgency.INFO,
                    title="MolidoTrade — مدیریت خروج",
                    body=text,
                    at=datetime.now(UTC),
                ),
                session=session,
            )
    return {
        "applied": False,
        "brains": [b.as_dict() for b in brains],
        "sent": bool(getattr(delivery, "sent", False)),
        "text": text,
    }
