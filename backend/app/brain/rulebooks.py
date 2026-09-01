"""Real prop-firm rulebooks, transcribed from the provider's published page.

Until this file existed, `challenge.py` was exercised against a rulebook whose
own response called it "a conventional two-phase example, not a provider's
verified rules". Every headroom figure it produced was arithmetic about numbers
nobody had checked - correct arithmetic, and worthless.

Three things are recorded beside every rulebook, and they matter as much as the
numbers:

`source` is the page the figures came from. A rule with no source cannot be
re-checked, and a prop firm's terms are not the kind of thing to remember
wrongly.

`retrieved` is when it was read. Providers change their terms, and a rulebook
with no date silently ages into a different firm's rules.

`confirmed_by_holder` is False on every entry here, and only the person who
signed up can flip it. What is published on a marketing page and what is on
one account's contract are not guaranteed to be the same document.

Rules the page does not state are left `None` - unknown - rather than assumed
absent. Where the provider claims the list is exhaustive ("Every rule, every
condition, published before you start"), an unlisted rule is recorded as
NOT_IMPOSED and the docstring says which claim that rests on, so a later reader
can disagree with the inference instead of inheriting it invisibly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from app.brain.challenge import (
    NOT_IMPOSED,
    AllowanceBasis,
    ChallengeRules,
    DrawdownBasis,
    LeverageCaps,
)
from app.core.enums import AssetClass

#: When the FundedNext pages below were read.
FUNDEDNEXT_RETRIEVED = date(2026, 8, 30)
FUNDEDNEXT_SOURCE = "https://fundednext.com/general-rules"


@dataclass(frozen=True)
class Rulebook:
    """One provider program, with the provenance of its numbers."""

    key: str
    provider: str
    program: str
    phase: str
    rules: ChallengeRules
    source: str
    retrieved: date
    #: True only once the account holder has checked these against their own
    #: contract. Nothing in this file may set it.
    confirmed_by_holder: bool = False
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "provider": self.provider,
            "program": self.program,
            "phase": self.phase,
            "source": self.source,
            "retrieved": self.retrieved.isoformat(),
            "confirmed_by_holder": self.confirmed_by_holder,
            "profit_target_pct": _publish(self.rules.profit_target_pct),
            "max_daily_drawdown_pct": _publish(self.rules.max_daily_drawdown_pct),
            "max_total_drawdown_pct": _publish(self.rules.max_total_drawdown_pct),
            "total_drawdown_trailing": self.rules.total_drawdown_trailing,
            "min_trading_days": _publish(self.rules.min_trading_days),
            "max_trading_days": _publish(self.rules.max_trading_days),
            "allowance_basis": self.rules.allowance_basis.value
            if self.rules.allowance_basis
            else None,
            "notes": list(self.notes),
        }


def _publish(value: Any) -> Any:
    """Render a rule for a caller, keeping the three states apart.

    `None` and NOT_IMPOSED both look empty in JSON, and they are opposite
    facts, so the marker becomes a word.
    """
    if value is NOT_IMPOSED or isinstance(value, type(NOT_IMPOSED)):
        return "not imposed"
    return value


# Common to every Stellar program below, and each is a transcription rather
# than a default:
#
#   The daily limit is "a cap on how much you can lose in a single day.
#   Includes realized and unrealized P&L, swap, and commission" - unrealized
#   P&L is what makes it an equity rule rather than a balance one, so a
#   floating loss counts against it the moment it exists.
#
#   Both limits are "a percentage of the initial balance", not of current
#   equity, which is why the allowance basis is the starting balance. Reading
#   it as a share of current equity shrinks the allowance exactly when an
#   account is down and needs it measured correctly.
#
#   "Static means the loss limit is set from your starting balance and remains
#   unchanged throughout" - so the total floor does not trail for any Stellar
#   program except Instant, which the page marks Trailing.
#
#   News trading is "allowed, with no restrictions on when or how you trade",
#   and the 40% news profit split explicitly excludes the challenge phases.
#
#   The consistency inference above was WRONG, and was withdrawn on 30 Aug.
#   It read NOT_IMPOSED out of the Trading Objectives page's claim to list
#   "every rule, every condition". A 40% consistency rule does exist - best
#   day's profit no more than 40% of total - it simply lives in the help
#   centre rather than that page, attached to reward eligibility on the
#   FundedNext account. Whether it binds a Stellar *challenge* phase is not
#   stated either way, so the field is now `None` and blocks.
#
#   The lesson is about direction. Every other unknown in this file blocks;
#   a NOT_IMPOSED asserts a rule's absence and therefore permits, so it is
#   the one value an inference must never produce. Only a sentence that says
#   the rule does not exist can write it - Instant has such a sentence and
#   keeps NOT_IMPOSED; the challenge phases never did.
#
#   Three facts were published between 13 and 30 Aug that were absent before,
#   and are now read rather than inferred:
#     - weekend holding: "allowed across every CFDs account, at every stage"
#     - position cap: "Challenge / FundedNext: no hard cap, no fixed limit"
#       (help centre, "What is the maximum lot size in FundedNext?", 24 Feb
#       2026). The 5-position cap on the same page is the monthly competition
#       and binds nothing here.
#     - leverage: now published, but per asset class - see `max_leverage`.

# Leverage as the Symbols & Conditions tab publishes it, read 30 Aug 2026.
# Gold, silver and oil are filed under "Commodities" by that page, so METAL
# takes the commodity cap rather than one of its own - the enum splits them
# and the provider does not.
#
# These are the challenge-phase figures. The funded phase tightens indices
# and commodities on both programmes, and there is no funded FundedNext
# rulebook here to hold that; Instant is funded from day one and has its own.
_CRYPTO_ONE_TO_ONE = {AssetClass.CRYPTO: 1.0}

_LEVERAGE_1STEP = LeverageCaps(
    {
        AssetClass.FOREX: 30.0,
        AssetClass.INDEX: 10.0,
        AssetClass.COMMODITY: 15.0,
        AssetClass.METAL: 15.0,
        **_CRYPTO_ONE_TO_ONE,
    }
)

_LEVERAGE_2STEP_AND_LITE = LeverageCaps(
    {
        AssetClass.FOREX: 100.0,
        AssetClass.INDEX: 25.0,
        AssetClass.COMMODITY: 25.0,
        AssetClass.METAL: 25.0,
        **_CRYPTO_ONE_TO_ONE,
    }
)

_LEVERAGE_INSTANT = LeverageCaps(
    {
        AssetClass.FOREX: 30.0,
        AssetClass.INDEX: 5.0,
        AssetClass.COMMODITY: 7.5,
        AssetClass.METAL: 7.5,
        **_CRYPTO_ONE_TO_ONE,
    }
)

_COMMON: dict[str, Any] = {
    # Left unread on purpose, which is not the same as an omission.
    #
    # The page permits Expert Advisors on every model *subject to a paid
    # add-on bought per account*. That is neither a permission nor a
    # prohibition for any particular account, and there is no value here for
    # "conditional" - so it stays `None`, the gate reports the permission as
    # unread, and the holder confirms it for the account they actually bought.
    # Writing `True` would assert an add-on nobody has evidence of.
    "automated_trading_allowed": None,
    "drawdown_basis": DrawdownBasis.EQUITY,
    "allowance_basis": AllowanceBasis.STARTING_BALANCE,
    "total_drawdown_trailing": False,
    "max_trading_days": NOT_IMPOSED,       # "No deadline to pass the Challenge."
    # Was NOT_IMPOSED by inference until 30 Aug; the 40% consistency rule is
    # real and the inference was withdrawn. Unknown for a challenge phase, so
    # it blocks. Instant overrides this - its own page says it has none.
    "max_single_day_profit_share": None,
    "news_trading_allowed": True,
    # "Overnight and weekend holding are allowed across every CFDs account,
    # at every stage." Swap applies; triple swap Wednesday on forex and
    # commodities, Friday on indices and crypto.
    "weekend_holding_allowed": True,
    # `max_leverage` is not here: it is the one rule that differs by programme
    # as well as by asset class, so each book names its own `LeverageCaps`
    # above. It was `None` until 30 Aug for want of a type that could hold
    # "forex 1:100 and crypto 1:1 on the same account".
    # "Challenge / FundedNext: no hard cap, no fixed limit." Stated, not
    # inferred - which is what separates this NOT_IMPOSED from the consistency
    # one that had to be withdrawn.
    "max_concurrent_positions": NOT_IMPOSED,
}

_INACTIVITY = (
    "60-day inactivity rule: an account with no trade for 60 consecutive days "
    "is deactivated, and the window cannot be extended"
)
_MARGIN = (
    "cumulative margin usage of 70% or more is listed under gambling behaviour, "
    "which is enforced by review rather than by an automatic breach"
)
_AUTOMATION = (
    "Expert Advisors and VPS are allowed on every model but each needs its own "
    "paid add-on, and only on MT4/MT5 - automated trading without the add-on "
    "is a rule breach, not a technical limitation"
)
_CLOSED_ONLY = "the profit target is calculated on closed trades only"


#: When the FTMO page below was read.
FTMO_RETRIEVED = date(2026, 8, 14)
FTMO_SOURCE = "https://ftmo.com/en/trading-objectives/"

# FTMO differs from FundedNext in the one place it matters most, and the
# difference is the whole account once it is in profit:
#
#   "The Maximum Loss rule establishes an end-of-day trailing limit". The floor
#   is recalculated daily at 00:00 CE(S)T from "the highest account balance
#   achieved at 00:00 CE(S)T of any preceding trading day or, if higher, the
#   amount of Initial Simulated Capital", less 10% of Initial Simulated
#   Capital. FundedNext's Stellar floor is static. Reading FTMO's as static
#   would report headroom the account does not have the moment it is up.
#
#   "The limit can only increase" - it never falls back after a losing day.
#
#   Both limits are watched on equity: "Balance + Open Positions P/L +/- Swaps
#   - Commissions". A floating loss counts the moment it exists.
#
#   The daily limit is recalculated at 00:00 CE(S)T from "the account balance
#   recorded at 00:00 CE(S)T of the current day" less 3% of Initial Simulated
#   Capital - so the amount is a share of the starting capital while the anchor
#   is that day's opening balance. On the first day the anchor is the Initial
#   Simulated Capital.
#
#   The profit target is met "once your account balance exceeds the Initial
#   Simulated Capital by the required Profit Target with all positions closed"
#   - closed trades only, the same as FundedNext.
#
#   Minimum 4 trading days, "measured from 00:00:00 to 23:59:59 CE(S)T - during
#   which at least one position is opened", and it "applies to both phases".
#
#   "No time limit" on the challenge, so there is no deadline to pass.

_FTMO_COMMON: dict[str, Any] = {
    # Not stated on this page, like the four fields below it. Inferring
    # permission from silence is how a rulebook acquires a rule its provider
    # never wrote - and this is the one rule where the wrong inference costs
    # the account rather than a position size.
    "automated_trading_allowed": None,
    "drawdown_basis": DrawdownBasis.EQUITY,
    "allowance_basis": AllowanceBasis.STARTING_BALANCE,
    "total_drawdown_trailing": True,
    "max_trading_days": NOT_IMPOSED,       # "No time limit"
    "max_single_day_profit_share": None,   # not stated on this page
    "news_trading_allowed": None,          # not stated on this page
    "weekend_holding_allowed": None,       # not stated on this page
    "max_leverage": None,                  # varies by account type, not here
    "max_concurrent_positions": None,      # not stated
}

_FTMO_TRAIL = (
    "the maximum loss floor trails the highest balance recorded at 00:00 CE(S)T "
    "of any preceding day, not the live equity peak - an intraday spike does "
    "not raise it, and it only ever increases"
)
_FTMO_DAILY = (
    "the daily floor is that day's 00:00 CE(S)T balance less 3% of the initial "
    "capital, so the amount is a share of the starting capital while the anchor "
    "moves with each day's opening balance"
)
_FTMO_EQUITY = (
    "both limits are watched on equity - balance plus open P/L, swaps and "
    "commissions - so a floating loss counts against them before it is realised"
)
_FTMO_DAYS = (
    "a trading day is any day from 00:00:00 to 23:59:59 CE(S)T in which at "
    "least one position is opened, and the 4-day minimum applies to both phases"
)


RULEBOOKS: tuple[Rulebook, ...] = (
    Rulebook(
        key="ftmo-challenge-2step-phase1",
        provider="FTMO",
        program="FTMO Challenge 2-Step",
        phase="phase 1 (FTMO Challenge)",
        rules=ChallengeRules(
            profit_target_pct=0.10,
            max_daily_drawdown_pct=0.03,
            max_total_drawdown_pct=0.10,
            min_trading_days=4,
            **_FTMO_COMMON,
        ),
        source=FTMO_SOURCE,
        retrieved=FTMO_RETRIEVED,
        notes=(_CLOSED_ONLY, _FTMO_TRAIL, _FTMO_DAILY, _FTMO_EQUITY, _FTMO_DAYS),
    ),
    Rulebook(
        key="ftmo-challenge-2step-phase2",
        provider="FTMO",
        program="FTMO Challenge 2-Step",
        phase="phase 2 (Verification)",
        rules=ChallengeRules(
            profit_target_pct=0.05,
            max_daily_drawdown_pct=0.03,
            max_total_drawdown_pct=0.10,
            min_trading_days=4,
            **_FTMO_COMMON,
        ),
        source=FTMO_SOURCE,
        retrieved=FTMO_RETRIEVED,
        notes=(_CLOSED_ONLY, _FTMO_TRAIL, _FTMO_DAILY, _FTMO_EQUITY, _FTMO_DAYS),
    ),
    Rulebook(
        key="ftmo-challenge-1step",
        provider="FTMO",
        program="FTMO Challenge 1-Step",
        phase="single phase",
        rules=ChallengeRules(
            profit_target_pct=0.10,
            max_daily_drawdown_pct=0.03,
            max_total_drawdown_pct=0.10,
            min_trading_days=4,
            **_FTMO_COMMON,
        ),
        source=FTMO_SOURCE,
        retrieved=FTMO_RETRIEVED,
        notes=(_CLOSED_ONLY, _FTMO_TRAIL, _FTMO_DAILY, _FTMO_EQUITY, _FTMO_DAYS),
    ),
    Rulebook(
        key="ftmo-account-2step",
        provider="FTMO",
        program="FTMO Account (2-Step)",
        phase="funded",
        rules=ChallengeRules(
            # "There is no Profit Target on the subsequent FTMO Account
            # (2-Step)" - stated absence, not an unknown.
            profit_target_pct=NOT_IMPOSED,
            max_daily_drawdown_pct=0.03,
            max_total_drawdown_pct=0.10,
            min_trading_days=NOT_IMPOSED,
            **_FTMO_COMMON,
        ),
        source=FTMO_SOURCE,
        retrieved=FTMO_RETRIEVED,
        notes=(_FTMO_TRAIL, _FTMO_DAILY, _FTMO_EQUITY),
    ),
    Rulebook(
        key="fundednext-stellar-1step",
        provider="FundedNext",
        program="Stellar 1-Step",
        phase="single phase",
        rules=ChallengeRules(
            profit_target_pct=0.10,
            max_daily_drawdown_pct=0.03,
            max_total_drawdown_pct=0.06,
            min_trading_days=2,
            **_COMMON,
            max_leverage=_LEVERAGE_1STEP,
        ),
        source=FUNDEDNEXT_SOURCE,
        retrieved=FUNDEDNEXT_RETRIEVED,
        notes=(_CLOSED_ONLY, "maximum loss is static", _INACTIVITY, _MARGIN, _AUTOMATION),
    ),
    Rulebook(
        key="fundednext-stellar-2step-phase1",
        provider="FundedNext",
        program="Stellar 2-Step",
        phase="phase 1",
        rules=ChallengeRules(
            profit_target_pct=0.08,
            max_daily_drawdown_pct=0.05,
            max_total_drawdown_pct=0.10,
            min_trading_days=5,
            **_COMMON,
            max_leverage=_LEVERAGE_2STEP_AND_LITE,
        ),
        source=FUNDEDNEXT_SOURCE,
        retrieved=FUNDEDNEXT_RETRIEVED,
        notes=(_CLOSED_ONLY, "maximum loss is static", _INACTIVITY, _MARGIN, _AUTOMATION),
    ),
    Rulebook(
        key="fundednext-stellar-2step-phase2",
        provider="FundedNext",
        program="Stellar 2-Step",
        phase="phase 2",
        rules=ChallengeRules(
            profit_target_pct=0.05,
            max_daily_drawdown_pct=0.05,
            max_total_drawdown_pct=0.10,
            min_trading_days=5,
            **_COMMON,
            max_leverage=_LEVERAGE_2STEP_AND_LITE,
        ),
        source=FUNDEDNEXT_SOURCE,
        retrieved=FUNDEDNEXT_RETRIEVED,
        notes=(_CLOSED_ONLY, "maximum loss is static", _INACTIVITY, _MARGIN, _AUTOMATION),
    ),
    Rulebook(
        key="fundednext-stellar-lite-phase1",
        provider="FundedNext",
        program="Stellar Lite",
        phase="phase 1",
        rules=ChallengeRules(
            profit_target_pct=0.08,
            max_daily_drawdown_pct=0.04,
            max_total_drawdown_pct=0.08,
            min_trading_days=5,
            **_COMMON,
            max_leverage=_LEVERAGE_2STEP_AND_LITE,
        ),
        source=FUNDEDNEXT_SOURCE,
        retrieved=FUNDEDNEXT_RETRIEVED,
        notes=(_CLOSED_ONLY, "maximum loss is static", _INACTIVITY, _MARGIN, _AUTOMATION),
    ),
    Rulebook(
        key="fundednext-stellar-lite-phase2",
        provider="FundedNext",
        program="Stellar Lite",
        phase="phase 2",
        rules=ChallengeRules(
            profit_target_pct=0.04,
            max_daily_drawdown_pct=0.04,
            max_total_drawdown_pct=0.08,
            min_trading_days=5,
            **_COMMON,
            max_leverage=_LEVERAGE_2STEP_AND_LITE,
        ),
        source=FUNDEDNEXT_SOURCE,
        retrieved=FUNDEDNEXT_RETRIEVED,
        notes=(_CLOSED_ONLY, "maximum loss is static", _INACTIVITY, _MARGIN, _AUTOMATION),
    ),
    Rulebook(
        key="fundednext-free-trial",
        provider="FundedNext",
        program="Free Trial",
        phase="trial",
        rules=ChallengeRules(
            # Transcribed from the account's own Trading Objectives panel on
            # 1 Sep 2026, for account 34838666 at $15,000: "Profit target
            # $750", "Min trading days 3 Days", "Daily loss limit (-5%) $750",
            # "Max loss limit (-10%) $1,500". Read as percentages of the
            # starting balance, which is how the panel labels the two limits.
            #
            # The general-rules page carries no Free Trial column - it lists
            # the paid Stellar programs, whose 2-Step phase 1 asks 8% over 5
            # days. Copying those numbers here would have set a target half
            # again too high and a day count that fails this account for being
            # too quick. So the account's own page is the source, and it is a
            # first-party, dated reading rather than an inference from a
            # neighbouring product.
            profit_target_pct=0.05,
            max_daily_drawdown_pct=0.05,
            max_total_drawdown_pct=0.10,
            min_trading_days=3,
            **_COMMON,
            max_leverage=_LEVERAGE_2STEP_AND_LITE,
        ),
        source="https://app.fundednext.com/accounts (account 34838666 overview)",
        retrieved=date(2026, 9, 1),
        notes=(
            _CLOSED_ONLY,
            "maximum loss is static",
            _INACTIVITY,
            _MARGIN,
            _AUTOMATION,
            "the trial's objectives are read from the account page rather "
            "than the general-rules table, which has no Free Trial column",
            # Read 1 Sep 2026 from the help centre's EA article, and it is
            # why this account cannot be traded automatically at all: "For
            # any kind of Free or BOGO accounts, 'EA' and 'VPS & EA' add-ons
            # will not be included by default; however, a trader can choose
            # to add them by paying the additional usage fee, after which the
            # selected add-on will be activated on the account."
            #
            # So the server answers every automated order with retcode 10026
            # - not a misconfiguration on this side and not something support
            # can switch on, but a paid add-on this account does not carry.
            # Twenty-five orders across thirteen symbols were refused that
            # way before the sentence was found.
            "automated trading needs a paid EA add-on that a Free Trial "
            "account does not include, so the server refuses every EA order",
            # The same article, and it is a live risk for this deployment
            # rather than a note: "Using EA that incorporates third-party
            # applications such as Telegram or WhatsApp is strictly
            # prohibited." This platform has a Telegram channel. It is
            # read-only by construction - nothing arriving from a chat can
            # reach the order path, and a test pins that - but the rule is
            # written broadly and the firm judges it, not us.
            "this firm prohibits EAs that incorporate Telegram or WhatsApp; "
            "the chat channel here is read-only, but the rule is theirs to "
            "read",
            # The VPS article, 8 Apr 2026, and it applies to this deployment
            # by construction: the terminal runs on a server rather than on
            # the holder's own machine, which is what a VPS is. "Traders are
            # allowed to use a VPS in both the Challenge and FundedNext
            # accounts, with an additional usage fee... VPS usage fee is
            # applicable for all packages", and the same Free/BOGO sentence
            # excludes the add-on from this account.
            #
            # Two of its clauses are worth carrying beside the fee, because
            # they are about the shape of this system rather than its cost:
            # a VPS may not be shared, and it may not be used for "Account
            # Management" or "Group Trading" - so one host driving several
            # of this firm's accounts is a question to settle in writing
            # before it ever does.
            "running the terminal on a server is VPS use by this firm's "
            "definition: a paid add-on, excluded from Free accounts, and "
            "not to be shared across accounts",
        ),
    ),
    Rulebook(
        key="fundednext-stellar-instant",
        provider="FundedNext",
        program="Stellar Instant",
        phase="funded from day one",
        rules=ChallengeRules(
            profit_target_pct=NOT_IMPOSED,
            max_daily_drawdown_pct=NOT_IMPOSED,
            max_total_drawdown_pct=0.06,
            min_trading_days=NOT_IMPOSED,
            **{
                **_COMMON,
                "max_leverage": _LEVERAGE_INSTANT,
                "total_drawdown_trailing": True,
                # "The Stellar Instant Account has no consistency rules." A
                # sentence that states the absence, so this one may assert it
                # where the challenge phases may not.
                "max_single_day_profit_share": NOT_IMPOSED,
            },
        ),
        source=FUNDEDNEXT_SOURCE,
        retrieved=FUNDEDNEXT_RETRIEVED,
        notes=(
            "the only Stellar program with a trailing floor: the limit rises "
            "with profit, never falls with loss, and stops at the initial balance",
            "no profit target and no daily loss limit - the total floor is the "
            "whole rulebook, which makes it the strictest rather than the loosest",
            "the 40% news profit split applies here, unlike the challenge phases",
            _INACTIVITY,
            _MARGIN,
            _AUTOMATION,
        ),
    ),
)

BY_KEY: dict[str, Rulebook] = {book.key: book for book in RULEBOOKS}


def get(key: str) -> Rulebook | None:
    return BY_KEY.get(key)


def providers() -> list[str]:
    return sorted({book.provider for book in RULEBOOKS})
