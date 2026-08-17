"""Turn recorded decisions into orders, once each, behind every gate.

The last piece. The rule has been writing decisions for days and the execution
path has existed since this morning; nothing joined them, so the position on
the account was one I sent by hand.

Five choices carry this, and each one closes a way it goes wrong:

**Only the rule arm.** The control is a coin flip written down so the rule has
something to be measured against. Trading it would put money behind a random
side and double the exposure, and the comparison it exists for does not need it
to be traded - it needs it to be *recorded*, which already happens.

**Only one price series.** Both series decide on the same instruments at nearly
the same instants. Trading both would open two positions in one symbol for one
market view, and the risk numbers above would each see half of it. The broker
series is the one traded, because it is decided on the prices that actually
fill - the public feed and the broker differ by about four pips on EURUSD, and
a decision taken on a price you cannot trade at is a decision about a different
market.

**Once, ever.** The order is written onto the journal entry that produced it.
An entry that already carries one is skipped, so a cycle that runs twice, or a
worker that restarts mid-pass, cannot reopen a position. This matters more than
any other property here: everything else fails by not trading, and this fails
by trading twice.

**Sized, or not sent.** Lots come from equity, the risk fraction and the stop
distance, using the broker's own tick value. No tick value means no order -
never a default size, because a default is a position whose risk nobody chose.

**Capped.** The cross-section opens both tails at every instant, so a day of
hourly bars proposes far more positions than a 10k account should hold at once.
The cap is on open positions at the broker, counted from the terminal rather
than from this system's own record, because those disagree exactly when it
matters.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailedError
from app.execution.contracts import (
    Approval,
    OrderIntent,
    OrderSide,
    OrderState,
    OrderType,
)
from app.execution.metatrader_broker import MetaTraderBroker
from app.models.journal import ARM_RULE, SOURCE_BROKER, JournalEntry

#: Fraction of equity risked per position. Small on purpose: the rule proposes
#: several positions per instant and the edge it is chasing is a fiftieth of a
#: stop distance, so size is not where the return comes from.
RISK_PERCENT = 0.25

#: How many positions may be open at the broker at once.
#:
#: The cross-section takes both tails at every instant. Left uncapped, a day of
#: hourly bars would propose dozens, and a 10k account holding dozens of
#: correlated FX positions is one market move away from its own drawdown limit.
MAX_OPEN_POSITIONS = 8

#: Only decisions this fresh are traded. An hour-old decision is about a price
#: that has moved, and filling it now trades the delay rather than the rule.
#:
#: Measured from when the decision was *taken*, which is not what its timestamp
#: says. A journal entry is stamped with the bar's instant - 04:00 for the bar
#: labelled 04:00 - but that bar spans 04:00 to 05:00 and the rule decided on
#: its close. So the decision is an hour younger than its own timestamp, and
#: charging it that hour left a usable window of about fifteen minutes against
#: a collector that runs every fifteen. The first live cycle found four
#: decisions and traded none of them, missing by nine minutes.
MAX_DECISION_AGE_MINUTES = 90

#: How long the bar the decision was taken on lasts. The decision happened at
#: its close, not at its label.
DECISION_BAR_MINUTES = 60


def _lots(
    *,
    equity: float,
    stop_distance: float,
    specification: dict[str, Any],
) -> tuple[float | None, str]:
    """How many lots put `RISK_PERCENT` of equity behind this stop.

    Returns `(None, why)` rather than a default when the broker has not
    published what a tick is worth. A default size is a position whose risk
    nobody chose, and it would be wrong by a different factor on every symbol.
    """
    from app.services import calculators

    sized = calculators.lot_size(
        symbol=str(specification.get("name") or ""),
        equity=equity,
        risk_percent=RISK_PERCENT,
        stop_distance_price=stop_distance,
        tick_value=specification.get("tick_value"),
        tick_size=specification.get("tick_size"),
        volume_min=specification.get("volume_min"),
        volume_step=specification.get("volume_step"),
    )
    if not sized.get("available"):
        return None, str(sized.get("reason") or "the size could not be computed")
    lots = float(sized.get("lots") or 0.0)
    if lots <= 0:
        return None, "the computed size rounds to zero lots at this risk"
    return lots, ""


def run_cycle(
    session: Session,
    *,
    now: datetime | None = None,
    broker: MetaTraderBroker | None = None,
    bridge: Any = None,
) -> dict[str, Any]:
    """Send an order for every fresh rule decision that has not had one.

    Every refusal is named and counted. A cycle that sends nothing because the
    gates are shut and one that sends nothing because there was nothing to send
    are different facts, and a single "0 orders" hides which.
    """
    from app.execution import autopilot
    from app.providers.metatrader import MetaTraderBridge

    moment = (now or datetime.now(UTC)).astimezone(UTC)
    feed = bridge or MetaTraderBridge()
    sender = broker or MetaTraderBroker()

    mode, why, _live = autopilot.mode_now()
    if mode != "live":
        return _report(mode=mode, refused=f"autopilot is in {mode}: {why}")

    published = feed.account()
    allowed, account_reason = autopilot.account_gate(published)
    if not allowed:
        return _report(mode=mode, refused=account_reason)

    login = str(published.get("login") or "")
    equity = float(published.get("equity") or 0.0)
    if not login or equity <= 0:
        return _report(mode=mode, refused="the terminal published no usable account")

    # Counted from the terminal, never from this system's own record. They
    # disagree exactly when it matters, and the broker's answer is the one the
    # account is judged on.
    open_now = len(feed.positions().get("positions") or [])
    room = MAX_OPEN_POSITIONS - open_now
    if room <= 0:
        return _report(
            mode=mode,
            refused=(
                f"{open_now} positions are already open and the cap is "
                f"{MAX_OPEN_POSITIONS}"
            ),
            open_positions=open_now,
        )

    specifications = {
        str(s.get("name")): s for s in (feed.symbols().get("symbols") or [])
    }

    candidates = _pending(session, moment)
    sent: list[dict[str, Any]] = []
    skipped: list[str] = []

    for entry in candidates:
        if len(sent) >= room:
            skipped.append(
                f"{entry.symbol}: the open-position cap was reached in this cycle"
            )
            continue

        geometry = entry.before or {}
        price, stop = geometry.get("entry"), geometry.get("stop")
        target = geometry.get("target")
        if price is None or stop is None:
            skipped.append(f"{entry.symbol}: the decision recorded no levels")
            continue

        specification = specifications.get(entry.symbol)
        if not specification:
            skipped.append(
                f"{entry.symbol}: the terminal publishes no contract "
                "specification, so the size cannot be computed from it"
            )
            continue

        lots, problem = _lots(
            equity=equity,
            stop_distance=abs(float(price) - float(stop)),
            specification=specification,
        )
        if lots is None:
            skipped.append(f"{entry.symbol}: {problem}")
            continue

        try:
            intent = OrderIntent(
                symbol=entry.symbol,
                side=OrderSide.BUY if entry.decision == "long" else OrderSide.SELL,
                order_type=OrderType.MARKET,
                risk_r=RISK_PERCENT / 100.0,
                entry=float(price),
                stop=float(stop),
                target=float(target) if target is not None else None,
                approvals=(
                    Approval(
                        source="strategy",
                        approved=True,
                        detail="cross-sectional-stretch, both tails",
                        at=moment,
                    ),
                    Approval(
                        source="risk",
                        approved=True,
                        detail=f"{RISK_PERCENT}% of equity behind the recorded stop",
                        at=moment,
                    ),
                ),
                authorised_at=moment,
                account_id=login,
                metadata={"lots": lots, "journal_entry": str(entry.id)},
            )
        except ValidationFailedError as problem:
            # One malformed decision must not end the cycle for every
            # decision behind it. Named, because a side and a stop that
            # disagree is a recorder bug worth finding, not noise.
            skipped.append(f"{entry.symbol}: {problem}")
            continue

        # Written before the order is sent, not after. If this process dies
        # between the two, the next cycle sees a decision that already has an
        # order and leaves it alone - which loses an order rather than
        # duplicating one. That is the direction to fail in.
        entry.during = {
            **(entry.during or {}),
            "order": {
                "intent_id": str(intent.intent_id),
                "lots": lots,
                "state": "submitting",
                "at": moment.isoformat(),
            },
        }
        session.commit()

        report = sender.submit(intent)
        entry.during = {
            **(entry.during or {}),
            "order": {
                "intent_id": str(intent.intent_id),
                "lots": lots,
                "state": str(report.state),
                "ticket": report.broker_order_id,
                "fill": report.average_price,
                "reason": report.reason,
                "at": moment.isoformat(),
            },
        }
        session.commit()

        sent.append(
            {
                "symbol": entry.symbol,
                "side": entry.decision,
                "lots": lots,
                "state": str(report.state),
                "ticket": report.broker_order_id,
                "fill": report.average_price,
                # The gap between the price the rule decided on and the price
                # the account got. This is the number the whole dual-series
                # argument was about, and now it is measured per order rather
                # than inferred from two feeds.
                "slippage": (
                    round(report.average_price - float(price), 5)
                    if report.average_price
                    else None
                ),
            }
        )

    return _report(
        mode=mode,
        sent=sent,
        skipped=skipped,
        considered=len(candidates),
        open_positions=open_now,
    )


def _pending(session: Session, moment: datetime) -> list[JournalEntry]:
    """Fresh rule decisions on the broker series that have no order yet.

    The arm and the series are filters rather than options: the control is a
    measurement and the public series is decided on prices this account cannot
    fill at.
    """
    from datetime import timedelta

    # The bar's length is added back, because a decision stamped 04:00 was
    # taken on that bar's close at 05:00.
    cutoff = moment - timedelta(
        minutes=MAX_DECISION_AGE_MINUTES + DECISION_BAR_MINUTES
    )
    rows = session.scalars(
        select(JournalEntry)
        .where(
            JournalEntry.arm == ARM_RULE,
            JournalEntry.price_source == SOURCE_BROKER,
            JournalEntry.closed_at.is_(None),
            JournalEntry.opened_at >= cutoff,
        )
        .order_by(JournalEntry.opened_at)
    ).all()

    return [row for row in rows if not (row.during or {}).get("order")]


def _report(
    *,
    mode: str,
    sent: list[dict[str, Any]] | None = None,
    skipped: list[str] | None = None,
    refused: str | None = None,
    considered: int = 0,
    open_positions: int | None = None,
) -> dict[str, Any]:
    filled = [o for o in (sent or []) if o["state"] == OrderState.FILLED]
    return {
        "mode": mode,
        "orders": len(sent or []),
        "filled": len(filled),
        "considered": considered,
        "open_positions": open_positions,
        "sent": sent or [],
        # Every refusal named. "0 orders because the gates are shut" and "0
        # orders because there was nothing to send" are different facts.
        "skipped": skipped or [],
        "refused": refused,
        "risk_percent": RISK_PERCENT,
        "max_open_positions": MAX_OPEN_POSITIONS,
        "note": (
            "the rule arm on the broker's own price series only. The control "
            "is recorded and never traded - it exists so the rule has "
            "something to be measured against, and trading it would put money "
            "behind a random side"
        ),
    }


def new_id() -> uuid.UUID:
    return uuid.uuid4()
