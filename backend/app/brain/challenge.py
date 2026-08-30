"""Challenge engine (spec phase 28, §30).

Prop-firm and funded-account rules, checked *before* execution.

A funded account is not an ordinary account with extra paperwork. It is an
account that can be taken away in a single afternoon by a rule that has nothing
to say about whether the trade was good. The daily drawdown does not care that
the setup was clean: it counts money once, at the moment the equity prints, and
there is no appeal.

So this module answers the one question the risk brain does not ask — *if this
trade loses everything it risks, is the challenge still alive?* That projection
is the point of the module and the reason it runs before execution rather than
after. A trade whose full loss ends the challenge is not a trade with a bad
outcome; it is a trade that must not be placed, and finding that out afterwards
is a post-mortem, not a control.

Three properties follow, and they are the same three the risk brain has:

**Every rule is optional, and absent is not zero.** A provider that imposes no
daily drawdown and a provider that permits a daily loss of exactly zero are
opposite accounts. `None` means the rule does not exist; `0.0` means the rule
exists and allows nothing.

**Unmeasured is never satisfied.** A rule whose inputs are missing lands in
`unverified` and gates new positions. It does not quietly pass, and it does not
become a breach either — this module will not accuse an account of violating
something it never measured.

**Each rule is read the way the provider reads it: in whichever direction costs
the account.** Drawdown is measured on equity, so floating losses count the
instant they exist. The profit target is measured on balance, so floating
profits do not count at all. Both readings are the unfavourable one, and both
are what the provider's server actually does.

Nothing here places an order, sizes a lot, or speaks to a broker. It returns a
verdict and a headroom. Execution is phase 25 and does not exist yet.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any, Final

from app.core.enums import AssetClass

# Below this many days there is no distribution to speak of. One profitable day
# is trivially 100% of the profit, so judging consistency that early would fail
# every account on its first winning day — the rule is reported as unjudged
# instead, which is the difference between "we checked" and "we could not".
MIN_CONSISTENCY_DAYS = 3

# How much of a drawdown allowance must be spent before it is worth saying so.
# Policy, not measurement: no supplied field could confirm or refute it.
WARNING_THRESHOLD = 0.75

# The same question for leverage, which is a different quantity with a
# different distribution. They were one constant, which made the pair of
# thresholds look like a finding rather than two independent choices.
LEVERAGE_WARNING_SHARE = 0.75

# A stop does not fill at the stop. Sizing a trade so its modelled loss lands
# exactly on the drawdown floor assumes a fill that costs nothing to obtain;
# the buffer keeps the modelled worst case short of the real one. Policy, and
# published in the payload so a reader can see a haircut was applied rather
# than mistaking the result for an unshaded measurement.
SLIPPAGE_BUFFER = 0.9


class DrawdownBasis(StrEnum):
    """What the provider's server watches when it decides to close an account.

    Equity moves the moment a position does; balance only moves when one
    closes. An account judged on balance can look untouched while its equity
    has already gone through the floor — and the provider, who was watching
    equity, closed it twenty minutes ago. Most providers measure equity, which
    is why that is the default here.
    """

    EQUITY = "equity"
    BALANCE = "balance"


class AllowanceBasis(StrEnum):
    """What the drawdown percentages are a percentage *of*.

    Most providers quote a fixed figure - "5% of a 100k account" - but some
    recompute the daily allowance off the current balance, which shrinks the
    rope exactly as the account draws down. The difference only shows up on
    the accounts where the rule actually bites, so it cannot be assumed.
    """

    STARTING_BALANCE = "starting_balance"
    CURRENT_BALANCE = "current_balance"


class NotImposed:
    """A deliberate statement that a provider carries no such rule.

    It exists so that "nobody entered this rulebook" and "this provider caps
    nothing" stop being the same value. They are opposite facts about an
    account, and the second one is a claim about a document somebody has to
    have read — so it has to be written down rather than arrived at by leaving
    a field alone.

    `None` keeps its English meaning throughout this module: nobody said. Every
    rule defaults to it, so an un-entered rulebook now blocks instead of
    approving.
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "NOT_IMPOSED"

    def __bool__(self) -> bool:
        """Falsey, so an accidental `if rules.max_leverage:` still reads as
        "there is no cap here" rather than silently enforcing one."""
        return False


NOT_IMPOSED: Final = NotImposed()

#: A numeric rule: a figure, `NOT_IMPOSED`, or `None` for nobody said.
Rule = float | NotImposed | None
IntRule = int | NotImposed | None
FlagRule = bool | NotImposed | None


@dataclass(frozen=True)
class LeverageCaps:
    """Leverage the way providers actually publish it: one cap per asset class.

    `max_leverage` was a single float, and that cannot hold what FundedNext
    prints on one page: forex 1:100 and crypto 1:1 on the same account. Any
    one number is false for some instrument that account can trade, and the
    two ways of being wrong are both bad - too high permits what the
    provider's server will reject, too low refuses what it would have
    allowed. Neither is a cap; both are a guess wearing one.

    A cap for an asset class that is not listed falls back to the most
    restrictive one that is. That is the same rule the rest of this module
    follows: not knowing may only reduce exposure, never grant it.
    """

    by_asset: Mapping[AssetClass, float]

    def __post_init__(self) -> None:
        if not self.by_asset:
            raise ValueError(
                "leverage caps with no asset class say nothing - use None for "
                "unread and NOT_IMPOSED for a provider that caps nothing"
            )
        for asset, cap in self.by_asset.items():
            if not isinstance(cap, float | int) or isinstance(cap, bool):
                raise ValueError(f"the {asset} leverage cap must be a number")
            if not cap > 0:
                raise ValueError(
                    f"the {asset} leverage cap must be above zero; a cap of "
                    f"{cap} forbids every position and is not what a page "
                    "saying 1:1 means"
                )

    @property
    def most_restrictive(self) -> float:
        return float(min(self.by_asset.values()))

    def binding(self, asset: AssetClass | None) -> float:
        """The cap governing a trade in `asset`; the tightest when unnamed."""
        if asset is None:
            return self.most_restrictive
        return float(self.by_asset.get(asset, self.most_restrictive))


@dataclass
class ChallengeRules:
    """One provider's rulebook, per account.

    Every rule is `None` by default, meaning **nobody entered it** — not that
    the provider does not impose it. Those were the same value until a probe
    showed that `ChallengeRules()` approved a trade with no breach, no gate and
    nothing in `unverified`: the module was asserting that an unnamed provider
    caps nothing, on the strength of a field nobody had filled in.

    To say a provider genuinely imposes no rule, write `NOT_IMPOSED`. It is a
    claim about a document somebody read, so it has to be stated.

    Defaulting any of these to `0.0` would make "no daily drawdown rule" and
    "no daily loss permitted" the same object, and they are opposite accounts.
    """

    profit_target_pct: Rule = None
    max_daily_drawdown_pct: Rule = None
    max_total_drawdown_pct: Rule = None
    min_trading_days: IntRule = None
    max_trading_days: IntRule = None
    #: A figure, per-asset `LeverageCaps`, NOT_IMPOSED, or None for unread.
    max_leverage: Rule | LeverageCaps = None
    # No single day may be more than this share of total profit.
    max_single_day_profit_share: Rule = None
    news_trading_allowed: FlagRule = None
    weekend_holding_allowed: FlagRule = None
    max_concurrent_positions: IntRule = None

    #: Whether software may choose the trades.
    #:
    #: Not a number, and the only rule in this list that can rule this platform
    #: out of an account entirely. Providers draw the line in different places:
    #: several permit money-management and copy-trading experts while
    #: forbidding automated decision-making, which is precisely what this
    #: system does.
    #:
    #: `None` means nobody read the document, and here that is not the same as
    #: permission: this rule cannot be answered by trading smaller, because the
    #: question is whether software may choose the trades at all.
    #:
    #: It is nonetheless **reported and not gated**. This comment used to say
    #: the opposite - "this one cannot be reduced, so it stops" - and had said
    #: it since before `check` was changed to report it, so the description of
    #: the safety layer and the safety layer disagreed about whether a trade
    #: gets through. The reasoning for reporting is at the check itself; the
    #: reasoning for stopping is the paragraph above, and it has not been
    #: withdrawn. Whether to gate is an open decision, not a settled one.
    #:
    #: What that means in practice, now that the gate supplies an R value: a
    #: registered account passes the challenge gate with this permission
    #: unread. Four execution switches still stand behind it.
    automated_trading_allowed: FlagRule = None

    # Not rules but rulers — how the two drawdown rules above are read.
    drawdown_basis: DrawdownBasis = DrawdownBasis.EQUITY
    # `None` means nobody said, and the smaller of the two bases is used. The
    # alternative - assuming the starting balance - grants a drawn-down account
    # more rope than the provider does, which clears risk their server will
    # reject.
    allowance_basis: AllowanceBasis | None = None
    # Whether the total drawdown floor trails the account's peak or stays
    # anchored to the starting balance. Providers do both, the difference is
    # the whole account once it is in profit, and `None` means nobody said.
    total_drawdown_trailing: bool | None = None


@dataclass
class ChallengeState:
    """The account as the provider's server currently sees it.

    The first seven fields are required. An optional equity or position count
    would let a caller omit the one number that would have refused the trade.
    """

    starting_balance: float
    current_equity: float
    # Highest equity reached. Providers that trail on balance instead should
    # supply the peak on the basis they are measured on.
    peak_equity: float
    daily_starting_equity: float
    days_traded: int
    open_positions: int
    current_date: date

    # Realised profit per day. Kept separate from `days_traded` because a
    # provider counts a day on which a trade was placed, whether or not it
    # produced a P&L row worth storing.
    daily_profits: dict[date, float] = field(default_factory=dict)

    current_balance: float | None = None
    # The day's opening balance. Required for a balance-basis account: the
    # day's opening *equity* is a different ruler, and using it puts the daily
    # floor below the provider's whenever the day opened with a floating loss.
    daily_starting_balance: float | None = None
    current_leverage: float | None = None
    #: What the proposed trade is in, so a per-asset cap can be resolved.
    #: `None` is honest and costs exposure rather than granting it: the
    #: tightest published cap applies to a trade nobody identified.
    asset_class: AssetClass | None = None
    # What one R is worth in account currency. Without it a risk expressed in R
    # cannot be turned into a loss in money, and the loss projection — the only
    # part of this module that can refuse a trade before it exists — cannot be
    # computed at all.
    currency_per_r: float | None = None
    in_news_window: bool | None = None
    # True when the current session is the last before the weekend break.
    weekend_ahead: bool | None = None


@dataclass
class Headroom:
    """How much may still be lost before one limit binds, in account currency.

    `imposed` and `available` are deliberately separate. A limit the provider
    never set and a limit that could not be measured are both "no number", and
    only the first is safe to ignore.
    """

    limit: str  # "daily" | "total"
    imposed: bool
    available: bool
    amount: float | None = None
    floor: float | None = None
    allowance: float | None = None
    consumed: float | None = None
    breached: bool | None = None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        if not self.available:
            return {
                "limit": self.limit,
                "imposed": self.imposed,
                "available": False,
                "reason": self.reason,
            }
        return {
            "limit": self.limit,
            "imposed": True,
            "available": True,
            "amount": round(self.amount, 2) if self.amount is not None else None,
            "floor": round(self.floor, 2) if self.floor is not None else None,
            "allowance": round(self.allowance, 2) if self.allowance is not None else None,
            "consumed": round(self.consumed, 6) if self.consumed is not None else None,
            "breached": self.breached,
        }


@dataclass
class ConsistencyReport:
    """Whether the profit is spread across days or came from one of them."""

    available: bool
    reason: str | None = None
    days: int = 0
    total_profit: float | None = None
    best_day: date | None = None
    best_day_profit: float | None = None
    best_day_share: float | None = None
    limit: float | None = None
    within_limit: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        if not self.available:
            return {"available": False, "reason": self.reason, "days": self.days}
        return {
            "available": True,
            "days": self.days,
            "total_profit": round(self.total_profit, 2) if self.total_profit is not None else None,
            "best_day": self.best_day.isoformat() if self.best_day else None,
            "best_day_profit": (
                round(self.best_day_profit, 2) if self.best_day_profit is not None else None
            ),
            "best_day_share": (
                round(self.best_day_share, 6) if self.best_day_share is not None else None
            ),
            "limit": self.limit,
            "within_limit": self.within_limit,
        }


@dataclass
class LossProjection:
    """The account as it would stand if the proposed trade lost in full."""

    available: bool
    reason: str | None = None
    risk_r: float | None = None
    loss_amount: float | None = None
    projected_value: float | None = None
    breaches_daily: bool | None = None
    breaches_total: bool | None = None
    # True only when every imposed limit was measured and none of them breaks.
    # None means at least one could not be measured, which is not a pass.
    survivable: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        if not self.available:
            return {"available": False, "reason": self.reason, "survivable": self.survivable}
        return {
            "available": True,
            "risk_r": self.risk_r,
            "loss_amount": round(self.loss_amount, 2) if self.loss_amount is not None else None,
            "projected_value": (
                round(self.projected_value, 2) if self.projected_value is not None else None
            ),
            "breaches_daily": self.breaches_daily,
            "breaches_total": self.breaches_total,
            "survivable": self.survivable,
            "reason": self.reason,
        }


@dataclass
class ChallengeVerdict:
    """The answer, split three ways by how well it is known.

    `breaches` are measured violations — the challenge is failed. `warnings`
    are measured and close. `unverified` is what could not be checked at all;
    it never turns into either of the other two, because a rule nobody measured
    can be neither satisfied nor broken.
    """

    status: str  # "passed" | "failed" | "in_progress"
    allowed: bool
    verdict: str  # "approve" | "reduce" | "block"
    # Largest new risk the drawdown limits can absorb. `None` means the
    # challenge imposes no drawdown limit at all — never a stand-in for a
    # number that could not be measured, which blocks and reports 0.0.
    max_additional_risk_r: float | None
    daily: Headroom
    total: Headroom
    consistency: ConsistencyReport
    projection: LossProjection
    # False when a drawdown limit is imposed but could not be turned into a
    # risk figure. Without this flag the caller sees the same `None` either
    # way, and "this provider caps nothing" and "we could not work out the cap"
    # are opposite facts. The verdict blocks in the second case, so the flag is
    # an explanation rather than the safeguard itself.
    risk_cap_measurable: bool = True
    breaches: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)
    #: Reasons nothing new may be opened *now*, as distinct from rules the
    #: account has broken (`breaches`) and rules nobody entered (`unverified`).
    #:
    #: Published because `allowed` was computed from these and then dropped, so
    #: a caller saw a refusal with an empty `breaches` list and had to guess.
    #: The one caller guessed "the rulebook is incomplete", which is right for
    #: an unentered rule and wrong for a rule that is entered and could not be
    #: measured - and those need opposite responses from whoever reads it.
    gates: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return self.status == "failed"

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "allowed": self.allowed,
            "verdict": self.verdict,
            "max_additional_risk_r": (
                round(self.max_additional_risk_r, 4)
                if self.max_additional_risk_r is not None
                else None
            ),
            "risk_cap_measurable": self.risk_cap_measurable,
            # Published so the size is not read as an unshaded measurement.
            "slippage_buffer_applied": SLIPPAGE_BUFFER,
            "breaches": self.breaches,
            "warnings": self.warnings,
            "unverified": self.unverified,
            "headroom": {"daily": self.daily.as_dict(), "total": self.total.as_dict()},
            "consistency": self.consistency.as_dict(),
            "projection": self.projection.as_dict(),
            # Stated on every response so no consumer can mistake a passing
            # challenge check for permission to place an order.
            "authorises_execution": False,
            "note": "challenge rules are checked before execution; nothing here places an order",
        }


def _money(value: float) -> float:
    """Round to the smallest currency unit before comparing.

    Limits are money and money resolves to cents. Left in binary floating
    point, 10% of a 100,000 account is 110,000.000000000015, which puts a
    cent-exact balance a fraction of a cent the wrong side of a target it has
    actually reached — and failing an account on a representation artefact is
    still failing the account.
    """
    return round(value, 2)


def _refuse(reason: str) -> ChallengeVerdict:
    """A state that cannot be measured at all. Refuse everything, say why once.

    The limits are reported as imposed-but-unmeasured rather than absent: with
    the state incoherent we do not know which rules apply, and "might exist,
    could not be checked" is the reading that blocks.
    """
    return ChallengeVerdict(
        status="in_progress",
        allowed=False,
        verdict="block",
        max_additional_risk_r=0.0,
        daily=Headroom(limit="daily", imposed=True, available=False, reason=reason),
        total=Headroom(limit="total", imposed=True, available=False, reason=reason),
        consistency=ConsistencyReport(available=False, reason=reason),
        projection=LossProjection(available=False, reason=reason),
        unverified=[reason],
        gates=[reason],
    )


def _reference(rules: ChallengeRules, state: ChallengeState) -> tuple[float | None, str | None]:
    """The account value the drawdown rules are measured on, or why there isn't one.

    When the rulebook says balance and no balance was supplied, this returns
    nothing rather than substituting equity. The substitution is not neutral:
    with a position in profit, equity sits above balance, so the swap would err
    in the one direction that loses the account.
    """
    if rules.drawdown_basis is DrawdownBasis.EQUITY:
        return state.current_equity, None
    if state.current_balance is None:
        return None, "drawdown is measured on balance and no balance was supplied"
    return state.current_balance, None


def _daily_anchor(
    rules: ChallengeRules, state: ChallengeState
) -> tuple[float | None, str | None]:
    """Where the daily drawdown is measured from, on the rulebook's own basis.

    Mixing the two rulers is not a rounding error. A balance-basis account
    whose day opened with a floating loss has an opening equity below its
    opening balance, so anchoring on equity drops the floor by exactly that
    loss and hands back rope the provider never granted.
    """
    if rules.drawdown_basis is DrawdownBasis.EQUITY:
        return state.daily_starting_equity, None
    if state.daily_starting_balance is None:
        return None, (
            "daily drawdown is measured on balance and no opening balance was "
            "supplied - the day's opening equity is a different ruler"
        )
    return state.daily_starting_balance, None


def _allowance_base(
    rules: ChallengeRules, state: ChallengeState, reference: float | None
) -> tuple[float, str | None]:
    """The figure the drawdown percentages are taken of."""
    if rules.allowance_basis is AllowanceBasis.STARTING_BALANCE:
        return state.starting_balance, None
    if rules.allowance_basis is AllowanceBasis.CURRENT_BALANCE:
        return state.starting_balance if reference is None else reference, None
    if reference is None or reference >= state.starting_balance:
        return state.starting_balance, None
    return reference, (
        "allowance basis unspecified - the percentage is taken of the smaller "
        "of the starting and current balance"
    )


def _total_anchor(
    rules: ChallengeRules, state: ChallengeState, peak: float
) -> tuple[float, str | None]:
    """Where the total drawdown is measured from."""
    if rules.total_drawdown_trailing is True:
        return peak, None
    if rules.total_drawdown_trailing is False:
        return state.starting_balance, None
    # Unspecified. The higher anchor puts the floor closer to the account, so
    # taking the higher of the two is the strict reading; guessing the other
    # way would be guessing in the direction that ends the challenge.
    anchor = max(peak, state.starting_balance)
    note = "total drawdown anchor unspecified — measured from the stricter of peak and start"
    return anchor, note


def _headroom(
    limit: str,
    *,
    pct: Rule,
    reference: float | None,
    anchor: float | None,
    allowance_base: float,
    unmeasurable: str | None,
) -> Headroom:
    """Turn one drawdown rule into a number, or explain why it cannot be one.

    `anchor` is what the loss is measured *from* — the day's opening equity for
    the daily rule, the peak or the starting balance for the total one.
    `allowance_base` is what the percentage is *of*, chosen by
    `_allowance_base` from the rulebook rather than assumed here.
    """
    if isinstance(pct, NotImposed):
        return Headroom(
            limit=limit,
            imposed=False,
            available=False,
            reason="this provider imposes no such rule",
        )
    if pct is None:
        # Treated as imposed-but-unmeasurable rather than absent, which routes
        # it into `unmeasured_limits` and blocks. An unknown drawdown rule is
        # the one place a challenge account cannot afford an optimistic read.
        return Headroom(
            limit=limit,
            imposed=True,
            available=False,
            reason=(
                f"the {limit} drawdown rule was never entered; not knowing a "
                "provider's limit is not evidence that they have none"
            ),
        )
    if reference is None or anchor is None:
        return Headroom(
            limit=limit,
            imposed=True,
            available=False,
            reason=unmeasurable or "no measurable account value",
        )

    allowance = _money(pct * allowance_base)
    floor = _money(anchor - allowance)
    used = anchor - reference
    # With a zero allowance the share spent is undefined, not 0% and not 100%.
    # Publishing either put an invented ratio in a field named `consumed`.
    consumed = used / allowance if allowance > 0 else None
    return Headroom(
        limit=limit,
        imposed=True,
        available=True,
        amount=max(0.0, reference - floor),
        floor=floor,
        allowance=allowance,
        consumed=consumed,
        # Strictly below, not at. An account sitting exactly on its floor has
        # not lost more than the limit; it also has no room for another trade,
        # so the distinction only decides whether the account is already dead.
        breached=reference < floor,
    )


def evaluate_consistency(
    max_share: Rule, daily_profits: dict[date, float]
) -> ConsistencyReport:
    """Is the profit spread across days, or is it one day wearing a disguise?

    Computed from the actual per-day history and from nothing else. When the
    history is too short the answer is "not judged" — passing by default would
    hand a clean bill of health to the exact account the rule exists to catch,
    the one that made its target in a single afternoon.
    """
    days = len(daily_profits)
    if isinstance(max_share, NotImposed):
        return ConsistencyReport(
            available=False, reason="this provider imposes no consistency rule", days=days
        )
    if max_share is None:
        return ConsistencyReport(
            available=False,
            reason="the consistency rule was never entered, so it was not checked",
            days=days,
        )
    if days < MIN_CONSISTENCY_DAYS:
        return ConsistencyReport(
            available=False,
            reason=f"insufficient days to judge: {days} of {MIN_CONSISTENCY_DAYS} needed",
            days=days,
        )

    total = sum(daily_profits.values())
    if total <= 0:
        return ConsistencyReport(
            available=False,
            reason="no net profit yet to apportion",
            days=days,
            total_profit=total,
            limit=max_share,
        )

    best_day, best_profit = max(daily_profits.items(), key=lambda item: item[1])
    share = best_profit / total
    return ConsistencyReport(
        available=True,
        days=days,
        total_profit=total,
        best_day=best_day,
        best_day_profit=best_profit,
        best_day_share=share,
        limit=max_share,
        within_limit=share <= max_share,
    )


def project_full_loss(
    *,
    risk_r: float | None,
    reference: float | None,
    currency_per_r: float | None,
    daily: Headroom,
    total: Headroom,
) -> LossProjection:
    """What this trade losing in full would do to the challenge.

    The heart of the module. Every other check here reports something that has
    already happened; this one is the only one that can still be acted on.
    """
    if risk_r is None:
        return LossProjection(available=False, reason="no trade proposed")
    if risk_r <= 0:
        return LossProjection(available=False, reason="proposed risk must be positive")

    imposed = [h for h in (daily, total) if h.imposed]
    if not imposed:
        # Nothing to breach, so nothing to compute. This is the one route to a
        # survivable projection without a loss figure, and it is survivable
        # because the rulebook is empty rather than because the state was.
        return LossProjection(
            available=True,
            reason="the challenge imposes no drawdown limit for a loss to breach",
            risk_r=risk_r,
            survivable=True,
        )
    if currency_per_r is None or currency_per_r <= 0:
        return LossProjection(
            available=False,
            risk_r=risk_r,
            reason="one R is not expressed in account currency — the loss cannot be projected",
        )
    if reference is None:
        return LossProjection(
            available=False, risk_r=risk_r, reason="no measurable account value to project from"
        )

    loss = risk_r * currency_per_r
    projected = reference - loss

    outcomes: list[bool | None] = []
    results: dict[str, bool | None] = {}
    for headroom in imposed:
        breaks = projected < headroom.floor if headroom.floor is not None else None
        results[headroom.limit] = breaks
        outcomes.append(breaks)

    if any(outcome is True for outcome in outcomes):
        survivable: bool | None = False
        reason = "a full loss on this trade breaches a challenge limit"
    elif any(outcome is None for outcome in outcomes):
        survivable = None
        reason = "a limit could not be measured — survival cannot be claimed"
    else:
        survivable = True
        reason = None

    return LossProjection(
        available=True,
        reason=reason,
        risk_r=risk_r,
        loss_amount=loss,
        projected_value=projected,
        breaches_daily=results.get("daily"),
        breaches_total=results.get("total"),
        survivable=survivable,
    )


def check(
    rules: ChallengeRules,
    state: ChallengeState,
    proposed_risk_r: float | None = None,
) -> ChallengeVerdict:
    """Check the account against its rulebook before anything is executed.

    `proposed_risk_r` may be omitted to ask only "where does this account
    stand, and may it open anything at all right now?".
    """
    if state.starting_balance <= 0:
        return _refuse("starting balance is not positive — no limit can be expressed against it")

    future = [day for day in state.daily_profits if day > state.current_date]
    if future:
        return _refuse(
            f"the profit history holds {len(future)} day(s) after {state.current_date} — "
            "the state is not internally consistent"
        )

    breaches: list[str] = []
    warnings: list[str] = []
    unverified: list[str] = []
    # Reasons a new position may not be opened that are not, in themselves,
    # violations of anything. Being at the position cap breaks no rule; opening
    # one more would.
    gates: list[str] = []

    reference, basis_problem = _reference(rules, state)

    # The peak is by definition the maximum over the account's life, the
    # present included. A peak below current equity is a stale assembler, and
    # the staleness is not neutral — it lowers a trailing floor, which is the
    # one direction that quietly buys the account more rope.
    # Compared against `reference`, not against equity: under a balance basis
    # a caller who followed the docstring supplies a balance peak, and equity
    # floats above balance whenever a position is in profit. Overwriting the
    # peak with that figure declared healthy accounts dead.
    peak = state.peak_equity if reference is None else max(state.peak_equity, reference)
    if peak > state.peak_equity:
        unverified.append(
            "the supplied peak was below the current account value on the same "
            "basis - the higher figure was used"
        )

    anchor, anchor_note = _total_anchor(rules, state, peak)
    if anchor_note:
        unverified.append(anchor_note)

    allowance_base, base_note = _allowance_base(rules, state, reference)
    if base_note:
        unverified.append(base_note)

    # The daily anchor resets every session, so it is the day's opening figure
    # rather than the account's origin: measuring from the start would make
    # yesterday's losses count against today's allowance.
    daily_anchor, daily_anchor_problem = _daily_anchor(rules, state)

    daily = _headroom(
        "daily",
        pct=rules.max_daily_drawdown_pct,
        reference=reference,
        anchor=daily_anchor,
        allowance_base=allowance_base,
        unmeasurable=basis_problem or daily_anchor_problem,
    )
    total = _headroom(
        "total",
        pct=rules.max_total_drawdown_pct,
        reference=reference,
        anchor=anchor,
        allowance_base=allowance_base,
        unmeasurable=basis_problem,
    )

    for headroom in (daily, total):
        if headroom.breached and headroom.floor is not None and reference is not None:
            breaches.append(
                f"{headroom.limit} drawdown breached: {reference:.2f} is below the "
                f"{headroom.floor:.2f} floor"
            )
        elif headroom.available and headroom.consumed is not None:
            if headroom.consumed >= WARNING_THRESHOLD:
                warnings.append(
                    f"{headroom.consumed:.0%} of the {headroom.limit} drawdown allowance is spent"
                )
        elif headroom.imposed:
            unverified.append(f"{headroom.limit} drawdown not checked: {headroom.reason}")
            gates.append(f"{headroom.limit} drawdown could not be measured")

    # ------------------------------------------------------------- leverage
    # Resolved to the one figure that governs this trade before it is used.
    # A per-asset rulebook with no asset named resolves to its tightest cap
    # rather than refusing: the answer is knowable and conservative, and
    # blocking on it would stop every trade on a rulebook that is complete.
    cap: float | None = None
    if rules.max_leverage is None:
        unverified.append(
            "the leverage cap was never entered, so it was not checked"
        )
    elif isinstance(rules.max_leverage, LeverageCaps):
        cap = rules.max_leverage.binding(state.asset_class)
        if state.asset_class is None:
            warnings.append(
                f"no asset class was named, so the tightest published leverage "
                f"cap ({cap:.2f}x) was applied rather than the one for the "
                "instrument actually traded"
            )
    elif isinstance(rules.max_leverage, float | int):
        cap = float(rules.max_leverage)

    if cap is not None:
        if state.current_leverage is None:
            unverified.append("leverage rule not checked: no leverage in the account state")
            gates.append("leverage could not be measured")
        elif state.current_leverage > cap:
            breaches.append(
                f"leverage {state.current_leverage:.2f}x is above the "
                f"{cap:.2f}x cap"
            )
        else:
            if state.current_leverage >= cap:
                gates.append(f"leverage is at the {cap:.2f}x cap")
            elif state.current_leverage >= cap * LEVERAGE_WARNING_SHARE:
                warnings.append(
                    f"leverage {state.current_leverage:.2f}x is near the "
                    f"{cap:.2f}x cap"
                )

    # ------------------------------------------------------------ positions
    if rules.max_concurrent_positions is None:
        unverified.append(
            "the concurrent-position cap was never entered, so it was not checked"
        )
    elif isinstance(rules.max_concurrent_positions, int):
        if state.open_positions > rules.max_concurrent_positions:
            breaches.append(
                f"{state.open_positions} open positions exceeds the "
                f"{rules.max_concurrent_positions} permitted"
            )
        elif state.open_positions >= rules.max_concurrent_positions:
            gates.append(f"{state.open_positions} open positions is the concurrent cap")

    # ----------------------------------------------------- automated trading
    #
    # The only rule here that can rule this platform out of an account
    # entirely, and the only one that does not reduce.
    #
    # Every other unverified rule lowers what is permitted, because a smaller
    # position is a safe answer to "we could not check the limit". There is no
    # smaller position that satisfies "software may not choose the trade" -
    # either it chose it or it did not - so an unread rule stops here rather
    # than shrinking. That inverts this module's usual treatment of the
    # unknown, and it inverts it deliberately: the cost of being wrong is the
    # account, not a drawdown.
    #
    # Providers draw the line in different places. Several permit
    # money-management and copy-trading experts while forbidding automated
    # decision-making, which is exactly what this system is - so "we use an
    # expert" is not the question, and "our software picked the trade" is.
    if rules.automated_trading_allowed is None:
        # Gated, and this is the second time the decision has moved - so the
        # argument on both sides is kept rather than replaced.
        #
        # It was gated, then changed to reported-only on the reasoning that
        # every other unread rule here is reported, and that gating this one
        # would refuse ten of the fourteen catalogued rulebooks over a field
        # nobody had filled in yet. Both halves of that were true.
        #
        # It gates again because the consistency argument does not survive
        # what this rule actually asks. Every other rule here answers "how
        # much may be risked", and an unknown one can be honoured by risking
        # less. This one asks whether software may choose the trades at all,
        # and there is no smaller version of yes. If a provider forbids it,
        # the account is closed for the first automated order, and no position
        # size prevents that - so the direction that costs least when wrong is
        # to stop.
        #
        # Refusing ten of fourteen is the correct reading of ten unconfirmed
        # rulebooks, not a cost of the gate. It became visible rather than
        # theoretical when the gate started supplying an R value: before that
        # an unsizeable risk was blocking these accounts anyway, and this
        # rule's state changed nothing on screen.
        unverified.append(
            "the rulebook does not say whether this provider permits automated "
            "trading, and this platform chooses its own trades - so the "
            "permission has to be confirmed against the account's own contract"
        )
        gates.append(
            "the automation permission is unread, and it is the one rule that "
            "cannot be answered by trading smaller"
        )
    elif isinstance(rules.automated_trading_allowed, NotImposed):
        pass
    elif rules.automated_trading_allowed is False:
        # A breach rather than a gate, because unlike every other restriction
        # here the state it depends on is never in doubt: this platform always
        # chooses its own trades. There is no window to wait out and no size
        # to reduce to.
        breaches.append(
            "this provider forbids automated trading experts, and every order "
            "this platform sends is chosen by software"
        )

    # ----------------------------------------------------------------- news
    # A news window is a gate on the next trade, never a verdict on the last
    # one: this module runs before execution, so it has nothing to say about a
    # position that was already open when the window started.
    if rules.news_trading_allowed is None:
        unverified.append(
            "the rulebook does not say whether this provider restricts news "
            "trading - the restriction was not checked"
        )
    elif isinstance(rules.news_trading_allowed, NotImposed):
        pass
    elif rules.news_trading_allowed is False:
        if state.in_news_window is None:
            unverified.append("news restriction not checked: news-window state unknown")
            gates.append("news-window state unknown")
        elif state.in_news_window:
            gates.append("inside a restricted news window")

    # -------------------------------------------------------------- weekend
    if rules.weekend_holding_allowed is None:
        unverified.append(
            "the rulebook does not say whether this provider restricts weekend "
            "holding - the restriction was not checked"
        )
    elif isinstance(rules.weekend_holding_allowed, NotImposed):
        pass
    elif rules.weekend_holding_allowed is False:
        if state.weekend_ahead is None:
            unverified.append("weekend restriction not checked: weekend proximity unknown")
            gates.append("weekend proximity unknown")
        elif state.weekend_ahead:
            gates.append("weekend holding is not permitted and the break is next")
            if state.open_positions > 0:
                warnings.append(
                    f"{state.open_positions} open position(s) must be closed before the "
                    "weekend break"
                )

    # ------------------------------------------------------------ day counts
    days_short = 0
    if rules.min_trading_days is None:
        unverified.append("the minimum trading days were never entered, so they were not checked")
    elif isinstance(rules.min_trading_days, int) and state.days_traded < rules.min_trading_days:
        days_short = rules.min_trading_days - state.days_traded
    if rules.max_trading_days is None:
        unverified.append("the maximum trading days were never entered, so they were not checked")
    elif isinstance(rules.max_trading_days, int):
        if state.days_traded > rules.max_trading_days:
            breaches.append(
                f"{state.days_traded} trading days used, beyond the "
                f"{rules.max_trading_days} permitted"
            )
        elif state.days_traded >= rules.max_trading_days:
            warnings.append("this is the last permitted trading day")

    # --------------------------------------------------------- profit target
    target_met: bool | None = None
    if isinstance(rules.profit_target_pct, float | int):
        target_value = _money(state.starting_balance * (1.0 + rules.profit_target_pct))
        if state.current_balance is None:
            # Floating profit is not profit until the position closes, and no
            # provider pays out on it. Reading the target off equity would
            # declare a challenge passed on money the account does not have.
            unverified.append(
                "profit target not checked: it is reached on closed profit and no balance "
                "was supplied"
            )
        else:
            target_met = _money(state.current_balance) >= target_value
            if target_met:
                warnings.append("profit target is met — further risk can only lose it")

    consistency = evaluate_consistency(rules.max_single_day_profit_share, state.daily_profits)
    consistency_ok: bool | None = None
    if rules.max_single_day_profit_share is None:
        # Named, like every other unentered rule in this function. Until now
        # the whole block below was gated on the rule being a number, so
        # `evaluate_consistency` composed "the consistency rule was never
        # entered" and the caller threw it away - the one unknown here that
        # was silently skipped, which is the exact shape of failure this
        # module exists to prevent. `NOT_IMPOSED` still says nothing, because
        # a stated absence is an answer.
        unverified.append(f"consistency rule not judged: {consistency.reason}")
    elif isinstance(rules.max_single_day_profit_share, float | int):
        if consistency.available:
            consistency_ok = consistency.within_limit
            if consistency_ok is False and consistency.best_day_share is not None:
                warnings.append(
                    f"consistency: the best day is {consistency.best_day_share:.0%} of total "
                    f"profit, above the {rules.max_single_day_profit_share:.0%} ceiling"
                )
        else:
            unverified.append(f"consistency rule not judged: {consistency.reason}")

    # --------------------------------------------------------------- status
    if breaches:
        status = "failed"
    else:
        status = "in_progress"
        if target_met:
            outstanding: list[str] = []
            if days_short:
                outstanding.append(f"{days_short} more trading day(s) required")
            # `is not None` here read NOT_IMPOSED as an imposed rule, so a
            # provider with no consistency requirement kept an account at
            # in_progress after it had met the target.
            if (
                isinstance(rules.max_single_day_profit_share, float | int)
                and consistency_ok is not True
            ):
                outstanding.append("the consistency rule is not satisfied")
            if outstanding:
                warnings.append(
                    "profit target met but the challenge is not passed: " + "; ".join(outstanding)
                )
            else:
                status = "passed"

    # ------------------------------------------------------------ projection
    projection = project_full_loss(
        risk_r=proposed_risk_r,
        reference=reference,
        currency_per_r=state.currency_per_r,
        daily=daily,
        total=total,
    )
    if projection.survivable is False:
        warnings.append("losing this trade in full would breach a challenge limit")

    allowed = not breaches and not gates
    imposed_limits = [h for h in (daily, total) if h.imposed]

    max_additional: float | None = None
    # True only when no imposed limit produced a cap, i.e. the provider really
    # caps nothing. An imposed limit whose cap could not be computed is the
    # opposite situation and must not share the answer.
    cap_measurable = True
    amounts = [h.amount for h in imposed_limits if h.amount is not None]
    unmeasured_limits = [h for h in imposed_limits if h.amount is None]
    unpriced_r = state.currency_per_r is None or state.currency_per_r <= 0
    if unmeasured_limits or (amounts and unpriced_r):
        cap_measurable = False
        unverified.append(
            "new risk cannot be sized against the drawdown limits: one R is not "
            "expressed in account currency"
            if amounts
            else "an imposed drawdown limit could not be measured, so no cap follows from it"
        )
    elif amounts and state.currency_per_r:
        max_additional = (min(amounts) * SLIPPAGE_BUFFER) / state.currency_per_r

    if not allowed:
        # Nothing may be opened, so the largest openable risk is a measured
        # zero rather than an unknown.
        return ChallengeVerdict(
            status=status,
            allowed=False,
            verdict="block",
            max_additional_risk_r=0.0,
            risk_cap_measurable=cap_measurable,
            daily=daily,
            total=total,
            consistency=consistency,
            projection=projection,
            breaches=breaches,
            warnings=warnings,
            unverified=unverified,
            gates=gates,
        )

    if not cap_measurable:
        # The standing question - "may anything be opened right now?" - has no
        # safe answer when an imposed limit could not be turned into a size.
        # Approving here handed a downstream sizer the same reply it gets from
        # an account with no rules at all.
        allowed = False
        verdict = "block"
    elif proposed_risk_r is None:
        verdict = "approve"
    elif proposed_risk_r <= 0:
        allowed = False
        verdict = "block"
        unverified.append("proposed risk must be positive")
    elif projection.survivable is None:
        # The projection is the only check that can clear a trade before it
        # exists, and it could not be computed. A trade nothing cleared is not
        # a trade that may be taken.
        allowed = False
        verdict = "block"
    elif projection.survivable is False:
        # A full loss at this size ends the challenge. A smaller one may not,
        # and "reduce to 0.4 R" is a more useful answer downstream than "no".
        if max_additional is not None and max_additional > 0:
            verdict = "reduce"
        else:
            allowed = False
            verdict = "block"
    elif max_additional is None:
        verdict = "approve"
    elif max_additional <= 0:
        allowed = False
        verdict = "block"
    elif max_additional < proposed_risk_r:
        verdict = "reduce"
    else:
        verdict = "approve"

    return ChallengeVerdict(
        status=status,
        allowed=allowed,
        verdict=verdict,
        max_additional_risk_r=0.0 if not allowed else max_additional,
        risk_cap_measurable=cap_measurable,
        daily=daily,
        total=total,
        consistency=consistency,
        projection=projection,
        breaches=breaches,
        warnings=warnings,
        unverified=unverified,
        gates=gates,
    )
