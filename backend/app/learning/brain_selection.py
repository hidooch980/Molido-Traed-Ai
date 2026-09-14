"""Which brain each account should trade, decided from the journal - proposed, not applied.

On 14 September the owner moved four accounts by hand after a table showed
three brains beating their coin-flip control by more than half an R and two
losing to it by as much. That decision has an arithmetic, and an arithmetic
can run every day without anybody asking for it. This is it.

**Proposal mode only.** It says what it would change and why, in the log and
on Telegram, and changes nothing. A selector that rewrites the fleet from two
weeks of data should earn that right by being read first.

The rules, all of which the owner's decision already used:

  * **Broker prices, rule arm, each position once.** `weekly.positions`
    collapses the recorder's repeats, so one long move is one piece of
    evidence, not sixty.
  * **Beaten by its own control, it does not qualify.** The control is a coin
    flip on the same bars with the same geometry; a brain that cannot beat it
    has beaten nothing.
  * **After cost.** The journal is gross. `COST_R` is taken off before a brain
    may qualify, because a signal that costs more to collect than it pays is
    not an edge.
  * **Enough positions.** Below `MIN_POSITIONS` nothing is proposed for or
    against a brain.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.learning import weekly
from app.models.journal import ARM_CONTROL, ARM_RULE, JournalEntry

#: Round-trip cost per position in R, charged before a brain may qualify.
#: The spread alone measured about 0.06 R at H1; across 28 live fills a 1 R
#: geometry arrived at 0.77, so slippage costs more than the spread. 0.15 is
#: deliberately the pessimistic side of both.
COST_R = 0.15

#: Resolved positions a brain needs before it is judged either way.
MIN_POSITIONS = 50

#: The broker's own series. The public feed prices a different market.
SOURCE = "metatrader"


@dataclass(frozen=True)
class Standing:
    strategy: str
    positions: int
    mean_r: float | None
    control_mean_r: float | None

    @property
    def net_r(self) -> float | None:
        return None if self.mean_r is None else self.mean_r - COST_R

    @property
    def over_control(self) -> float | None:
        if self.mean_r is None or self.control_mean_r is None:
            return None
        return self.mean_r - self.control_mean_r

    @property
    def qualifies(self) -> bool:
        return bool(
            self.positions >= MIN_POSITIONS
            and self.net_r is not None
            and self.net_r > 0
            and self.over_control is not None
            and self.over_control > 0
        )

    def as_dict(self) -> dict[str, Any]:
        def r(value: float | None) -> float | None:
            return None if value is None else round(value, 3)

        return {
            "strategy": self.strategy,
            "positions": self.positions,
            "mean_r": r(self.mean_r),
            "net_r": r(self.net_r),
            "control_mean_r": r(self.control_mean_r),
            "over_control": r(self.over_control),
            "qualifies": self.qualifies,
        }


def standings(session: Session, *, source: str = SOURCE) -> list[Standing]:
    """Every brain on the broker series, best net R first."""
    rule_rows = session.scalars(
        select(JournalEntry).where(
            JournalEntry.arm == ARM_RULE, JournalEntry.price_source == source
        )
    ).all()
    control_rows = session.scalars(
        select(JournalEntry).where(
            JournalEntry.arm == ARM_CONTROL,
            JournalEntry.price_source == source,
            JournalEntry.r_multiple.is_not(None),
        )
    ).all()

    grouped = weekly.positions(list(rule_rows))
    control: dict[str, list[float]] = {}
    for row in control_rows:
        if row.r_multiple is not None:
            control.setdefault(row.strategy, []).append(float(row.r_multiple))

    out = []
    for strategy, bucket in grouped.items():
        resolved = bucket["resolved"]
        values = control.get(strategy) or []
        out.append(
            Standing(
                strategy=strategy,
                positions=resolved,
                mean_r=bucket["total_r"] / resolved if resolved else None,
                control_mean_r=sum(values) / len(values) if values else None,
            )
        )
    out.sort(key=lambda s: -(s.net_r if s.net_r is not None else -99.0))
    return out


def propose(
    ranked: list[Standing],
    accounts: dict[str, frozenset[str] | None],
    *,
    keep: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """What each account should move to, if anything.

    An account moves only when none of its current brains qualifies. Moves
    are spread across the qualifying brains, best first, so the fleet does
    not bet every account on one number. Accounts in `keep` never move: they
    are the comparison that shows whether moving helped.
    """
    good = [s.strategy for s in ranked if s.qualifies]
    by_name = {s.strategy: s for s in ranked}
    changes: list[dict[str, Any]] = []
    if not good:
        return changes

    turn = 0
    for account in sorted(accounts):
        current = accounts[account] or frozenset()
        if account in keep:
            continue
        if any(by_name.get(name) and by_name[name].qualifies for name in current):
            continue
        target = good[turn % len(good)]
        turn += 1
        changes.append(
            {
                "account": account,
                "from": sorted(current),
                "to": target,
                "why": (
                    f"{', '.join(sorted(current)) or 'nothing'} does not qualify; "
                    f"{target} earns {by_name[target].net_r:+.2f} R after cost and "
                    f"{by_name[target].over_control:+.2f} R over its control on "
                    f"{by_name[target].positions} positions"
                ),
            }
        )
    return changes


def compose(ranked: list[Standing], changes: list[dict[str, Any]]) -> str:
    lines = ["انتخاب مغز — پیشنهاد روزانه (هیچ تغییری اعمال نشد)", ""]
    for s in ranked:
        mark = "✓" if s.qualifies else "✗"
        net = "—" if s.net_r is None else f"{s.net_r:+.2f}"
        over = "—" if s.over_control is None else f"{s.over_control:+.2f}"
        lines.append(f"{mark} {s.strategy}: {s.positions} پوزیشن، خالص {net}R، از سکه {over}R")
    lines.append("")
    if not changes:
        lines.append("پیشنهاد تغییری نیست.")
    for change in changes:
        lines.append(f"• {change['account']}: {'+'.join(change['from']) or '—'} → {change['to']}")
    return "\n".join(lines)


def run(*, send: bool = True) -> dict[str, Any]:
    """Read the fleet, rank the brains, log and send the proposal."""
    import os
    from datetime import UTC, datetime

    from app.db.session import session_scope
    from app.integrations import notify, telegram
    from app.providers.metatrader import MetaTraderBridge, bridge_dirs
    from app.workers import autotrade

    keep = frozenset(
        p.strip() for p in os.environ.get("MOLIDO_BRAIN_SELECTION_KEEP", "").split(",") if p.strip()
    )
    accounts: dict[str, frozenset[str] | None] = {}
    for _key, path in sorted(bridge_dirs().items()):
        login = str(MetaTraderBridge(directory=path).account().get("login") or "")
        if login:
            accounts[login] = autotrade._strategy_for(login)[0]

    with session_scope() as session:
        ranked = standings(session)
        changes = propose(ranked, accounts, keep=keep)
        text = compose(ranked, changes)
        delivery = None
        if send:
            delivery = telegram.send(
                notify.Message(
                    urgency=notify.Urgency.INFO,
                    title="MolidoTrade — انتخاب مغز",
                    body=text,
                    at=datetime.now(UTC),
                ),
                session=session,
            )

    return {
        "applied": False,
        "standings": [s.as_dict() for s in ranked],
        "proposals": changes,
        "kept": sorted(keep),
        "sent": bool(getattr(delivery, "sent", False)),
        "text": text,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run(send=False), ensure_ascii=False, indent=1))
