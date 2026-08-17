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

**Capped twice: on count, and per symbol.** The cross-section opens both tails
at every instant, so a day of hourly bars proposes far more positions than a
10k account should hold. Both caps read the terminal rather than this system's
own record, because those disagree exactly when it matters.

The per-symbol cap was added after watching it happen: eight live positions
held only five symbols, with 0.48 lots of USDCAD across two of them. Each was a
separate decision, so nothing was traded twice - but the account carried double
the exposure the sizing computed for one, and a count-based limit cannot see
that.
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
#: The conservative pair the live cycle ran on, and the fallback if the
#: deployment sets nothing. Read through the accessors below rather than used
#: directly: binding them at import means a deployment cannot change how hard
#: it trades without a rebuild.
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

#: The most of one R a decision may spend just crossing the spread. Read from
#: the broker's own bid and ask at send time, not from a table: the number that
#: matters is the one being charged now, and it widens on news and at rollover
#: exactly when a rule is most likely to want to trade.
#:
#: R is the stop distance, so this ratio is what makes a shorter timeframe
#: dearer without anybody re-estimating anything. Measured on this deployment
#: against a 1.4 pip EURUSD spread and a 2.5x ATR stop, the round trip costs
#: about 0.06 R at H1, 0.13 at M15, 0.23 at M5 and 0.52 at M1 - so this ceiling
#: is what stands between the rule and a one-minute scalp that pays half its
#: risk before the trade has an opinion.
MAX_SPREAD_COST_R = 0.25

#: How long the bar the decision was taken on lasts. The decision happened at
#: its close, not at its label.
#:
#: Only a fallback now. Entries record their own timeframe, and this is what an
#: entry written before that field existed is charged. Hardcoding it was safe
#: while every decision was hourly and becomes a silent error the moment one is
#: not: an M5 decision charged an hour would stay tradeable for two and a half
#: hours, which is the delay being traded rather than the rule.
DECISION_BAR_MINUTES = 60


def _spread_cost_r(
    specification: dict[str, Any], stop_distance: float
) -> tuple[float | None, str]:
    """What crossing this symbol's spread costs, in R, right now.

    R is defined by the stop distance, so the cost in R is the broker's live
    bid-ask measured against that distance. Read per send rather than cached:
    the spread widens on news and at rollover, which is exactly when a rule is
    most likely to want to trade and exactly when a stale number is most wrong.

    Returns None rather than a default when the terminal has not published a
    usable quote. A missing spread is not a free one, and treating it as zero
    would let the one trade nobody could price through the one check meant to
    stop it.
    """
    bid, ask = specification.get("bid"), specification.get("ask")
    if bid is None or ask is None:
        return None, (
            "the terminal publishes no bid/ask for it, so the spread cannot be "
            "priced - and an unpriced spread is not a free one"
        )
    try:
        spread = float(ask) - float(bid)
    except (TypeError, ValueError):
        return None, "the published bid/ask could not be read as numbers"
    if spread < 0:
        return None, (
            f"the published bid {bid} is above the ask {ask}, which is not a "
            "market this should trade into"
        )
    if stop_distance <= 0:
        return None, "the decision recorded a zero stop, so R is undefined"
    return spread / stop_distance, ""


def _bar_minutes(entry: JournalEntry) -> int:
    """How long the bar this particular decision was taken on lasted."""
    from app.core.enums import Timeframe

    recorded = (entry.before or {}).get("timeframe")
    if not recorded:
        return DECISION_BAR_MINUTES
    try:
        return max(1, int(Timeframe(str(recorded)).delta.total_seconds() // 60))
    except (ValueError, KeyError):
        return DECISION_BAR_MINUTES


def _risk_percent() -> float:
    """What fraction of equity to put behind one stop, as the deployment set it."""
    from app.core.config import get_settings

    return float(getattr(get_settings(), "autotrade_risk_percent", RISK_PERCENT))


def _max_open_positions() -> int:
    """How many positions may be open at once, as the deployment set it."""
    from app.core.config import get_settings

    return int(
        getattr(get_settings(), "autotrade_max_open_positions", MAX_OPEN_POSITIONS)
    )


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
        risk_percent=_risk_percent(),
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
    live_positions = feed.positions().get("positions") or []
    open_now = len(live_positions)
    # Which symbols the account already carries. The cap on count alone let
    # the cross-section re-pick the same instrument on consecutive instants:
    # eight live positions held only five symbols, with 0.48 lots of USDCAD
    # across two of them - twice the risk the sizing computed for one
    # decision, and invisible in any count-based limit.
    held = {str(p.get("symbol")) for p in live_positions if p.get("symbol")}
    cap = _max_open_positions()
    room = cap - open_now
    if room <= 0:
        return _report(
            mode=mode,
            refused=(
                f"{open_now} positions are already open and the cap is "
                f"{cap}"
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
        if entry.symbol in held:
            skipped.append(
                f"{entry.symbol}: the account already holds a position in it, "
                "and a second one doubles an exposure that was sized for one"
            )
            continue

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

        stop_distance = abs(float(price) - float(stop))
        spread_cost, spread_reason = _spread_cost_r(specification, stop_distance)
        if spread_cost is None:
            skipped.append(f"{entry.symbol}: {spread_reason}")
            continue
        if spread_cost > MAX_SPREAD_COST_R:
            skipped.append(
                f"{entry.symbol}: crossing the spread costs {spread_cost:.3f} R, "
                f"over the {MAX_SPREAD_COST_R} R ceiling. The trade starts that "
                "far behind before it has an opinion"
            )
            continue

        try:
            intent = OrderIntent(
                symbol=entry.symbol,
                side=OrderSide.BUY if entry.decision == "long" else OrderSide.SELL,
                order_type=OrderType.MARKET,
                risk_r=_risk_percent() / 100.0,
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
                        detail=(
                            f"{_risk_percent()}% of equity behind the recorded stop"
                        ),
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
        # Held from this cycle on, so two decisions on one symbol inside a
        # single pass cannot both go through either.
        held.add(entry.symbol)

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
    # taken on that bar's close at 05:00. Which bar differs per entry now, so
    # the query takes the widest window any timeframe could justify and each
    # row is then charged its own bar below. Filtering only in SQL would need
    # one cutoff for all of them, and the only safe single value is the
    # loosest - which is exactly the stale M5 decision this guards against.
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

    fresh = [
        row
        for row in rows
        if row.opened_at
        >= moment - timedelta(minutes=MAX_DECISION_AGE_MINUTES + _bar_minutes(row))
    ]
    return [row for row in fresh if _needs_an_order(row)]


#: The one rejection reason that proves nothing reached the broker.
#:
#: Written by the adapter when the request file itself could not be created,
#: which is the case where retrying is provably safe: no file means the expert
#: never saw it and no position exists. Matching on the reason is narrow on
#: purpose - any broader rule risks resending an order that was placed.
NEVER_SENT = "the request could not be written"


def _needs_an_order(entry: JournalEntry) -> bool:
    """Whether this decision still has an order owing.

    A decision that already carries one is left alone, including a rejected
    one: a rejection from the broker means it saw the request and said no, and
    resending it is how one refusal becomes two positions when the refusal was
    transient.

    The single exception is a request that was never written at all. Four
    orders were lost that way on the first live cycle, to a read-only mount,
    and re-deriving them from the decisions that are still sitting there is
    exactly what a decision-first design is for.
    """
    order = (entry.during or {}).get("order")
    if not order:
        return True
    if order.get("state") != str(OrderState.REJECTED):
        return False
    return NEVER_SENT in str(order.get("reason") or "")


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
        "risk_percent": _risk_percent(),
        "max_open_positions": _max_open_positions(),
        "note": (
            "the rule arm on the broker's own price series only. The control "
            "is recorded and never traded - it exists so the rule has "
            "something to be measured against, and trading it would put money "
            "behind a random side"
        ),
    }


def new_id() -> uuid.UUID:
    return uuid.uuid4()
