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
absent. NOT_IMPOSED is written only where a sentence on the page states the
rule's absence, and the comment beside it quotes that sentence, so a later
reader can disagree with the reading instead of inheriting it invisibly.

The FundedNext rulebooks that used to live here were removed on 13 Sep 2026
when the last account on that firm was switched off; the holder rehearses on
rulebooks of their own now (`app.services.custom_rulebooks`). The engine
rules they exercised - the per-asset leverage cap, the automation ceiling by
account size - stay in `challenge.py`, because a written rulebook may set
them too.
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
)


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


_CLOSED_ONLY = "the profit target is calculated on closed trades only"


#: When the FTMO page below was read.
FTMO_RETRIEVED = date(2026, 8, 14)
FTMO_SOURCE = "https://ftmo.com/en/trading-objectives/"

#: Where the five rules below the objectives were read, and when.
#:
#: The objectives page states the profit target, the two drawdowns and the
#: minimum trading days, and it is silent on everything else - which is why
#: `automated_trading_allowed`, weekend holding, news and the position cap
#: were `None` here for three weeks. They are not unpublished; they are on
#: other pages of the same site, and nobody had gone and read them.
FTMO_FAQ_RETRIEVED = date(2026, 9, 8)
FTMO_FAQ_STRATEGY = (
    "https://ftmo.com/en/faq/"
    "which-instruments-can-i-trade-and-what-strategies-am-i-allowed-to-use/"
)
FTMO_FAQ_NEWS = "https://ftmo.com/en/faq/can-i-trade-news/"
FTMO_FAQ_HOLDING = (
    "https://ftmo.com/en/faq/"
    "do-i-have-to-close-my-positions-overnight-or-before-the-weekend/"
)

# FTMO's floor trails, and against a static floor the difference is the
# whole account once it is in profit:
#
#   "The Maximum Loss rule establishes an end-of-day trailing limit". The floor
#   is recalculated daily at 00:00 CE(S)T from "the highest account balance
#   achieved at 00:00 CE(S)T of any preceding trading day or, if higher, the
#   amount of Initial Simulated Capital", less 10% of Initial Simulated
#   Capital. Reading it as static would report headroom the account does
#   not have the moment it is up.
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
#   - closed trades only.
#
#   Minimum 4 trading days, "measured from 00:00:00 to 23:59:59 CE(S)T - during
#   which at least one position is opened", and it "applies to both phases".
#
#   "No time limit" on the challenge, so there is no deadline to pass.

_FTMO_COMMON: dict[str, Any] = {
    # Read 8 Sep 2026 from FTMO_FAQ_STRATEGY, and it is a permission stated
    # rather than one inferred from silence: "we have no reasons for limiting
    # or restricting your trading strategy, whether it\'s discretionary
    # trading, algorithmic trading, EAs, etc."
    #
    # This field had been `None` since the file was written, and `None` here
    # is the one value that is not a shrug - it means nobody read the
    # document, and the account is the thing at stake rather than a position
    # size. It was answerable the whole time on a page nobody had opened.
    "automated_trading_allowed": True,
    "drawdown_basis": DrawdownBasis.EQUITY,
    "allowance_basis": AllowanceBasis.STARTING_BALANCE,
    "total_drawdown_trailing": True,
    "max_trading_days": NOT_IMPOSED,       # "No time limit"
    # The same page, and it is a platform limit rather than a strategy rule:
    # "platform servers have 200 orders at a time and 2000 max positions per
    # day limitation". The per-day figure has nowhere to live in this model,
    # so it is written into the notes instead of rounded into this one.
    "max_concurrent_positions": 200,
    # Still unread, and still deliberately so.
    #
    # FTMO does not publish leverage on the objectives page, the symbols
    # page, the how-it-works page, or the FAQ index - it is set per account
    # type at purchase. Every other field in this dict moved today because a
    # page was found that stated it. This one did not, and writing the
    # widely-repeated 1:100 would be exactly the invention this file exists
    # to refuse.
    "max_leverage": None,
}

#: News and weekend holding during the Evaluation Process.
#:
#: Both restrictions are real and neither applies here, which is a
#: distinction worth keeping: FTMO gates them on the *funded* account, not
#: on the challenge. "While trading during the Evaluation Process, the
#: restriction does not apply regardless of the account type" - said twice,
#: once on each page, for news and for holding.
_FTMO_EVALUATION: dict[str, Any] = {
    **_FTMO_COMMON,
    "news_trading_allowed": True,
    "weekend_holding_allowed": True,
    # The Best Day Rule is a 1-Step rule. See `_FTMO_1STEP` below; on the
    # two-phase products FTMO states no equivalent, and a stated absence is
    # not the same as an unread field.
    "max_single_day_profit_share": NOT_IMPOSED,
}

#: The 1-Step products, which carry the one consistency rule FTMO imposes.
#:
#: "the Best Day Rule requires that your Best Day does not represent more
#: than 50% of your Positive Days\' Profit", and it "applies to the FTMO
#: Challenge: 1-Step as well as the FTMO Account (1-Step)" - so it is set
#: here and nowhere else.
_FTMO_1STEP: dict[str, Any] = {
    **_FTMO_EVALUATION,
    "max_single_day_profit_share": 0.50,
}

#: The funded account, where the two restrictions switch on.
#:
#: Encoded for the **Standard** account type. Swing is exempt from both and
#: is a different product the holder chooses at purchase; the note beside
#: this rulebook says so, because a Swing holder reading `False` here would
#: be reading a rule that is not theirs. Standard is the restrictive
#: reading, which is the safe direction to be wrong in.
_FTMO_FUNDED: dict[str, Any] = {
    **_FTMO_COMMON,
    "news_trading_allowed": False,
    "weekend_holding_allowed": False,
    "max_single_day_profit_share": NOT_IMPOSED,
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
_FTMO_EA = (
    "this firm permits algorithmic trading and EAs outright, and caps the "
    "platform at 200 open orders at a time and 2,000 positions per day; an "
    "EA that makes the server hyperactive may be asked to slow down"
)
_FTMO_EVAL_FREE = (
    "the news and weekend-holding restrictions belong to the funded FTMO "
    "Account, not to the evaluation: during the Challenge and Verification "
    "both are explicitly lifted for every account type"
)
_FTMO_STANDARD = (
    "these are the Standard account type's restrictions - no trade opened or "
    "closed within two minutes either side of a listed news release on the "
    "affected instrument, and positions closed before the weekend or a "
    "rollover longer than two hours. A Swing account is exempt from both, so "
    "confirm which type this account is before trusting the two flags"
)
_FTMO_BEST_DAY = (
    "the Best Day Rule caps the most profitable day at 50% of the sum of all "
    "profitable days, and exceeding it is not a breach - it withholds the "
    "pass or the reward until further profit brings the share back down"
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
            **_FTMO_EVALUATION,
        ),
        source=FTMO_SOURCE,
        retrieved=FTMO_RETRIEVED,
        notes=(
            _CLOSED_ONLY,
            _FTMO_TRAIL,
            _FTMO_DAILY,
            _FTMO_EQUITY,
            _FTMO_DAYS,
            _FTMO_EA,
            _FTMO_EVAL_FREE,
        ),
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
            **_FTMO_EVALUATION,
        ),
        source=FTMO_SOURCE,
        retrieved=FTMO_RETRIEVED,
        notes=(
            _CLOSED_ONLY,
            _FTMO_TRAIL,
            _FTMO_DAILY,
            _FTMO_EQUITY,
            _FTMO_DAYS,
            _FTMO_EA,
            _FTMO_EVAL_FREE,
        ),
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
            **_FTMO_1STEP,
        ),
        source=FTMO_SOURCE,
        retrieved=FTMO_RETRIEVED,
        notes=(
            _CLOSED_ONLY,
            _FTMO_TRAIL,
            _FTMO_DAILY,
            _FTMO_EQUITY,
            _FTMO_DAYS,
            _FTMO_EA,
            _FTMO_EVAL_FREE,
            _FTMO_BEST_DAY,
        ),
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
            **_FTMO_FUNDED,
        ),
        source=FTMO_SOURCE,
        retrieved=FTMO_RETRIEVED,
        notes=(
            _FTMO_TRAIL,
            _FTMO_DAILY,
            _FTMO_EQUITY,
            _FTMO_EA,
            _FTMO_STANDARD,
        ),
    ),
)

BY_KEY: dict[str, Rulebook] = {book.key: book for book in RULEBOOKS}


def get(key: str) -> Rulebook | None:
    return BY_KEY.get(key)


def providers() -> list[str]:
    return sorted({book.provider for book in RULEBOOKS})
