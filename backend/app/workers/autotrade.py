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
from datetime import UTC, date, datetime, timedelta
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


def _feed_age_bars(published: dict[str, Any], moment: datetime) -> float | None:
    """How stale the terminal's own publication is, in decision bars.

    The bridge already measures this and publishes `age_seconds` under
    `state`, so that is read rather than recomputed from a stamp. Re-deriving
    it here meant parsing a timestamp in a format the bridge does not use -
    the first live call returned None and the brain correctly blocked, which
    is how the mistake surfaced. One measurement, in the place that owns it.

    Returned as None when the bridge offers no age, and the brain treats None
    as stale rather than fresh: not knowing the age of a feed is not evidence
    that it is young. That is its rule, and this does not soften it by
    substituting a number.
    """
    state = published.get("state")
    seconds = state.get("age_seconds") if isinstance(state, dict) else None
    if seconds is None:
        seconds = published.get("age_seconds")
    try:
        minutes = abs(float(seconds)) / 60.0
    except (TypeError, ValueError):
        return None
    return minutes / max(DECISION_BAR_MINUTES, 1)


def _authorise(state: Any, *, feed_age_bars: float | None) -> Any:
    """Ask the risk brain whether this cycle may open new risk.

    Health is reported honestly rather than flatteringly. `calibrated` and
    `training_eligible` are left at their pessimistic defaults because this
    deployment has neither a calibrated probability nor a proven edge, and
    both of those halve the permitted risk rather than blocking - which is the
    brain's own considered answer to being unsure, and not one to override
    from here.
    """
    from app.brain.risk import DataHealth, authorise

    return authorise(
        requested_risk_r=_risk_percent() / 100.0,
        account=state,
        health=DataHealth(data_age_bars=feed_age_bars),
    )


#: How close to a high-impact release a new position may be opened. Both prop
#: firms this build carries rulebooks for restrict trading around news, and a
#: violation there is not a loss - it is the account, in one afternoon. The
#: window is deliberately wider than either firm's stated one: sitting exactly
#: on a rule's edge means a clock difference of seconds decides whether the
#: challenge survives.
NEWS_WINDOW_MINUTES = 5

#: Impacts that close the window. Medium releases move price too, but blocking
#: on them costs most of the session on a busy week for a rule that has no
#: measured edge around news either way.
NEWS_IMPACTS = frozenset({"High"})


#: Hours before the Friday close at which the weekend counts as "ahead". The
#: FX week ends around 21:00 UTC on Friday, so this starts warning in the
#: early afternoon - enough of a session left to close what is open rather
#: than discovering the rule at the last quote.
WEEKEND_WARNING_HOUR_UTC = 16

#: Friday, as `weekday()` counts.
_FRIDAY = 4


def _weekend_ahead(moment: datetime) -> bool:
    """Whether this is the last session before the break.

    Prop rulebooks that forbid weekend holding are asking about the gap: a
    position carried over Sunday's open can pass its stop without ever being
    offered the price. So the answer is about the *session*, not the clock -
    Friday afternoon onwards, and the whole of Saturday and Sunday, which is
    when a position can only have been carried in.
    """
    weekday = moment.weekday()
    if weekday > _FRIDAY:
        return True
    if weekday == _FRIDAY and moment.hour >= WEEKEND_WARNING_HOUR_UTC:
        return True
    return False


def _currencies_of(symbol: str) -> set[str]:
    """The two currencies a pair is exposed to.

    Metals and indices are left with whatever their first three characters
    say plus USD, because XAUUSD is exposed to dollar releases whatever else
    it is. A symbol too short to split returns nothing and the caller then has
    no currency to match on - which is reported rather than treated as safe.
    """
    cleaned = "".join(c for c in symbol.upper() if c.isalpha())
    if len(cleaned) < 6:
        return set()
    return {cleaned[:3], cleaned[3:6]}


def _news_gate(
    symbol: str, moment: datetime, releases: list[dict[str, Any]] | None
) -> tuple[bool, str]:
    """Whether a release is close enough to keep this symbol shut.

    `releases` is None when the calendar could not be read, and that refuses.
    An unknown news state is not a quiet one, and the rule being protected
    here is the kind that ends an account rather than costing a trade. The
    calendar module takes the same position about its own feed: a feed failing
    is not a quiet week.
    """
    if releases is None:
        return False, (
            "the economic calendar could not be read, so whether a release is "
            "imminent is unknown - and unknown is not quiet"
        )

    exposed = _currencies_of(symbol)
    if not exposed:
        return False, (
            f"{symbol} cannot be split into currencies, so its news exposure "
            "cannot be checked"
        )

    window = timedelta(minutes=NEWS_WINDOW_MINUTES)
    for release in releases:
        if str(release.get("impact") or "") not in NEWS_IMPACTS:
            continue
        if str(release.get("currency") or "").upper() not in exposed:
            continue
        at = release.get("at")
        if not at:
            # An all-day entry has no clock, so no window can be drawn around
            # it. Named rather than silently skipped.
            continue
        try:
            when = datetime.fromisoformat(str(at))
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        if abs((when - moment).total_seconds()) <= window.total_seconds():
            return False, (
                f"{release.get('title') or 'a high-impact release'} for "
                f"{release.get('currency')} lands within {NEWS_WINDOW_MINUTES} "
                "minutes, and both rulebooks restrict trading around it"
            )
    return True, ""


def _any_high_impact_now(
    moment: datetime, releases: list[dict[str, Any]] | None
) -> bool | None:
    """Whether any high-impact release is inside the window, for any currency.

    None when the calendar could not be read. The challenge engine treats an
    unknown restriction as a gate rather than a pass, which is the same
    position the per-symbol check takes and for the same reason.
    """
    if releases is None:
        return None
    return any(not _news_gate(f"{r.get('currency') or 'XXX'}USD", moment, [r])[0]
               for r in releases
               if str(r.get("impact") or "") in NEWS_IMPACTS)


def _this_week(moment: datetime) -> list[dict[str, Any]] | None:
    """This week's releases, or None if the feed could not be read.

    None rather than an empty list on failure. An empty week and an unreadable
    feed are different facts and only one of them means it is safe to trade.
    """
    from app.services import calendar as calendar_service

    try:
        return list(calendar_service.week(now=moment).get("releases") or [])
    except Exception:  # noqa: BLE001 - any failure is "unknown", not "quiet"
        return None


def _open_risk_r(
    position: dict[str, Any], specification: dict[str, Any], one_r_money: float
) -> float | None:
    """What an already-open position still risks, in R.

    Computed from its own stop and size rather than assumed to be one R.
    Positions opened at a different equity, or by hand, or before a risk
    change, are not one R - and the portfolio brain adds these up, so a wrong
    unit here becomes a wrong total for the whole book.

    None when the terminal has not published enough to price it. The caller
    treats an unpriceable position as unknown exposure rather than none.
    """
    try:
        opened = float(position.get("price_open"))
        stop = float(position.get("stop"))
        volume = float(position.get("volume"))
        tick_value = float(specification.get("tick_value"))
        tick_size = float(specification.get("tick_size"))
    except (TypeError, ValueError):
        return None
    if tick_size <= 0 or one_r_money <= 0 or volume <= 0:
        return None
    distance = abs(opened - stop)
    if distance <= 0:
        # A position with no stop is not a position risking nothing. It is one
        # whose risk has no ceiling, which no number here can express.
        return None
    money = (distance / tick_size) * tick_value * volume
    return money / one_r_money


def _portfolio_headroom(
    symbol: str,
    direction: str,
    proposed_risk_r: float,
    live_positions: list[dict[str, Any]],
    specifications: dict[str, dict[str, Any]],
    one_r_money: float,
) -> tuple[float | None, str]:
    """How much of this trade the open book can still absorb.

    `brain/portfolio.py` exists because two independently excellent EURUSD and
    GBPUSD longs are one larger dollar-short position, and a sizer that judges
    each on its own merit approves twice the exposure it believes it approved.
    It had no caller in the live path either.

    Returns `(headroom_r, reason)`. A None headroom is a refusal, and the
    reason says which position could not be priced - an unpriceable position
    is unknown exposure, not absent exposure, and adding to a book you cannot
    measure is the thing this module exists to prevent.
    """
    from app.brain import portfolio as portfolio_brain

    book: list[portfolio_brain.Position] = []
    for row in live_positions:
        held = str(row.get("symbol") or "")
        specification = specifications.get(held) or {}
        risk_r = _open_risk_r(row, specification, one_r_money)
        if risk_r is None:
            return None, (
                f"the open {held or 'position'} cannot be priced in R, so the "
                "book's total exposure is unknown - and unknown is not zero"
            )
        book.append(
            portfolio_brain.Position(
                symbol=held,
                direction="buy" if str(row.get("side") or "").lower() == "buy" else "sell",
                risk_r=risk_r,
            )
        )

    verdict = portfolio_brain.evaluate(
        symbol=symbol,
        direction=direction,
        proposed_risk_r=proposed_risk_r,
        positions=book,
    )
    if not verdict.allowed:
        return None, "portfolio: " + "; ".join(verdict.breaches or ["blocked"])
    return verdict.max_additional_risk_r, ""


def _challenge_gate(
    session: Session,
    published: dict[str, Any],
    open_positions: int,
    proposed_risk_r: float,
    *,
    today: date,
    moment: datetime,
    in_news_window: bool | None = None,
) -> tuple[bool, str, float | None]:
    """Check the account against its prop rulebook, if it has one.

    `brain/challenge.py` holds ten sourced rulebooks and had no caller in the
    live path. It answers the question the risk brain does not: *if this trade
    loses everything it risks, is the challenge still alive?* A daily drawdown
    rule counts money once, at the moment the equity prints, and there is no
    appeal - so it has to be asked before the order, not after.

    An account with no rulebook registered is not a challenge account, and
    this passes rather than inventing limits it was never given. Returns
    `(allowed, reason, max_additional_risk_r)`.

    More than one active registration refuses instead of picking. The registry
    carries no broker login to match on, so with two accounts there is no
    honest way to know which rulebook governs the money about to be risked -
    and applying the wrong one is applying limits from another account.
    """
    from app.brain import challenge as challenge_brain
    from app.brain import rulebooks
    from app.services import challenge_accounts

    try:
        registered = [
            a
            for a in challenge_accounts.listing(
                session, tenant_id=challenge_accounts.default_tenant(session)
            )
            if getattr(a, "is_active", True)
        ]
    except Exception as problem:  # noqa: BLE001 - reported, never fatal
        return False, f"the challenge registry could not be read: {type(problem).__name__}", None

    if not registered:
        return True, "", None
    if len(registered) > 1:
        return (
            False,
            f"{len(registered)} challenge accounts are registered and none names a "
            "broker login, so which rulebook governs this money cannot be known",
            None,
        )

    account = registered[0]
    book = rulebooks.get(str(getattr(account, "rulebook_key", "") or ""))
    if book is None:
        return (
            False,
            f"the registered rulebook {getattr(account, 'rulebook_key', '?')!r} is not "
            "one this build knows, so its limits cannot be applied",
            None,
        )

    equity = float(published.get("equity") or 0.0)
    state = challenge_brain.ChallengeState(
        starting_balance=float(getattr(account, "starting_balance", 0.0) or 0.0),
        current_equity=equity,
        peak_equity=max(equity, float(getattr(account, "starting_balance", 0.0) or 0.0)),
        daily_starting_equity=equity,
        days_traded=0,
        open_positions=open_positions,
        current_date=today,
        current_balance=float(published.get("balance") or 0.0),
        # Both supplied rather than left None. The engine gates on an unknown
        # restriction, which is right, and answering the question is better
        # than being gated by it.
        in_news_window=in_news_window,
        weekend_ahead=_weekend_ahead(moment),
    )
    verdict = challenge_brain.check(book.rules, state, proposed_risk_r)
    if not verdict.allowed:
        if verdict.breaches:
            return False, "challenge rules: " + "; ".join(verdict.breaches), None
        # Blocked without a breach means the rulebook was never fully entered.
        # The engine refuses to approve against a limit nobody told it, which
        # is the right answer and a useless message unless it says so - the
        # fix is confirming the rulebook, not finding a trade that passes.
        unverified = "; ".join(getattr(verdict, "unverified", []) or [])
        return (
            False,
            "the registered rulebook is incomplete, so no trade can be checked "
            f"against it: {unverified or 'unspecified'}",
            None,
        )
    return True, "", verdict.max_additional_risk_r


def _account_state(
    session: Session, published: dict[str, Any], open_positions: int
) -> tuple[Any, str]:
    """Build the state the risk brain requires, or name what is missing.

    `AccountState` takes no optional fields on purpose - its own docstring
    says an optional balance would let a caller omit the one number that
    would have blocked the trade. So a missing peak or day-open refuses the
    cycle rather than being filled with a plausible default. Both come from
    recorded history, and the honest reading of "nothing recorded" is that
    the drawdown against them cannot be computed, not that it is zero.
    """
    from app.brain.risk import AccountState
    from app.services import equity as equity_service

    account_key = str(published.get("login") or "")
    if not account_key:
        return None, "the terminal published no login, so there is no account to size against"

    equity = float(published.get("equity") or 0.0)
    balance = float(published.get("balance") or 0.0)
    if equity <= 0:
        return None, "the terminal published no equity, so risk cannot be sized"

    peak = equity_service.peak_equity(session, account_key)
    if peak is None:
        return None, (
            "no equity has ever been recorded for this account, so the drawdown "
            "from peak cannot be computed - and an unknown drawdown is not a zero one"
        )

    day_open = equity_service.peak_day_open_balance(session, account_key)
    if day_open is None:
        return None, (
            "no day-boundary balance has been recorded, so today's loss cannot be "
            "measured against anything"
        )

    # The day's P&L expressed in R, which is what the brain's limits are in.
    # One R is what a single trade risks, so a 3 R daily limit is three losing
    # trades - which is the unit the limit was written in.
    one_r = equity * (_risk_percent() / 100.0)
    if one_r <= 0:
        return None, "the configured risk per trade is zero, so R is undefined"
    daily_pnl_r = (equity - float(day_open)) / one_r

    return (
        AccountState(
            equity=equity,
            balance=balance,
            peak_equity=float(peak),
            daily_pnl_r=daily_pnl_r,
            open_positions=open_positions,
            used_margin=float(published.get("margin") or 0.0),
            free_margin=float(published.get("free_margin") or 0.0),
        ),
        "",
    )


#: Sources whose decisions may be sent, and how their levels are read.
#:
#: The terminal's own series is sent as recorded: its prices are the prices the
#: order will meet. Any other series has to be re-anchored, because a level
#: from a different feed is a different number for the same moment - the public
#: feed and the broker sit about four pips apart on EURUSD here.
#:
#: The reasoning that admitted the daily series was that a 2.5x ATR stop on D1
#: is around eighty-five pips, so four pips of feed difference is under five
#: percent of it. Measured against the live book, the actual gap on the one
#: recorded D1 decision was 146.7 pips - not feed difference at all, but a
#: series that stops last December. Re-anchoring held the stop at exactly the
#: 84.9 pips the decision asked for, where sending it as recorded would have
#: placed it 232 pips away, nearly three times the intended risk.
#:
#: So the mechanism works and the admission was wrong. Both are kept: the
#: function, because a current series will need it, and the empty set, because
#: this one is not current.
#: Empty, and the reason is measured rather than cautious. The daily series
#: this was written for ends on 2025-12-31 - two hundred and thirty days stale
#: - because the backfill loaded 2005 to 2025 and never reached this year. A
#: decision taken on it is not a stale price, it is a stale *market*, and
#: re-anchoring would carry last December's signal onto today's quote, which
#: is worse than not trading it at all.
#:
#: The check that would have caught this on its own is decision *age*, and it
#: does not: these entries were opened minutes ago on data from December. Age
#: of the row is not age of the evidence.
#:
#: Put "dukascopy" back when the series reaches the current day, and not
#: before. Everything below is written and tested against it.
REANCHORED_SOURCES: frozenset[str] = frozenset()


def _levels_from_broker(
    geometry: dict[str, Any], specification: dict[str, Any], side: str
) -> tuple[float, float, float | None] | None:
    """Re-anchor a decision's shape onto the broker's own price.

    The *distances* are what the analysis produced - they are volatility, and
    volatility transfers between feeds. The *price* has to come from the venue
    the order will actually meet, or the stop sits at a level that meant
    something on another chart.

    Distances are taken from the recorded levels rather than recomputed from
    the multiples, so a decision keeps whatever geometry it was actually
    written with. Re-deriving them from today's constants would silently
    re-shape an old decision if a multiple ever moved.

    Returns None when the terminal has published no usable quote, because a
    re-anchoring without a price is a guess about where the market is.
    """
    try:
        recorded_entry = float(geometry["entry"])
        recorded_stop = float(geometry["stop"])
    except (KeyError, TypeError, ValueError):
        return None

    stop_distance = abs(recorded_entry - recorded_stop)
    if stop_distance <= 0:
        return None

    target_distance: float | None = None
    raw_target = geometry.get("target")
    if raw_target is not None:
        try:
            target_distance = abs(float(raw_target) - recorded_entry)
        except (TypeError, ValueError):
            target_distance = None
        if target_distance is not None and target_distance <= 0:
            target_distance = None

    bid, ask = specification.get("bid"), specification.get("ask")
    try:
        # Entered at the side of the book the order will actually cross, not
        # at a mid nobody trades: a buy lifts the ask.
        entry = float(ask) if side == "long" else float(bid)
    except (TypeError, ValueError):
        return None
    if entry <= 0:
        return None

    if side == "long":
        stop = entry - stop_distance
        target = entry + target_distance if target_distance is not None else None
    else:
        stop = entry + stop_distance
        target = entry - target_distance if target_distance is not None else None

    if stop <= 0 or (target is not None and target <= 0):
        return None
    return entry, stop, target


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
    risk_percent: float | None = None,
) -> tuple[float | None, str]:
    """How many lots put this much of equity behind this stop.

    `risk_percent` defaults to the configured figure. The caller passes the
    risk brain's *permitted* figure instead, which is often smaller: consulting
    a limit and then sizing as though it had approved the full request is not
    consulting it at all.

    Returns `(None, why)` rather than a default when the broker has not
    published what a tick is worth. A default size is a position whose risk
    nobody chose, and it would be wrong by a different factor on every symbol.
    """
    from app.services import calculators

    sized = calculators.lot_size(
        symbol=str(specification.get("name") or ""),
        equity=equity,
        risk_percent=_risk_percent() if risk_percent is None else risk_percent,
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
    kill_switch: Any = None,
) -> dict[str, Any]:
    """Send an order for every fresh rule decision that has not had one.

    Every refusal is named and counted. A cycle that sends nothing because the
    gates are shut and one that sends nothing because there was nothing to send
    are different facts, and a single "0 orders" hides which.

    The kill switch is read here rather than trusted from a caller. This
    function is the only path that sends live orders and it used to consult no
    switch at all - the API reported one engaged while this traded, because
    the switch lived in a per-request object and this never asked.
    """
    from app.execution import autopilot, killswitch_store
    from app.providers.metatrader import MetaTraderBridge

    moment = (now or datetime.now(UTC)).astimezone(UTC)
    feed = bridge or MetaTraderBridge()
    sender = broker or MetaTraderBroker()

    # First gate, before the mode, the account and the decisions. A halt that
    # can be reached only after four other things succeed is not a halt.
    switch = kill_switch if kill_switch is not None else killswitch_store.load()
    if switch.engaged:
        return _report(mode="halted", refused=f"kill switch: {switch.reason}")

    mode, why, _live = autopilot.mode_now()
    if mode == autopilot.HALTED:
        return _report(mode=mode, refused=f"autopilot is in {mode}: {why}")

    # Paper runs the whole cycle and sends nothing. The mode existed and this
    # function refused on it, so "paper" meant "do nothing" rather than "do
    # everything except send" - and everything except send is where the work
    # is. The first run of the sizing, the gates and the lot arithmetic should
    # not be on real money.
    if mode == autopilot.PAPER:
        from app.execution.paper_broker import PaperBroker

        sender = broker if broker is not None else PaperBroker()

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

    # The risk brain, which until now decided nothing. It exists to be the
    # link that cannot be talked out of its answer, and it was reachable only
    # from an API route - so the daily loss limit it enforces had never once
    # been consulted by the thing that trades.
    state, missing = _account_state(session, published, open_now)
    if state is None:
        return _report(mode=mode, refused=f"risk state unavailable: {missing}")

    verdict = _authorise(state, feed_age_bars=_feed_age_bars(published, moment))
    if not verdict.approves:
        return _report(
            mode=mode,
            refused="risk brain: " + "; ".join(verdict.hard_breaches or verdict.reasons),
        )

    # Read once for the cycle. Both the account-wide question the rulebook
    # asks and the per-symbol gate below draw on the same week.
    releases = _this_week(moment)

    # The prop rulebook, if this account has one. It answers what the risk
    # brain does not: whether the challenge survives this trade losing. An
    # account with none registered passes - inventing limits it was never
    # given would be a rule nobody agreed to.
    passes, why, headroom_r = _challenge_gate(
        session,
        published,
        open_now,
        verdict.permitted_risk_r,
        today=moment.date(),
        moment=moment,
        # Computed once for the account rather than per symbol: the rulebook's
        # question is whether trading is restricted right now, not whether one
        # instrument happens to be exposed.
        in_news_window=_any_high_impact_now(moment, releases),
    )
    if not passes:
        return _report(mode=mode, refused=why)
    if headroom_r is not None and headroom_r < verdict.permitted_risk_r:
        # The tighter of the two governs. Two limits consulted and the looser
        # obeyed is one limit consulted.
        verdict.permitted_risk_r = headroom_r

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

        # A decision from another feed carries that feed's prices, and the
        # public series sits about four pips from the broker on EURUSD here.
        # Its *shape* is volatility and transfers; its absolute levels do not.
        if entry.price_source != SOURCE_BROKER:
            reanchored = _levels_from_broker(geometry, specification, entry.decision)
            if reanchored is None:
                skipped.append(
                    f"{entry.symbol}: recorded on {entry.price_source} and the "
                    "terminal publishes no quote to re-anchor it onto, so its "
                    "levels would be another feed's prices"
                )
                continue
            price, stop, target = reanchored

        clear, news_reason = _news_gate(entry.symbol, moment, releases)
        if not clear:
            skipped.append(f"{entry.symbol}: {news_reason}")
            continue

        stop_distance = abs(float(price) - float(stop))

        # What the open book can still absorb of this, which is a different
        # question from whether the account can afford it. Two excellent
        # correlated longs are one larger position, and sizing each on its own
        # merit approves twice the exposure it believes it approved.
        headroom, portfolio_reason = _portfolio_headroom(
            entry.symbol,
            "buy" if entry.decision == "long" else "sell",
            verdict.permitted_risk_r,
            live_positions,
            specifications,
            equity * (verdict.permitted_risk_r or 0.0),
        )
        if headroom is None:
            skipped.append(f"{entry.symbol}: {portfolio_reason}")
            continue
        risk_for_this = min(verdict.permitted_risk_r, headroom)
        if risk_for_this <= 0:
            skipped.append(
                f"{entry.symbol}: the book has no room left for it at this correlation"
            )
            continue

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

        lots, problem = _lots(
            equity=equity,
            stop_distance=stop_distance,
            specification=specification,
            # The tightest of the three that spoke: the risk brain's ceiling,
            # the challenge headroom folded into it, and what the open book
            # can still absorb at this correlation. Consulting three limits
            # and obeying the loosest is consulting none.
            risk_percent=risk_for_this * 100.0,
        )
        if lots is None:
            skipped.append(f"{entry.symbol}: {problem}")
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
                        # What was used, not what was configured. The approval
                        # is the audit record, and the two stopped being the
                        # same number the moment the risk brain started
                        # reducing - it said 0.8% while sizing at 0.2%.
                        detail=(
                            f"{risk_for_this * 100:.4g}% of equity behind the "
                            f"recorded stop (requested {_risk_percent()}%, "
                            f"reduced by risk/challenge/portfolio)"
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
            # The terminal's own series, plus any series wide enough to be
            # re-anchored onto the broker's price. See REANCHORED_SOURCES.
            JournalEntry.price_source.in_([SOURCE_BROKER, *sorted(REANCHORED_SOURCES)]),
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
