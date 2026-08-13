"""The transcribed prop-firm rulebooks (spec §28).

Until these existed the challenge brain was exercised against a rulebook whose
own response called it "not a provider's verified rules". The arithmetic was
right and the numbers were nobody's.

So these tests are mostly about provenance rather than behaviour. A wrong
number here does not crash anything: it produces a confident headroom figure
for a limit the provider does not have, which is the most expensive kind of
quiet wrong this system can be.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.brain import challenge as ch
from app.brain import rulebooks as rb


class TestEveryRulebookCarriesItsProvenance:
    @pytest.mark.parametrize("book", rb.RULEBOOKS, ids=lambda b: b.key)
    def test_it_names_a_source(self, book):
        """A rule with no source cannot be re-checked, and a prop firm's terms
        are not the kind of thing to remember wrongly."""
        assert book.source.startswith("https://")

    @pytest.mark.parametrize("book", rb.RULEBOOKS, ids=lambda b: b.key)
    def test_it_is_dated(self, book):
        """Providers change their terms. A rulebook with no date silently ages
        into a different firm's rules."""
        assert isinstance(book.retrieved, date)

    @pytest.mark.parametrize("book", rb.RULEBOOKS, ids=lambda b: b.key)
    def test_nothing_in_the_file_claims_the_holder_confirmed_it(self, book):
        """What a marketing page publishes and what one account's contract says
        are not guaranteed to be the same document. Only the person who signed
        up can close that gap, so no entry may ship pre-confirmed."""
        assert book.confirmed_by_holder is False

    def test_the_keys_are_unique(self):
        keys = [book.key for book in rb.RULEBOOKS]

        assert len(keys) == len(set(keys))


class TestTheNumbersSurviveTheChallengeBrain:
    @pytest.mark.parametrize("book", rb.RULEBOOKS, ids=lambda b: b.key)
    def test_a_healthy_account_is_permitted(self, book):
        """Every transcribed book must produce a usable answer for an untouched
        account. One that blocks a fresh account has a rule in the wrong state,
        and the block would read as caution rather than as a transcription
        error."""
        verdict = ch.check(book.rules, _fresh(), 1.0)

        assert verdict.allowed is True, verdict.unverified

    @pytest.mark.parametrize("book", rb.RULEBOOKS, ids=lambda b: b.key)
    def test_no_drawdown_rule_is_left_unknown(self, book):
        """The two drawdown rules are the ones that block when unknown, and
        they are also the two this file exists to get right.

        Scoped to the drawdown notes on purpose. Leverage, position count and
        weekend holding are unknown here deliberately, and an assertion broad
        enough to catch those would force them to be guessed to stay green -
        which is the failure this file was written to avoid."""
        verdict = ch.check(book.rules, _fresh(), 1.0)

        drawdown_notes = [n for n in verdict.unverified if "drawdown" in n]

        assert not any("never entered" in note for note in drawdown_notes)

    @pytest.mark.parametrize("book", rb.RULEBOOKS, ids=lambda b: b.key)
    def test_the_unknown_rules_are_named_rather_than_silently_skipped(self, book):
        """The three this file could not source have to show up somewhere. A
        rule nobody checked and nobody mentioned is indistinguishable from a
        rule that passed."""
        verdict = ch.check(book.rules, _fresh(), 1.0)
        notes = " ".join(verdict.unverified)

        assert "leverage" in notes
        assert "concurrent-position" in notes
        assert "weekend" in notes


class TestTheFundedNextFiguresAreWhatThePagePublishes:
    """Spot checks against the published table, not against the code.

    Written out longhand rather than looped, because a loop over the same
    constants the module defines would pass no matter what those constants say.
    """

    def test_one_step(self):
        rules = rb.get("fundednext-stellar-1step").rules

        assert rules.profit_target_pct == 0.10
        assert rules.max_daily_drawdown_pct == 0.03
        assert rules.max_total_drawdown_pct == 0.06
        assert rules.min_trading_days == 2

    def test_two_step_phase_one(self):
        rules = rb.get("fundednext-stellar-2step-phase1").rules

        assert rules.profit_target_pct == 0.08
        assert rules.max_daily_drawdown_pct == 0.05
        assert rules.max_total_drawdown_pct == 0.10
        assert rules.min_trading_days == 5

    def test_two_step_phase_two_lowers_only_the_target(self):
        """The phase-2 target drops to 5% while both loss limits stay where
        they were - a rulebook that relaxed the floors between phases would be
        a different and much easier challenge."""
        one = rb.get("fundednext-stellar-2step-phase1").rules
        two = rb.get("fundednext-stellar-2step-phase2").rules

        assert two.profit_target_pct == 0.05
        assert two.max_daily_drawdown_pct == one.max_daily_drawdown_pct
        assert two.max_total_drawdown_pct == one.max_total_drawdown_pct

    def test_lite(self):
        one = rb.get("fundednext-stellar-lite-phase1").rules
        two = rb.get("fundednext-stellar-lite-phase2").rules

        assert (one.profit_target_pct, two.profit_target_pct) == (0.08, 0.04)
        assert one.max_daily_drawdown_pct == 0.04
        assert one.max_total_drawdown_pct == 0.08

    def test_instant_is_the_only_trailing_floor(self):
        """The page marks exactly one program Trailing. Getting this backwards
        moves the floor by the whole account once it is in profit."""
        trailing = [b.key for b in rb.RULEBOOKS if b.rules.total_drawdown_trailing]

        assert trailing == ["fundednext-stellar-instant"]

    def test_instant_has_no_target_and_no_daily_limit_but_says_so(self):
        """Absent is not unknown here: the page states there is none, so the
        marker is used rather than a blank."""
        rules = rb.get("fundednext-stellar-instant").rules

        assert rules.profit_target_pct is rb.NOT_IMPOSED
        assert rules.max_daily_drawdown_pct is rb.NOT_IMPOSED
        assert rules.max_total_drawdown_pct == 0.06


class TestTheRulersAreTranscribedNotAssumed:
    @pytest.mark.parametrize("book", rb.RULEBOOKS, ids=lambda b: b.key)
    def test_the_allowance_is_a_share_of_the_starting_balance(self, book):
        """"a percentage of the initial balance". Reading it as a share of
        current equity shrinks the allowance exactly when an account is down
        and needs it measured correctly."""
        assert book.rules.allowance_basis is ch.AllowanceBasis.STARTING_BALANCE

    @pytest.mark.parametrize("book", rb.RULEBOOKS, ids=lambda b: b.key)
    def test_the_daily_limit_is_measured_on_equity(self, book):
        """"Includes realized and unrealized P&L" - the unrealized half is what
        makes it an equity rule, so a floating loss counts the moment it
        exists rather than when it is closed."""
        assert book.rules.drawdown_basis is ch.DrawdownBasis.EQUITY

    @pytest.mark.parametrize("book", rb.RULEBOOKS, ids=lambda b: b.key)
    def test_there_is_no_deadline(self, book):
        assert book.rules.max_trading_days is rb.NOT_IMPOSED


class TestWhatThePageDoesNotSayStaysUnknown:
    @pytest.mark.parametrize("book", rb.RULEBOOKS, ids=lambda b: b.key)
    def test_weekend_holding_is_not_guessed(self, book):
        """It appears on no tab. Inferring it from silence is how a rulebook
        acquires a rule its provider never wrote."""
        assert book.rules.weekend_holding_allowed is None

    @pytest.mark.parametrize("book", rb.RULEBOOKS, ids=lambda b: b.key)
    def test_leverage_is_not_guessed(self, book):
        """Published per symbol, not on the rules page."""
        assert book.rules.max_leverage is None

    @pytest.mark.parametrize("book", rb.RULEBOOKS, ids=lambda b: b.key)
    def test_news_trading_is_recorded_as_allowed_because_it_is_stated(self, book):
        """"allowed, with no restrictions on when or how you trade", and the
        news profit split explicitly excludes the challenge phases."""
        assert book.rules.news_trading_allowed is True


class TestThePayloadKeepsAbsentApartFromUnknown:
    def test_a_stated_absence_reads_as_words_not_as_null(self):
        """Both render empty in JSON otherwise, and they are opposite facts."""
        payload = rb.get("fundednext-stellar-instant").as_dict()

        assert payload["profit_target_pct"] == "not imposed"

    def test_a_real_number_survives_the_trip(self):
        payload = rb.get("fundednext-stellar-1step").as_dict()

        assert payload["max_daily_drawdown_pct"] == 0.03

    def test_the_notes_carry_what_the_numbers_cannot(self):
        """The automation note is the one worth having: EAs are permitted on
        every model but need a paid add-on, so running this system against a
        challenge without one is a rule breach rather than a technical
        problem."""
        notes = " ".join(rb.get("fundednext-stellar-2step-phase1").as_dict()["notes"])

        assert "add-on" in notes


def _fresh() -> ch.ChallengeState:
    """An account that has done nothing yet, priced so a cap can be computed."""
    return ch.ChallengeState(
        starting_balance=100_000.0,
        current_equity=100_000.0,
        peak_equity=100_000.0,
        daily_starting_equity=100_000.0,
        daily_starting_balance=100_000.0,
        current_balance=100_000.0,
        days_traded=5,
        open_positions=0,
        current_date=date(2026, 8, 13),
        currency_per_r=200.0,
    )
