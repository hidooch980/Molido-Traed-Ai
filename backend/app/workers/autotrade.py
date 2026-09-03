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

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailedError
from app.execution.broker import BrokerAdapter
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
from app.core.logging import get_logger

log = get_logger(__name__)

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

#: The expert's own `MaxSlippagePts`, used when it does not publish one.
#:
#: The ceiling above counted the spread and nothing else, and the spread is
#: about half of what getting in costs. The other half is the fill landing
#: away from the quote, and across twenty-eight live fills that was the larger
#: half: a geometry designed for one unit of reward per unit of risk arrived
#: at 0.77, and the worst of them at 0.15.
#:
#: Counting it here is not a new tolerance. 0.25 R was already the deployment's
#: answer to "how much may execution cost", and it was being enforced against
#: an understatement. A worst case rather than an average, because the expert
#: enforces this exact number as its deviation limit - so it is a bound the
#: venue will honour, not an estimate somebody has to keep re-fitting.
DEFAULT_SLIPPAGE_POINTS = 30.0

#: How long the bar the decision was taken on lasts. The decision happened at
#: its close, not at its label.
#:
#: Only a fallback now. Entries record their own timeframe, and this is what an
#: entry written before that field existed is charged. Hardcoding it was safe
#: while every decision was hourly and becomes a silent error the moment one is
#: not: an M5 decision charged an hour would stay tradeable for two and a half
#: hours, which is the delay being traded rather than the rule.
DECISION_BAR_MINUTES = 60

#: The frame that supplies context, and the frames that are details
#: inside it. An entry on a fast frame is refused when the context frame
#: has a fresh decision the other way - not when it is silent, which is
#: most instants.
CONTEXT_TIMEFRAME = "H1"
FAST_TIMEFRAMES: frozenset[str] = frozenset({"M1", "M5", "M15"})


def _number(value: Any) -> float:
    """A published field as a float, raising on anything that is not one.

    Every caller wraps its conversions in `except (TypeError, ValueError)` and
    treats a failure as "the terminal has not published enough to price this".
    `dict.get` on those payloads is typed `Any | None`, so `float(None)` was
    the path a missing field took to that handler - correct at runtime and
    invisible to the type checker, which read six calls that could be passed
    None and said so.

    This raises the same `TypeError` on the same input, so the handlers above
    are unchanged. What it adds is that the contract is now written down: a
    missing field is not a zero, and nothing here substitutes one.
    """
    if value is None:
        raise TypeError("the terminal published no value for this field")
    return float(value)


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
        minutes = abs(_number(seconds)) / 60.0
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
        opened = _number(position.get("price_open"))
        stop = _number(position.get("stop"))
        volume = _number(position.get("volume"))
        tick_value = _number(specification.get("tick_value"))
        tick_size = _number(specification.get("tick_size"))
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
        held_base, held_quote = _currencies(held)
        book.append(
            portfolio_brain.Position(
                symbol=held,
                direction="buy" if str(row.get("side") or "").lower() == "buy" else "sell",
                risk_r=risk_r,
                base_currency=held_base,
                quote_currency=held_quote,
            )
        )

    proposed_base, proposed_quote = _currencies(symbol)
    verdict = portfolio_brain.evaluate(
        symbol=symbol,
        direction=direction,
        proposed_risk_r=proposed_risk_r,
        positions=book,
        base_currency=proposed_base,
        quote_currency=proposed_quote,
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
    from app.services import challenge_accounts

    try:
        # `listing` hands back AccountView wrappers, not accounts. Keeping the
        # wrapper - rather than unwrapping to the row - is what lets the
        # rulebook below come from the one resolution the service already did.
        # Reading a row's field off the wrapper answers nothing, which is how
        # "the registered rulebook '?' is not one this build knows" appeared
        # for an account whose rulebook was perfectly well known: the read was
        # aimed at the wrong object.
        registered = [
            view
            for view in challenge_accounts.listing(
                session, tenant_id=challenge_accounts.default_tenant(session)
            )
            if view.account.is_active
        ]
    except Exception as problem:  # noqa: BLE001 - reported, never fatal
        return False, f"the challenge registry could not be read: {type(problem).__name__}", None

    if not registered:
        return True, "", None

    # Which registration governs *this* money.
    #
    # A registration labelled with an account number binds that account and
    # no other. Without this, one prop account made every other terminal a
    # prop account: three demo balances of $100, $500 and $959 were each
    # measured against a $15,000 challenge's $13,500 floor and refused for a
    # drawdown none of them had. The rulebook was right, the account it was
    # applied to was not.
    #
    # An exact digit-for-digit match with the login is not a coincidence, so
    # it wins outright. A bare number that matches some *other* account is
    # somebody else's registration and is dropped. Anything else - a label
    # like "my challenge" - keeps the old behaviour, because a name is not a
    # claim about which login it belongs to.
    login = str(published.get("login") or "").strip()
    mine = [v for v in registered if v.account.label.strip() == login]
    if mine:
        registered = mine
    else:
        registered = [
            v
            for v in registered
            if not (v.account.label.strip().isdigit() and v.account.label.strip() != login)
        ]
        if not registered:
            return True, "", None

    if len(registered) > 1:
        return (
            False,
            f"{len(registered)} challenge accounts are registered and none names a "
            "broker login, so which rulebook governs this money cannot be known",
            None,
        )

    view = registered[0]
    account = view.account
    # Already resolved by the service. Looking it up again would be a second
    # resolution that can disagree with the one the API reports.
    book = view.rulebook
    if book is None:
        return (
            False,
            f"the registered rulebook {account.rulebook_key!r} is not one this "
            "build knows, so its limits cannot be applied",
            None,
        )

    equity = float(published.get("equity") or 0.0)

    # Leverage in use, which is not the account's leverage setting.
    #
    # The bridge publishes `leverage`, and it is MetaTrader's ACCOUNT_LEVERAGE:
    # the ratio the broker permits. Handing that to the rule would compare a
    # permission against a cap and report an untouched account as sitting
    # exactly on its limit - a breach invented out of a healthy account.
    #
    # With no margin committed there is no exposure, so the leverage in use is
    # zero. That is a measurement and worth making, because it is the state an
    # account is in whenever a new position is being considered from flat.
    # With margin committed it cannot be derived from this payload: notional
    # is margin times the *symbol's* margin rate, and those differ per
    # instrument - so it stays unknown and the rule reports itself unmeasured
    # rather than guessing in either direction.
    margin = published.get("margin")
    leverage_in_use = 0.0 if margin is not None and float(margin) == 0.0 else None

    state = challenge_brain.ChallengeState(
        starting_balance=float(account.starting_balance or 0.0),
        current_equity=equity,
        peak_equity=max(equity, float(account.starting_balance or 0.0)),
        daily_starting_equity=equity,
        days_traded=0,
        open_positions=open_positions,
        # `getattr` because a stand-in account in a test predates the field,
        # and the safe default is the one that refuses: an account whose
        # confirmation cannot be read has not confirmed anything.
        rules_confirmed_by_holder=bool(getattr(account, "rules_confirmed", False)),
        current_date=today,
        current_balance=float(published.get("balance") or 0.0),
        # Both supplied rather than left None. The engine gates on an unknown
        # restriction, which is right, and answering the question is better
        # than being gated by it.
        in_news_window=in_news_window,
        weekend_ahead=_weekend_ahead(moment),
        current_leverage=leverage_in_use,
        # Registered by the holder for exactly this, and never read until now.
        # The column's own comment says an absent one blocks every verdict -
        # "correct, and useless" - and it was absent here because the gate
        # built the state without it, not because nobody had entered one.
        currency_per_r=(
            float(account.currency_per_r)
            if account.currency_per_r is not None
            else None
        ),
    )
    verdict = challenge_brain.check(book.rules, state, proposed_risk_r)
    if not verdict.allowed:
        if verdict.breaches:
            return False, "challenge rules: " + "; ".join(verdict.breaches), None
        # Blocked without a breach has two causes and they call for opposite
        # responses, so they are no longer reported in one sentence.
        #
        # A gate is a rule that IS entered and could not be cleared right now
        # - leverage that cannot be measured, a permission nobody confirmed.
        # An unverified entry is a rule nobody wrote down. This used to
        # announce "the registered rulebook is incomplete" for both, which
        # sent a reader to their provider's page to fix a number that was
        # already there, or to re-transcribe a rulebook that was fine.
        # Both are reported when both exist. Naming only the gate would hide
        # every unentered rule behind whichever gate happened to fire, and
        # since the automation permission gates on all ten catalogued
        # rulebooks that would be all of them, always.
        gates = "; ".join(getattr(verdict, "gates", []) or [])
        unverified = "; ".join(getattr(verdict, "unverified", []) or [])
        if gates and unverified:
            return (
                False,
                f"the challenge gate is shut: {gates}. The rulebook is also "
                f"incomplete: {unverified}",
                None,
            )
        if gates:
            return False, f"the challenge gate is shut: {gates}", None
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
REANCHORED_SOURCES: frozenset[str] = frozenset({"aggregated"})

#: Analysis symbols admitted from any stored series, whatever its provider.
#:
#: The source-level rule above exists because a decision taken on one feed's
#: prices is a decision about a slightly different reality: the public EURUSD
#: and the broker's sit about four pips apart, which is a fifth of an hourly
#: stop and enough to matter.
#:
#: Gold is the case where that reasoning does not apply. The analysis series
#: is the futures contract and the order is spot, so the two never had the
#: same price and were never going to - the difference is a carry basis, which
#: is large, stable and completely absent from a *stretch*, because a stretch
#: is a distance measured in the instrument's own volatility. Re-anchoring
#: then takes the level from the venue that fills.
#:
#: It is also the cheapest instrument the account can trade: 0.029 R to cross
#: at hourly geometry against 0.062 for EURUSD, measured off the terminal's
#: own book.
REANCHORED_SYMBOLS: frozenset[str] = frozenset({"GCFUT", "SIFUT"})


#: Analysis symbol to the symbol the order is actually placed in.
#:
#: The rule ranks a series; the broker fills an instrument. Usually they are
#: the same name. For gold they are not: the public feed carries the futures
#: contract (GC=F, stored as GCFUT) and has fifteen-minute history for it,
#: while the terminal trades spot XAUUSD and publishes only hourly bars.
#:
#: They are not the same instrument, and the mapping is only defensible
#: because of what is done with it. The *shape* crosses over - gold futures
#: and gold spot move together closely enough that a stretch in one is a
#: stretch in the other - and the *price* does not, which is exactly what
#: re-anchoring already fixes: distances from the analysis series, absolute
#: level from the venue the order will meet.
#:
#: Silver the same way, for the same reason.
EXECUTION_SYMBOL: dict[str, str] = {
    "GCFUT": "XAUUSD",
    "SIFUT": "XAGUSD",
}


#: The codes a pair may be built from. An allowlist rather than a length
#: check, because a six-letter symbol is not evidence of two currencies -
#: COPPER divides into COP and PER, and COP is a real currency code.
#:
#: XAU, XAG and XPT are here deliberately: metals priced against a currency
#: behave as one for exposure, and three long metal positions against the
#: dollar are the same concentrated bet three FX pairs would be.
TRADED_CURRENCIES: frozenset[str] = frozenset({
    "AUD", "CAD", "CHF", "CNH", "CZK", "DKK", "EUR", "GBP", "HKD", "HUF",
    "ILS", "INR", "JPY", "MXN", "NOK", "NZD", "PLN", "SEK", "SGD", "THB",
    "TRY", "USD", "ZAR",
    "XAU", "XAG", "XPT",
    "BTC", "ETH",
})


def _currencies(symbol: str) -> tuple[str | None, str | None]:
    """The two currencies a pair is exposure to, or (None, None).

    EURUSD is +EUR and -USD when long, which is the whole reason the
    portfolio brain wants them: three long positions in EURUSD, GBPUSD
    and AUDUSD are not three bets, they are one bet against the dollar
    taken three times. Without the split, the brain sees three unrelated
    instruments and lets the book concentrate exactly where it should
    not.

    Metals and indices return (None, None) rather than a guess. XAUUSD
    does carry dollar exposure, but ".US500Cash" does not split into
    anything and a rule that pretends otherwise invents a currency
    position nobody holds. Unsplittable is the honest answer, and the
    brain treats an unknown currency as no claim rather than as zero.
    """
    name = _tradeable_symbol(symbol).upper()
    if len(name) != 6 or not name.isalpha():
        return None, None
    base, quote = name[:3], name[3:]
    # Both halves have to be codes this platform actually trades, or the
    # split is arithmetic rather than meaning: COPPER is six letters and
    # divides cleanly into COP and PER - and COP is the Colombian peso, so
    # the book would carry a position in a currency nobody holds and the
    # concentration check would count it.
    if base not in TRADED_CURRENCIES or quote not in TRADED_CURRENCIES:
        return None, None
    return base, quote


def _tradeable_symbol(symbol: str) -> str:
    """The instrument an order for this analysis symbol is placed in."""
    return EXECUTION_SYMBOL.get(symbol, symbol)


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
    # Entered at the side of the book the order will actually cross, not at a
    # mid nobody trades: a buy lifts the ask.
    crossed = ask if side == "long" else bid
    if crossed is None:
        return None
    try:
        entry = float(crossed)
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
    """What getting into this symbol costs, in R, right now.

    R is defined by the stop distance, so the cost in R is what the venue
    charges to open measured against that distance. Read per send rather than
    cached: the spread widens on news and at rollover, which is exactly when a
    rule is most likely to want to trade and exactly when a stale number is
    most wrong.

    Two costs, not one. The spread is the visible half; the other is the fill
    landing away from the quote it was priced against, and on a short
    timeframe that half is the larger. A 2.5x ATR stop is around forty pips at
    H1 and seven at M5, while the fill lands three or four pips off either
    way - noise in the first case and most of the trade in the second. Charging
    only the spread made the fast frames look affordable, and the realised
    reward-to-risk across twenty-eight live fills said otherwise.

    The slippage figure is a bound rather than an estimate: it is the expert's
    own deviation limit, which the venue enforces on every order. Published by
    the expert where it can be, so changing it there does not quietly
    invalidate the arithmetic here.

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

    # `point` is what a deviation limit is counted in. `tick_size` stands in
    # where a terminal publishes only that: the two are equal on every
    # instrument traded here, and where they are not, the tick is the larger -
    # which overstates the allowance and so refuses rather than admits. That
    # is the safe direction for a check whose whole job is refusing.
    point = _maybe_number(specification.get("point"))
    if point is None or point <= 0:
        point = _maybe_number(specification.get("tick_size"))
    if point is None or point <= 0:
        return None, (
            "the terminal publishes no point or tick size for it, so the "
            "slippage allowance cannot be priced - and an unpriced allowance "
            "is not a zero one"
        )

    allowed_points = _maybe_number(specification.get("slippage_points"))
    if allowed_points is None or allowed_points < 0:
        allowed_points = DEFAULT_SLIPPAGE_POINTS
    return (spread + allowed_points * point) / stop_distance, ""


def _maybe_number(value: Any) -> float | None:
    """A float, or None. `_number` raises, which is right for its callers.

    This one is for the checks that treat an absent field as a question to
    answer rather than a failure to propagate.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


#: How many resolved decisions a timeframe needs before its own measurement
#: is allowed to set the ceiling. Below this the fixed ceiling stands: a
#: handful of trades is not an edge, and letting six samples widen or narrow
#: what may be paid is fitting the gate to noise.
MIN_FOR_MEASURED_CEILING = 200


def _measured_edge(session: Session) -> dict[str, float]:
    """Expectancy in R per timeframe, from this deployment's own journal.

    The fixed ceiling answered "how much may execution cost" without ever
    asking what the trade was worth, and the two numbers turned out to be on
    opposite sides of each other: 0.25 R allowed, and the best brain earning
    0.124 R gross. Every trade at the ceiling was a loser by arithmetic, and
    the arithmetic was never done.

    So the ceiling is now the edge itself. A trade may not cost more than it
    is expected to make - not a preference, an accounting identity, and the
    one threshold here that nobody has to choose. Where a timeframe measures
    negative it buys nothing at any price and its decisions stop reaching a
    broker, which is how H1 came to be excluded without anybody writing a
    rule about H1.

    Gross of costs on purpose: the journal resolves decisions against the
    price series, so what it reports is what the signal is worth before
    paying for it. That is exactly the quantity a cost has to fit inside.
    """
    rows = session.execute(
        select(
            JournalEntry.timeframe,
            func.avg(JournalEntry.r_multiple),
            func.count(JournalEntry.id),
        )
        .where(
            JournalEntry.arm == ARM_RULE,
            JournalEntry.closed_at.is_not(None),
            JournalEntry.r_multiple.is_not(None),
        )
        .group_by(JournalEntry.timeframe)
    ).all()

    edges: dict[str, float] = {}
    for timeframe, expectancy, count in rows:
        if not timeframe or expectancy is None:
            continue
        if int(count or 0) < MIN_FOR_MEASURED_CEILING:
            continue
        edges[str(timeframe)] = float(expectancy)
    return edges


def _cost_ceiling(edges: dict[str, float], timeframe: Any) -> tuple[float, str]:
    """What this decision's timeframe may spend getting in, and why.

    Never looser than the fixed ceiling. A timeframe measuring 0.4 R has not
    earned the right to pay 0.4 R for entry - the fixed number is a statement
    about execution quality that stands on its own, and this only ever
    tightens it.
    """
    edge = edges.get(str(timeframe))
    if edge is None:
        return MAX_SPREAD_COST_R, (
            f"the standing ceiling - {timeframe} has too few resolved "
            "decisions to measure its own"
        )
    if edge <= 0:
        return 0.0, f"{timeframe} has measured {edge:+.3f} R and buys nothing at any price"
    return min(MAX_SPREAD_COST_R, edge), f"{timeframe} measures {edge:+.3f} R gross"


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
    account_currency: str | None = None,
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
        # So the calculator can catch a broker publishing a tick value that
        # disagrees with its own contract size. This account's terminal
        # understated XAUUSD by ten times, and the position it sized carried
        # 1.87% of equity against a configured 0.75%.
        contract_size=specification.get("contract_size"),
        account_currency=account_currency,
    )
    if not sized.get("available"):
        return None, str(sized.get("reason") or "the size could not be computed")
    disagreement = sized.get("spec_disagreement")
    if disagreement:
        # Logged every time rather than once: a broker that fixes its
        # specification should make this stop, and silence is how nobody
        # notices it never did.
        log.warning(
            "autotrade.specification_disagreement",
            symbol=specification.get("name"),
            detail=disagreement,
            lots=sized.get("lots"),
            actual_risk_percent=sized.get("actual_risk_percent"),
        )
    lots = float(sized.get("lots") or 0.0)
    if lots <= 0:
        return None, "the computed size rounds to zero lots at this risk"
    return lots, ""


def run_all_accounts(
    session: Session,
    *,
    now: datetime | None = None,
    kill_switch: Any = None,
) -> dict[str, Any]:
    """Run one cycle per configured account, and let each fail alone.

    Every account gets its own bridge, its own broker and its own pass through
    every gate. Nothing is shared but the kill switch, which is deliberate: a
    halt is a halt across the fleet, and a per-account halt that leaves the
    others trading is not the thing anybody reaches for it to do.

    **One account's failure must not stop the others.** That is the whole
    reason this exists rather than a loop at the call site. A terminal that is
    logged out, a bridge that is not mounted, a rulebook that no longer
    resolves - each of those is a fact about one account, and a fleet that
    stops on the first of them is a fleet that stops on its weakest member.

    So every account is caught individually and its failure is reported beside
    the others' results rather than raised. What is *not* caught is a kill
    switch refusal, because that is not a failure - it is the answer.
    """
    from app.providers.metatrader import MetaTraderBridge, bridge_dirs

    moment = (now or datetime.now(UTC)).astimezone(UTC)
    accounts = bridge_dirs()

    from app.execution import account_switch

    reports: dict[str, Any] = {}
    sent = 0
    for key, directory in sorted(accounts.items()):
        allowed, why = account_switch.state(key)
        if not allowed:
            # Skipped, not failed. A paused account and a broken one look the
            # same in a count of zero orders, and only one of them wants
            # somebody to go and look at it.
            reports[key] = {"orders": 0, "skipped": why}
            continue
        try:
            report = run_cycle(
                session,
                now=moment,
                broker=MetaTraderBroker(directory=directory),
                bridge=MetaTraderBridge(directory=directory),
                kill_switch=kill_switch,
            )
        except Exception as problem:  # noqa: BLE001 - one account, not the fleet
            reports[key] = {
                "orders": 0,
                "refused": (
                    f"{type(problem).__name__} while trading this account. The "
                    "others were unaffected"
                ),
            }
            continue
        reports[key] = report
        sent += int(report.get("orders") or 0)

    return {
        "accounts": len(accounts),
        "orders": sent,
        "by_account": reports,
        "note": (
            "each account ran its own gates against its own terminal. A "
            "failure here is about one account and says which"
        ),
    }


def _conviction_imports() -> None:
    """Documented here rather than imported at module scope.

    `autotrade` is imported by the collector on every cycle and by the tests
    in bulk; the learning modules it now consults pull in the measurement
    stack, and paying for that at import time would slow every path that
    never reaches an order.
    """


def run_cycle(
    session: Session,
    *,
    now: datetime | None = None,
    broker: BrokerAdapter | None = None,
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
    from app.execution import autopilot, conviction, killswitch_store
    from app.learning import edge as edge_registry
    from app.learning import rules as rules_module
    from app.ops import calibration
    from app.providers.metatrader import MetaTraderBridge

    moment = (now or datetime.now(UTC)).astimezone(UTC)
    feed = bridge or MetaTraderBridge()
    sender: BrokerAdapter = broker or MetaTraderBroker()

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
        from app.execution.paper_broker import LivePaperBroker

        sender = broker if broker is not None else LivePaperBroker()

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

    # Bound once: the risk brain gates on it and the conviction step below
    # scores it, and computing it twice invites the two to disagree.
    feed_age_bars = _feed_age_bars(published, moment)
    verdict = _authorise(state, feed_age_bars=feed_age_bars)
    if not verdict.approves:
        return _report(
            mode=mode,
            refused="risk brain: " + "; ".join(verdict.hard_breaches or verdict.reasons),
        )

    # The one decision (`app.ops.authorization`), from every live fact at
    # once: the gates above plus what only the host and the tables know -
    # the restore drill, the secrets scan, the disk, the audit chain, the
    # freshness of every source. Recomputed here every cycle, which is what
    # lets a cleared blocker clear without anything being reset, and written
    # to the audit trail so "why did it not trade at 14:00" has an answer.
    #
    # It can only refuse. Every gate above that already said no has already
    # returned; this adds the operational ones and never removes any.
    authorization = _cycle_authorization(
        session,
        moment=moment,
        published=published,
        account_reason=account_reason,
        risk_verdict=verdict,
        feed_age_bars=_feed_age_bars(published, moment),
        sender=sender,
    )
    if authorization is not None and not authorization.order_authorized:
        return _report(
            mode=mode,
            refused="order authorization: " + "; ".join(authorization.blocking_reasons),
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
    # The broker's specification, checked against the broker's own arithmetic.
    #
    # A gold position closed at -$3,730.76 because the terminal published a
    # tick value ten times too small and every layer trusted it. The identity
    # in `calculators.lot_size` catches that before an order is sent, for
    # instruments whose quote currency can be read from their name; this
    # catches it on anything the account already holds, by dividing the
    # position's own profit by its own move. Reported, never acted on - the
    # sizing correction lives in one place and is tested there.
    try:
        from app.ops import spec_audit

        audit = spec_audit.audit(live_positions, specifications)
        for finding in audit.findings:
            log.warning("autotrade.specification_contradicted_by_profit", **finding.as_dict())
    except Exception as problem:  # noqa: BLE001 - a monitor never stops a cycle
        log.warning("autotrade.spec_audit_unavailable", problem=type(problem).__name__)

    strategies, strategy_refusal = _strategy_for(login)
    if strategies is None:
        return _report(mode=mode, refused=strategy_refusal)
    candidates = _pending(session, moment, login=login, strategies=strategies)
    sent: list[dict[str, Any]] = []
    skipped: list[str] = []

    # Read once for the cycle rather than per candidate: both are account-wide
    # facts and neither moves between symbols.
    edge_allowed, _edge_why = edge_registry.live_trading_allowed()
    try:
        calibrated_sources = len(calibration.measure(session, now=moment).calibrated)
    except Exception:  # noqa: BLE001 - unread is unobserved, which costs confidence
        calibrated_sources = None

    required = _consensus_required()
    # Always built, not only when a majority is demanded: the votes are
    # what tell agreement from contradiction, and contradiction is worth
    # acting on even when one brain is enough to act.
    sides_by_timeframe: dict[tuple[str, str], set[str]] = {}
    votes = _fresh_votes(session, moment, sides_by_timeframe)
    # Read once. It is one aggregate over the journal and it does not change
    # inside a cycle.
    edges = _measured_edge(session)

    for entry in candidates:
        # Resolved before the per-symbol cap, because the cap is about the
        # instrument the account will actually carry: a GCFUT decision and
        # an XAUUSD position are the same exposure under two names.
        traded_as = _tradeable_symbol(entry.symbol)
        if traded_as in held:
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

        # A contradiction is settled by weight of opinion, not by veto.
        #
        # With one brain enough to act, a long from one and a short from
        # another on the same symbol at the same instant both became
        # orders: the fleet ends up flat and pays two spreads for the
        # privilege. Counting agreement does not catch this - each side
        # has its own supporter and neither is outvoted.
        #
        # Disagreement is information rather than noise: the brains read
        # the same bars and reached opposite conclusions, and sitting out
        # costs nothing while being wrong costs the spread twice.
        #
        # But refusing on *any* opposition was a veto, and with seven
        # brains something is almost always on the other side: it blocked
        # sixty-one of sixty-four decisions in one cycle, which is not
        # caution, it is a system that has stopped. A single dissenter
        # against three supporters is a minority, and treating it as a
        # halt gives one brain more power than the other six together.
        #
        # So the side with more brains behind it wins, and a tie refuses:
        # equal weight on both sides is exactly no information, which is
        # the case sitting out was meant for.
        other_side = "short" if entry.decision == "long" else "long"
        against = votes.get((entry.symbol, other_side), set())
        supporting = votes.get((entry.symbol, entry.decision), set())
        # Both names are read again further down by the conviction step, which
        # runs for every candidate rather than only for the ones the consensus
        # rule examines.
        if len(against) >= len(supporting):
            skipped.append(
                f"{entry.symbol}: {len(against)} brains want the other side "
                f"against {len(supporting)} for it "
                f"({', '.join(sorted(against))})"
            )
            continue

        # A fast entry must not fight the hourly picture.
        #
        # The recorder writes a decision per timeframe and nothing ever
        # compared them, so an M5 long and an H1 short on the same
        # instrument were two independent trades rather than one
        # contradiction. The slower frame is the context the faster one
        # is a detail inside: entering against it is trading the noise
        # and paying the spread for the privilege.
        #
        # Only opposition blocks. An hourly frame with no opinion is not
        # a refusal - most instants it has none, and demanding agreement
        # from a frame that is silent would stop nearly everything.
        if str(entry.timeframe) in FAST_TIMEFRAMES:
            slower = sides_by_timeframe.get(
                (entry.symbol, CONTEXT_TIMEFRAME), set()
            )
            if slower and entry.decision not in slower:
                skipped.append(
                    f"{entry.symbol}: the {CONTEXT_TIMEFRAME} decision is "
                    f"{'/'.join(sorted(slower))} and this is "
                    f"{entry.decision} on {entry.timeframe}"
                )
                continue

        if required > 1:
            agreeing = votes.get((entry.symbol, entry.decision), set())
            if len(agreeing) < required:
                # The council rule: one brain moving alone is a hypothesis,
                # not a trade. Named with the count so a symbol every brain
                # ignores and one a single brain loves read differently.
                skipped.append(
                    f"{entry.symbol}: consensus needs {required} brains and "
                    f"{len(agreeing)} agree ({', '.join(sorted(agreeing))})"
                )
                continue

        geometry = entry.before or {}
        price, stop = geometry.get("entry"), geometry.get("stop")
        target = geometry.get("target")
        if price is None or stop is None:
            skipped.append(f"{entry.symbol}: the decision recorded no levels")
            continue

        specification = specifications.get(traded_as)
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
        ceiling, ceiling_why = _cost_ceiling(edges, entry.timeframe)
        if spread_cost > ceiling:
            skipped.append(
                f"{entry.symbol}: spread and slippage cost {spread_cost:.3f} R "
                f"against a {ceiling:.3f} R ceiling - {ceiling_why}. The trade "
                "starts further behind than it is expected to travel"
            )
            continue

        # How much of the permitted risk this particular trade has earned.
        #
        # Every gate above has already said yes; none of them expressed the
        # difference between a trade the evidence barely permits and one it
        # positively supports, so every permitted order was sized the same.
        # This scores that difference and can only spend it downward - the
        # multiplier is capped at 1.0 by construction (`app.execution.
        # conviction`), so a mistake here costs a position that was too small
        # and never one that was too large.
        judgement = conviction.assess(
            side=entry.decision,
            proven_edge=edge_allowed,
            factors=[
                conviction.agreement_factor(
                    agreeing=len(supporting),
                    opposing=len(against),
                ),
                conviction.cost_factor(cost_r=spread_cost, ceiling_r=ceiling),
                conviction.freshness_factor(age_bars=feed_age_bars),
                conviction.calibration_factor(calibrated_sources=calibrated_sources),
                # No regime filter has been confirmed out of sample: the
                # dispersion hypothesis separated the halves by t 1.82 against
                # a required 1.96 on 21 years of daily bars. Reported as
                # unobserved rather than as a pass, because not knowing which
                # regime this is costs confidence - which is the truthful
                # effect of not knowing.
                conviction.regime_factor(aligned=None),
            ],
        )
        if not judgement.allowed:
            skipped.append(
                f"{entry.symbol}: trade power {judgement.score}/100 "
                f"({judgement.tier.label}) - " + "; ".join(judgement.blocks)
            )
            continue
        # The only line where conviction touches money, and it can only take
        # away: `risk_multiplier` is capped at 1.0, so this is a min() of the
        # permitted risk with itself at worst.
        permitted_before_conviction = risk_for_this
        risk_for_this = min(risk_for_this, risk_for_this * judgement.risk_multiplier)

        lots, problem = _lots(
            equity=equity,
            stop_distance=stop_distance,
            specification=specification,
            # The tightest of the three that spoke: the risk brain's ceiling,
            # the challenge headroom folded into it, and what the open book
            # can still absorb at this correlation. Consulting three limits
            # and obeying the loosest is consulting none.
            risk_percent=risk_for_this * 100.0,
            # The account's own currency, from what the terminal published.
            # It is what makes the contract-size cross-check meaningful: a
            # price quoted in the account's currency moves the account by
            # exactly the contract size per lot.
            account_currency=str(published.get("currency") or "") or None,
        )
        if lots is None and judgement.risk_multiplier < 1.0:
            # The lot step is coarse, and on an account whose permitted risk
            # buys only the minimum lot any reduction at all rounds to
            # nothing. That is not conviction deciding against the trade; it
            # is conviction being unable to express a preference, and letting
            # it read as a refusal would make the granularity of the broker's
            # volume step into a trading rule nobody wrote.
            #
            # So the trade proceeds at the risk every gate already approved -
            # never more than that - and the log says conviction had no say.
            lots, problem = _lots(
                equity=equity,
                stop_distance=stop_distance,
                specification=specification,
                risk_percent=permitted_before_conviction * 100.0,
                account_currency=str(published.get("currency") or "") or None,
            )
            if lots:
                risk_for_this = permitted_before_conviction
                log.info(
                    "autotrade.conviction_not_expressible",
                    symbol=entry.symbol,
                    score=judgement.score,
                    wanted_multiplier=round(judgement.risk_multiplier, 3),
                    lots=lots,
                    detail=(
                        "the permitted risk buys only the minimum lot, so the "
                        "reduction rounds to nothing and the trade goes at the "
                        "approved size"
                    ),
                )
        if lots is None:
            skipped.append(f"{entry.symbol}: {problem}")
            continue

        try:
            intent = OrderIntent(
                # The instrument the broker fills, which is not always the
                # one the rule ranked. See EXECUTION_SYMBOL.
                symbol=traded_as,
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
        # Keyed by account, because the fleet shares one journal. The old
        # single "order" key made every decision spendable exactly once
        # across all accounts, so whichever account ran first starved the
        # rest - once-ever is a per-account promise, not a fleet-wide one.
        entry.during = {
            **(entry.during or {}),
            "orders": {
                **((entry.during or {}).get("orders") or {}),
                login: {
                    "intent_id": str(intent.intent_id),
                    "lots": lots,
                    "state": "submitting",
                    "at": moment.isoformat(),
                },
            },
        }
        session.commit()

        report = sender.submit(intent)
        entry.during = {
            **(entry.during or {}),
            "orders": {
                **((entry.during or {}).get("orders") or {}),
                login: {
                    "intent_id": str(intent.intent_id),
                    "lots": lots,
                    "state": str(report.state),
                    "ticket": report.broker_order_id,
                    "fill": report.average_price,
                    "reason": report.reason,
                    "at": moment.isoformat(),
                },
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
        # Said out loud, on the channel somebody reads.
        #
        # The bot could answer questions and could not tell anybody anything,
        # so learning that an order had filled meant thinking to ask - and
        # what came back was every open position at once, which answers "what
        # do I hold" and never "what just happened". Announced per fill, with
        # the account named, because eight terminals and a notice that does
        # not say which one traded is a notice that starts a hunt.
        #
        # Never fatal. The order is already at the broker by the time this
        # runs, and a telegram outage must not raise into a loop that would
        # then forget a position the account genuinely holds.
        try:
            from app.integrations import trade_notice

            trade_notice.announce(
                session,
                trade_notice.position_opened(
                    terminal=str(published.get("server") or "terminal"),
                    login=login,
                    symbol=traded_as,
                    side=entry.decision,
                    lots=lots,
                    # What the broker returned, not what was asked for. A
                    # notice quoting the intended price is right almost
                    # always and wrong exactly when somebody needs to look.
                    fill=report.average_price,
                    stop=stop,
                    target=target,
                    risk_money=(
                        equity * risk_for_this if equity else None
                    ),
                    currency=str(published.get("currency") or ""),
                    risk_percent=round(risk_for_this * 100.0, 3),
                    strategy=entry.strategy,
                    ticket=report.broker_order_id,
                    at=moment,
                ),
            )
        except Exception:  # noqa: BLE001, S110 - a channel is not the trade
            pass

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


def _consensus_required() -> int:
    """How many brains must agree before an order is sent.

    1 is the pre-council behaviour: a brain's own decision is enough. 2 is
    the roadmap's agreement gate. Floored at 1 because zero would mean an
    order nobody decided, which is not a looser setting - it is nonsense.
    """
    from app.core.config import get_settings

    return max(1, int(getattr(get_settings(), "consensus_required", 1)))


def _fresh_votes(
    session: Session,
    moment: datetime,
    by_timeframe: dict[tuple[str, str], set[str]] | None = None,
) -> dict[tuple[str, str], set[str]]:
    """(symbol, side) -> the brains with a fresh decision saying exactly that.

    Every brain votes, including the ones that only record: the whole value
    of writing a non-trading brain's decisions down is that they can second
    a trading brain's motion. Freshness is the same window an order gets -
    a stale agreement is agreement about a price that has moved.
    """
    from datetime import timedelta

    cutoff = moment - timedelta(
        minutes=MAX_DECISION_AGE_MINUTES + DECISION_BAR_MINUTES
    )
    rows = session.scalars(
        select(JournalEntry).where(
            JournalEntry.arm == ARM_RULE,
            JournalEntry.closed_at.is_(None),
            JournalEntry.opened_at >= cutoff,
        )
    ).all()

    votes: dict[tuple[str, str], set[str]] = {}
    # Filled for the caller when one is supplied: which sides exist on
    # each timeframe, which is a different question from how many brains
    # are on each side.
    if by_timeframe is None:
        by_timeframe = {}
    for row in rows:
        if row.opened_at < moment - timedelta(
            minutes=MAX_DECISION_AGE_MINUTES + _bar_minutes(row)
        ):
            continue
        votes.setdefault((row.symbol, row.decision), set()).add(row.strategy)
        by_timeframe.setdefault((row.symbol, row.timeframe), set()).add(
            row.decision
        )
    return votes

#: Brains an unassigned account may be given, in a fixed order.
#:
#: Measured on this deployment's own journal rather than chosen by taste:
#:
#:     cross-sectional-stretch  1878 resolved  +0.124 R  56% win
#:     carry-differential        312 resolved  +0.218 R  61% win
#:     short-horizon-reversal   1040 resolved  +0.056 R  53% win
#:
#: `time-series-momentum` is absent because it measured -0.119 R over 377
#: resolved decisions, and the three brains added later are absent because
#: they have no resolved decisions at all yet. A default is not the place to
#: put something unmeasured - assign those by hand, deliberately, when
#: somebody wants to start measuring them.
DEFAULT_STRATEGIES: tuple[str, ...] = (
    "cross-sectional-stretch",
    "carry-differential",
    "short-horizon-reversal",
)


def _default_strategy(login: str) -> str:
    """Which brain an account nobody assigned should trade.

    From the login's digits, so it is stable without storing anything: the
    same account gets the same brain after a restart, a redeploy, or a
    rebuild of this container. A counter would drift; a random pick would
    make two runs of the same fleet incomparable.
    """
    digits = "".join(ch for ch in str(login) if ch.isdigit())
    if not digits:
        return DEFAULT_STRATEGIES[0]
    return DEFAULT_STRATEGIES[int(digits[-4:]) % len(DEFAULT_STRATEGIES)]


def _strategy_for(login: str) -> tuple[frozenset[str] | None, str]:
    """Which brains this account trades, or why it must not trade at all.

    Unassigned means the incumbent - the behaviour every account had before
    brains were separable. Assigned to a name nothing registered means no
    trading, stated: an account trading a brain nobody wrote is worse than
    one that sits out and says why.

    An account may hold several, written `login=first+second`. One brain per
    account was a rule about accounts pretending to be a rule about brains:
    seven brains were registered and recording, three of them added on
    request, and five of the seven had never produced a single order because
    no account named them. They were deciding into a drawer. Trading a brain
    is a property of the fleet, not a scarce slot, and the number of demo
    accounts somebody has opened is the wrong thing to ration it by.

    What still bounds the account is what always did - the position cap, the
    per-symbol cap, the daily loss limit and the portfolio brain - and those
    are counted per account rather than per brain, so adding a second brain
    widens what may be considered without widening what may be held.
    """
    from app.core.config import get_settings
    from app.learning import rules as rules_module
    from app.models.journal import STRATEGY_INCUMBENT

    raw = str(getattr(get_settings(), "account_strategies", "") or "")
    assigned: dict[str, str] = {}
    for piece in raw.split(","):
        if "=" in piece:
            key, _, value = piece.partition("=")
            assigned[key.strip()] = value.strip()

    raw_names = assigned.get(login)
    if raw_names is None:
        # Nobody assigned this account, and that is the normal case: an
        # account is registered on a web page by somebody who should not have
        # to also edit an environment variable, and until now that meant every
        # unassigned account silently traded the incumbent. Eight terminals
        # all running one brain measures that brain eight times and the other
        # six not at all.
        #
        # So the fleet spreads itself. The order is fixed and the choice is
        # the login's own digits, so the same account always lands on the same
        # brain - across restarts, across redeploys, and without any state to
        # keep. Two accounts can collide, which is fine: they are two samples
        # of one brain, not a lost one.
        raw_names = _default_strategy(login)
    names = [piece.strip() for piece in str(raw_names).split("+") if piece.strip()]
    # An assignment of nothing at all is a typo, not an instruction to trade
    # the incumbent: `login=` reads as somebody meaning to name a brain.
    if not names:
        return None, (
            f"account {login} is assigned an empty strategy - refusing to "
            "trade rather than falling back to a brain nobody chose"
        )

    unknown = sorted(
        {
            name
            for name in names
            if name != STRATEGY_INCUMBENT and rules_module.get(name) is None
        }
    )
    if unknown:
        # Any unknown name refuses the whole account rather than only that
        # brain. A typo silently dropping one brain and trading the rest is
        # the same account running a strategy nobody wrote down.
        listed = ", ".join(repr(name) for name in unknown)
        return None, (
            f"account {login} is assigned strategy {listed}, which is not one "
            "this build knows - refusing to trade rather than guessing a brain"
        )
    return frozenset(names), ""


def _pending(
    session: Session, moment: datetime, *, login: str, strategies: frozenset[str]
) -> list[JournalEntry]:
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
            or_(
                JournalEntry.price_source.in_(
                    [SOURCE_BROKER, *sorted(REANCHORED_SOURCES)]
                ),
                # Admitted on the instrument rather than on the feed. See
                # REANCHORED_SYMBOLS for why gold is the exception.
                JournalEntry.symbol.in_(sorted(REANCHORED_SYMBOLS)),
            ),
            JournalEntry.closed_at.is_(None),
            # This account's brains only. The whole point of separable
            # brains is that an account never trades a blend nobody designed
            # - which is a statement about the blend being written down, not
            # about it having exactly one member.
            JournalEntry.strategy.in_(sorted(strategies)),
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
    return [row for row in fresh if _needs_an_order(row, login)]


#: The one rejection reason that proves nothing reached the broker.
#:
#: Written by the adapter when the request file itself could not be created,
#: which is the case where retrying is provably safe: no file means the expert
#: never saw it and no position exists. Matching on the reason is narrow on
#: purpose - any broader rule risks resending an order that was placed.
NEVER_SENT = "the request could not be written"


def _needs_an_order(entry: JournalEntry, login: str) -> bool:
    """Whether this decision still owes *this account* an order.

    A decision that already carries one for this account is left alone,
    including a rejected one: a rejection from the broker means it saw the
    request and said no, and resending it is how one refusal becomes two
    positions when the refusal was transient.

    Per account, because the fleet shares one journal. Under the old
    fleet-wide reading, whichever account ran first spent the decision and
    the rest never traded at all - which looked exactly like the rule
    declining, for every account but one.

    The single exception is a request that was never written at all. Four
    orders were lost that way on the first live cycle, to a read-only mount,
    and re-deriving them from the decisions that are still sitting there is
    exactly what a decision-first design is for.
    """
    during = entry.during or {}
    order = (during.get("orders") or {}).get(login)
    if order is None:
        # The pre-fleet shape: one unkeyed order, account unknown. Claimed
        # for everyone, because guessing whose it was risks doubling it.
        order = during.get("order")
    if not order:
        return True
    if order.get("state") != str(OrderState.REJECTED):
        return False
    return NEVER_SENT in str(order.get("reason") or "")


def _cycle_authorization(
    session: Session,
    *,
    moment: datetime,
    published: dict[str, Any],
    account_reason: str,
    risk_verdict: Any,
    feed_age_bars: float | None,
    sender: Any,
) -> Any:
    """The cycle's order-authorization decision, audited.

    Returns None only when the posture itself could not be gathered - and
    says so in the log - so a broken reader does not silently halt a cycle
    that the gates above had already approved. Every individual reader
    inside `posture.gather` already fails closed as an undeterminable check;
    this guards the gatherer, not the checks.
    """
    from app.ops import posture as posture_module

    try:
        posture = posture_module.gather(
            session,
            now=moment,
            account=published,
            account_reason=account_reason,
            risk_approved=bool(risk_verdict.approves),
            risk_reason="; ".join(risk_verdict.reasons or []) or "the risk brain approves",
            data_age_bars=feed_age_bars,
            broker_adapter=sender,
        )
    except Exception as problem:  # noqa: BLE001 - reported, and the cycle continues on its own gates
        log.warning(
            "autotrade.authorization_unavailable",
            problem=type(problem).__name__,
            detail=str(problem)[:200],
        )
        return None
    decision = posture.decision
    log.info(
        "autotrade.authorization",
        authorized=decision.order_authorized,
        engine=decision.engine.value,
        kill_switch=decision.kill_switch.value,
        blocking=decision.blocking_reasons,
        advisories=decision.advisories,
        reader_failures=posture.reader_failures,
    )
    try:
        from app.services import audit

        audit.record(
            session,
            "execution.authorization",
            summary=(
                "orders authorised"
                if decision.order_authorized
                else "orders blocked: " + "; ".join(decision.blocking_reasons)[:400]
            ),
            payload={
                "engine_state": decision.engine.value,
                "kill_switch_state": decision.kill_switch.value,
                "order_authorization_state": decision.authorization.value,
                "blocking_reasons": decision.blocking_reasons,
                "advisories": decision.advisories,
                "login": str(published.get("login") or ""),
            },
            service="autotrade",
        )
    except Exception as problem:  # noqa: BLE001 - the audit must not decide the trade
        log.warning("autotrade.authorization_unaudited", problem=type(problem).__name__)
    return decision


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
