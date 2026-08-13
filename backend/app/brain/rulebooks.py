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
)

#: When the FundedNext pages below were read.
FUNDEDNEXT_RETRIEVED = date(2026, 8, 13)
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
#   No consistency rule appears anywhere in the published Trading Objectives.
#   That is recorded as NOT_IMPOSED on the strength of the page's own claim to
#   list "every rule, every condition" - an inference, and named as one.
#
#   Weekend holding is left unknown. It is not mentioned on any tab, and the
#   exhaustiveness claim is a weaker basis for a rule about when positions may
#   be held than for one about how they are scored.

_COMMON: dict[str, Any] = {
    "drawdown_basis": DrawdownBasis.EQUITY,
    "allowance_basis": AllowanceBasis.STARTING_BALANCE,
    "total_drawdown_trailing": False,
    "max_trading_days": NOT_IMPOSED,       # "No deadline to pass the Challenge."
    "max_single_day_profit_share": NOT_IMPOSED,
    "news_trading_allowed": True,
    "weekend_holding_allowed": None,       # not stated anywhere
    "max_leverage": None,                  # varies per symbol, not published here
    "max_concurrent_positions": None,      # not stated
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


RULEBOOKS: tuple[Rulebook, ...] = (
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
        ),
        source=FUNDEDNEXT_SOURCE,
        retrieved=FUNDEDNEXT_RETRIEVED,
        notes=(_CLOSED_ONLY, "maximum loss is static", _INACTIVITY, _MARGIN, _AUTOMATION),
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
            **{**_COMMON, "total_drawdown_trailing": True},
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
