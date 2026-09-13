"""Sizing a rehearsal demo so a FundedNext rulebook can actually run on it.

The plan this file exists to check: put a RoboForex demo under a real
FundedNext rulebook, so the drawdown and target rules are rehearsed against
live prices before any of it touches a paid challenge.

The trap is one we set ourselves the day before. `automation_max_account_size`
is read against `starting_balance` and knows nothing about who the broker is
or whether the account is a demo - correctly, because a $200,000 FundedNext
account drawn down to $40,000 has not become eligible. But it means a demo
sized the way this fleet sizes demos, at $200,000, would be registered under
a FundedNext rulebook and then refuse every order it was created to place.

`test_challenge.py` already tests the ceiling against synthetic rules. These
tests ask the same question of the seven rulebooks that are actually shipped,
because the number that matters is the one in `rulebooks.py`, not the one a
fixture chose.

The verdict below: $40,000 is the demo size. It clears the ceiling on every
FundedNext program, and it is wide enough for one minimum lot of gold, which
needs about $14,900 of margin and is what makes $15,000 unusable in practice.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.brain import challenge as ch
from app.brain import rulebooks as books

#: What this file argues for.
REHEARSAL_BALANCE = 40_000.0

#: What the fleet sizes demos at today, and why the question came up.
FLEET_DEMO_BALANCE = 200_000.0

#: Roughly the margin one minimum lot of gold needs. The floor under any
#: rehearsal size that intends to trade the instrument the fleet trades most.
ONE_LOT_OF_GOLD = 14_900.0

FUNDEDNEXT = [b for b in books.RULEBOOKS if b.provider == "FundedNext"]
FTMO = [b for b in books.RULEBOOKS if b.provider == "FTMO"]


def rehearsal(starting_balance: float, **over) -> ch.ChallengeState:
    """A quiet account: no drawdown, no positions, nothing else to object to.

    Everything that could independently refuse is set to the permissive value
    so that a refusal in these tests is the account-size ceiling and nothing
    standing next to it.
    """
    base = dict(
        starting_balance=starting_balance,
        current_equity=starting_balance,
        current_balance=starting_balance,
        peak_equity=starting_balance,
        daily_starting_equity=starting_balance,
        daily_profits={},
        days_traded=5,
        open_positions=0,
        current_date=date(2026, 9, 9),
        currency_per_r=starting_balance * 0.0075,
        current_leverage=0.0,
        in_news_window=False,
        weekend_ahead=False,
        rules_confirmed_by_holder=True,
    )
    base.update(over)
    return ch.ChallengeState(**base)


def ceiling_breach(verdict) -> str | None:
    return next((b for b in verdict.breaches if "only below" in b), None)


class TestTheFleetDemoSizeWouldRefuseEveryOrder:
    @pytest.mark.parametrize("book", FUNDEDNEXT, ids=lambda b: b.key)
    def test_two_hundred_thousand_breaches_every_fundednext_program(self, book):
        verdict = ch.check(book.rules, rehearsal(FLEET_DEMO_BALANCE), 1.0)

        assert ceiling_breach(verdict) is not None, book.key

    @pytest.mark.parametrize("book", FUNDEDNEXT, ids=lambda b: b.key)
    def test_and_therefore_refuses_the_trade(self, book):
        assert ch.check(book.rules, rehearsal(FLEET_DEMO_BALANCE), 1.0).allowed is False

    def test_the_refusal_names_the_account_size(self):
        book = books.BY_KEY["fundednext-stellar-2step-phase1"]

        breach = ceiling_breach(ch.check(book.rules, rehearsal(FLEET_DEMO_BALANCE), 1.0))

        assert "200,000" in breach

    def test_being_a_demo_does_not_exempt_it(self):
        # There is no demo flag in the state and deliberately so: the rulebook
        # describes a contract, and a rehearsal that quietly drops a rule is
        # not a rehearsal of that contract. The size is what has to change.
        assert not hasattr(ch.ChallengeState, "is_demo")


class TestFortyThousandIsTheRehearsalSize:
    @pytest.mark.parametrize("book", FUNDEDNEXT, ids=lambda b: b.key)
    def test_it_clears_the_ceiling_on_every_fundednext_program(self, book):
        verdict = ch.check(book.rules, rehearsal(REHEARSAL_BALANCE), 1.0)

        assert ceiling_breach(verdict) is None, book.key

    @pytest.mark.parametrize("book", FUNDEDNEXT, ids=lambda b: b.key)
    def test_a_quiet_account_is_allowed_to_trade(self, book):
        verdict = ch.check(book.rules, rehearsal(REHEARSAL_BALANCE), 1.0)

        assert verdict.allowed is True, (book.key, verdict.breaches)

    def test_it_leaves_room_for_one_lot_of_gold(self):
        assert REHEARSAL_BALANCE > ONE_LOT_OF_GOLD

    def test_fifteen_thousand_would_not(self):
        # The Free Trial size clears the ceiling and still cannot hold the
        # position the fleet trades most, which is why it is not the answer.
        assert 15_000.0 < ONE_LOT_OF_GOLD * 1.05

    def test_it_sits_below_the_line_the_firm_drew(self):
        book = books.BY_KEY["fundednext-stellar-2step-phase1"]

        assert REHEARSAL_BALANCE < float(book.rules.automation_max_account_size)


class TestTheLineItselfIsWhereTheFirmPutIt:
    @pytest.mark.parametrize("book", FUNDEDNEXT, ids=lambda b: b.key)
    def test_every_fundednext_program_carries_the_ceiling(self, book):
        assert book.rules.automation_max_account_size == 50_000.0

    @pytest.mark.parametrize("book", FUNDEDNEXT, ids=lambda b: b.key)
    def test_exactly_fifty_thousand_is_already_too_big(self, book):
        # "accounts of $50,000 and above", so the line is inclusive and a demo
        # sized exactly at it is on the wrong side.
        verdict = ch.check(book.rules, rehearsal(50_000.0), 1.0)

        assert ceiling_breach(verdict) is not None, book.key

    @pytest.mark.parametrize("book", FUNDEDNEXT, ids=lambda b: b.key)
    def test_a_dollar_under_is_permitted(self, book):
        verdict = ch.check(book.rules, rehearsal(49_999.0), 1.0)

        assert ceiling_breach(verdict) is None, book.key

    @pytest.mark.parametrize("book", FTMO, ids=lambda b: b.key)
    def test_ftmo_carries_no_such_ceiling_at_any_size(self, book):
        verdict = ch.check(book.rules, rehearsal(FLEET_DEMO_BALANCE), 1.0)

        assert ceiling_breach(verdict) is None, book.key

    @pytest.mark.parametrize("book", FTMO, ids=lambda b: b.key)
    def test_ftmo_permits_a_two_hundred_thousand_rehearsal(self, book):
        # The other way to rehearse a large account: FTMO permits EAs
        # outright, so the size question does not arise there at all.
        assert ch.check(book.rules, rehearsal(FLEET_DEMO_BALANCE), 1.0).allowed is True

    def test_seven_fundednext_rulebooks_are_shipped(self):
        assert len(FUNDEDNEXT) == 7


class TestTheRehearsalStillEnforcesTheRulesItIsFor:
    """A smaller demo must not become a demo with fewer rules.

    The point of the rehearsal is the money rules. If sizing down quietly
    relaxed one of them the exercise would be worthless, so each is provoked
    at the rehearsal size and has to still refuse.
    """

    BOOK = books.BY_KEY["fundednext-stellar-2step-phase1"]

    def test_the_daily_drawdown_still_binds(self):
        # It binds by cutting the size rather than refusing outright: with $10
        # of headroom left there is still a trade small enough to survive
        # losing everything it risks, and the engine says how small.
        rules = self.BOOK.rules
        floor = REHEARSAL_BALANCE * (1 - float(rules.max_daily_drawdown_pct))

        verdict = ch.check(
            rules,
            rehearsal(REHEARSAL_BALANCE, current_equity=floor + 10.0),
            5.0,
        )

        assert verdict.verdict == "reduce"
        assert verdict.max_additional_risk_r < 5.0

    def test_the_total_drawdown_still_binds(self):
        rules = self.BOOK.rules
        floor = REHEARSAL_BALANCE * (1 - float(rules.max_total_drawdown_pct))

        verdict = ch.check(
            rules,
            rehearsal(
                REHEARSAL_BALANCE,
                current_equity=floor + 10.0,
                current_balance=floor + 10.0,
            ),
            5.0,
        )

        assert verdict.allowed is False

    def test_an_unconfirmed_rulebook_still_refuses(self):
        # Every transcribed rulebook ships unconfirmed, and a rehearsal is not
        # a reason to stop asking the holder to check it against the contract.
        verdict = ch.check(
            self.BOOK.rules,
            rehearsal(REHEARSAL_BALANCE, rules_confirmed_by_holder=False),
            1.0,
        )

        assert verdict.allowed is False

    def test_the_shipped_rulebook_is_unconfirmed(self):
        assert self.BOOK.confirmed_by_holder is False
