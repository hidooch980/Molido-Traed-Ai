"""Rulebooks the holder writes, and the wall between them and the transcribed ten.

Two things make this feature safe rather than a hole, and both are properties
rather than code paths, so they are what most of this file is about.

**The transcribed rulebooks stay read only.** They carry the URL they were
read from and the date they were read, and that provenance is the whole
value - a number somebody can edit is no longer evidence of what a firm
published. There is deliberately no path here or anywhere that writes one, and
the tests assert the absence rather than trusting it.

**Writing your own must not be the way around the rules that matter.** Two
carry over unchanged: a rule nobody set blocks rather than passes, and
authoring a limit is not confirming it. If either relaxed on this side, "write
your own rulebook" would quietly become the way to trade with no limits and a
green tick.

The rest is ordinary: keys cannot collide, a rulebook in use cannot be
deleted, and a percentage is a fraction.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.brain import challenge as ch
from app.brain import rulebooks as books
from app.core.errors import NotFoundError, ValidationFailedError
from app.models.custom_rulebooks import KEY_PREFIX
from app.services import challenge_accounts, custom_rulebooks

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)

#: The four limits this was actually asked for: profit target, daily loss,
#: max daily loss and max loss - which in this engine are three rules, the
#: daily one being one number rather than two.
ASKED_FOR = {
    "profit_target_pct": 0.10,
    "max_daily_drawdown_pct": 0.05,
    "max_total_drawdown_pct": 0.10,
}


@pytest.fixture()
def tenant(session):
    return challenge_accounts.default_tenant(session)


def write(session, tenant, *, name="My demo discipline", rules=None, **over):
    return custom_rulebooks.create(
        session,
        tenant_id=tenant,
        name=name,
        rules=ASKED_FOR if rules is None else rules,
        now=NOW,
        **over,
    )


class TestTheTranscribedOnesAreReadOnly:
    def test_there_is_no_update_path_to_a_transcribed_rulebook(self, session, tenant):
        with pytest.raises(ValidationFailedError) as raised:
            custom_rulebooks.update(
                session, tenant_id=tenant, key="fundednext-stellar-1step", rules={}
            )

        assert "read only" in str(raised.value)

    @pytest.mark.parametrize("book", books.RULEBOOKS, ids=lambda b: b.key)
    def test_not_one_of_them_can_be_edited(self, session, tenant, book):
        with pytest.raises(ValidationFailedError):
            custom_rulebooks.update(session, tenant_id=tenant, key=book.key, rules={})

    def test_the_service_exposes_no_writer_for_them(self):
        # The absence is the feature. If a function is ever added that takes a
        # transcribed key and writes, this is the test that has to be deleted
        # first - which is a visible line in a diff.
        source = (custom_rulebooks.__doc__ or "") + str(
            custom_rulebooks.update.__doc__ or ""
        )

        assert "read only" in source

    def test_every_transcribed_key_is_protected(self):
        assert custom_rulebooks.PROTECTED == frozenset(b.key for b in books.RULEBOOKS)

    def test_a_transcribed_key_cannot_be_taken_by_a_custom_one(self, session, tenant):
        # Belt and braces: the prefix already makes this impossible, so this
        # is what fails if the prefix is ever dropped.
        assert all(not custom_rulebooks.is_custom(k) for k in custom_rulebooks.PROTECTED)


class TestTheTwoNamespacesCannotCollide:
    def test_a_written_key_carries_the_prefix(self, session, tenant):
        row = write(session, tenant)

        assert row.key.startswith(KEY_PREFIX)

    def test_the_key_is_made_from_the_name(self, session, tenant):
        row = write(session, tenant, name="My demo discipline")

        assert row.key == "custom:my-demo-discipline"

    def test_punctuation_and_case_collapse(self, session, tenant):
        row = write(session, tenant, name="  RoboForex  DEMO (40k)!  ")

        assert row.key == "custom:roboforex-demo-40k"

    def test_a_name_of_only_punctuation_is_refused(self, session, tenant):
        with pytest.raises(ValidationFailedError) as raised:
            write(session, tenant, name="!!!")

        assert "at least one letter or digit" in str(raised.value)

    def test_two_rulebooks_cannot_share_a_name(self, session, tenant):
        write(session, tenant, name="Mine")

        with pytest.raises(ValidationFailedError) as raised:
            write(session, tenant, name="mine")

        assert "already exists" in str(raised.value)

    def test_is_custom_reads_the_prefix(self):
        assert custom_rulebooks.is_custom("custom:anything") is True
        assert custom_rulebooks.is_custom("fundednext-stellar-1step") is False

    def test_is_custom_on_nothing_is_false(self):
        assert custom_rulebooks.is_custom(None) is False
        assert custom_rulebooks.is_custom("") is False

    def test_an_empty_name_is_refused(self, session, tenant):
        with pytest.raises(ValidationFailedError):
            write(session, tenant, name="   ")

    def test_an_overlong_name_is_refused(self, session, tenant):
        with pytest.raises(ValidationFailedError):
            write(session, tenant, name="x" * 121)


class TestNobodySaidIsNotNothing:
    def test_a_rule_left_out_stays_unset(self, session, tenant):
        row = write(session, tenant, rules={"profit_target_pct": 0.10})

        assert custom_rulebooks.to_rules(row.rules).max_daily_drawdown_pct is None

    def test_and_an_unset_rule_blocks(self, session, tenant):
        # The property that makes leaving a field alone safe: it does not pass.
        row = write(session, tenant, rules={"profit_target_pct": 0.10})
        rules = custom_rulebooks.to_rules(row.rules)

        verdict = ch.check(rules, quiet_account(), 1.0)

        assert verdict.allowed is False

    def test_not_imposed_is_a_claim_somebody_made(self, session, tenant):
        row = write(
            session,
            tenant,
            rules={**ASKED_FOR, "max_leverage": "not imposed"},
        )

        assert custom_rulebooks.to_rules(row.rules).max_leverage is ch.NOT_IMPOSED

    def test_the_word_is_case_insensitive(self, session, tenant):
        row = write(session, tenant, rules={**ASKED_FOR, "max_leverage": "NOT IMPOSED"})

        assert custom_rulebooks.to_rules(row.rules).max_leverage is ch.NOT_IMPOSED

    def test_the_two_empty_states_are_stored_differently(self, session, tenant):
        row = write(session, tenant, rules={**ASKED_FOR, "max_leverage": "not imposed"})

        assert "max_leverage" in row.rules
        assert "min_trading_days" not in row.rules

    def test_any_other_string_is_refused_rather_than_coerced(self, session, tenant):
        # "5" and 5 differ by a typo somebody should see.
        with pytest.raises(ValidationFailedError) as raised:
            write(session, tenant, rules={"profit_target_pct": "0.10"})

        assert "not imposed" in str(raised.value)


class TestAuthoringIsNotConfirming:
    def test_a_written_rulebook_is_born_unconfirmed(self, session, tenant):
        row = write(session, tenant)

        assert custom_rulebooks.to_rulebook(row).confirmed_by_holder is False

    def test_an_account_on_one_still_has_to_be_confirmed(self, session, tenant):
        row = write(session, tenant)
        account = challenge_accounts.create(
            session,
            tenant_id=tenant,
            label="RoboForex demo 40k",
            rulebook_key=row.key,
            starting_balance=Decimal("40000"),
            currency_per_r=Decimal("300"),
        )

        view = challenge_accounts.view_of(session, account)

        assert view.as_dict()["tracking_available"] is False

    def test_confirming_the_account_opens_tracking(self, session, tenant):
        row = write(session, tenant)
        account = challenge_accounts.create(
            session,
            tenant_id=tenant,
            label="RoboForex demo 40k",
            rulebook_key=row.key,
            starting_balance=Decimal("40000"),
            currency_per_r=Decimal("300"),
        )

        challenge_accounts.confirm(
            session, tenant_id=tenant, account_id=account.id, notes="my own rules"
        )

        assert challenge_accounts.view_of(session, account).as_dict()["tracking_available"]


class TestARuleIsANumberOfTheRightKind:
    def test_a_percentage_is_a_fraction(self, session, tenant):
        with pytest.raises(ValidationFailedError) as raised:
            write(session, tenant, rules={"max_daily_drawdown_pct": 5})

        assert "0.05 rather than 5" in str(raised.value)

    def test_a_fraction_just_under_one_is_allowed(self, session, tenant):
        row = write(session, tenant, rules={"max_daily_drawdown_pct": 0.99})

        assert custom_rulebooks.to_rules(row.rules).max_daily_drawdown_pct == 0.99

    def test_zero_is_refused_with_the_alternative_named(self, session, tenant):
        with pytest.raises(ValidationFailedError) as raised:
            write(session, tenant, rules={"max_daily_drawdown_pct": 0})

        assert "not imposed" in str(raised.value)

    def test_a_negative_rule_is_refused(self, session, tenant):
        with pytest.raises(ValidationFailedError):
            write(session, tenant, rules={"max_total_drawdown_pct": -0.05})

    def test_a_whole_number_rule_refuses_a_fraction(self, session, tenant):
        with pytest.raises(ValidationFailedError) as raised:
            write(session, tenant, rules={"min_trading_days": 2.5})

        assert "whole number" in str(raised.value)

    def test_a_flag_refuses_a_number(self, session, tenant):
        with pytest.raises(ValidationFailedError):
            write(session, tenant, rules={"news_trading_allowed": 1})

    def test_a_number_refuses_a_flag(self, session, tenant):
        # True is 1 to Python and would otherwise land as a leverage cap of one.
        with pytest.raises(ValidationFailedError) as raised:
            write(session, tenant, rules={"max_leverage": True})

        assert "is a number" in str(raised.value)

    def test_a_flag_is_stored_as_written(self, session, tenant):
        row = write(session, tenant, rules={**ASKED_FOR, "news_trading_allowed": False})

        assert custom_rulebooks.to_rules(row.rules).news_trading_allowed is False

    def test_an_unknown_rule_is_refused_by_name(self, session, tenant):
        # Silently dropping it would leave the holder believing they set a
        # limit the engine never sees, which is the worst of the outcomes.
        with pytest.raises(ValidationFailedError) as raised:
            write(session, tenant, rules={"max_lunch_breaks": 2})

        assert "max_lunch_breaks" in str(raised.value)

    def test_the_refusal_lists_what_it_would_accept(self, session, tenant):
        with pytest.raises(ValidationFailedError) as raised:
            write(session, tenant, rules={"nonsense": 1})

        assert "profit_target_pct" in str(raised.value)

    def test_a_basis_is_one_of_its_own_words(self, session, tenant):
        with pytest.raises(ValidationFailedError) as raised:
            write(session, tenant, rules={**ASKED_FOR, "drawdown_basis": "vibes"})

        assert "equity" in str(raised.value)

    def test_a_basis_survives_the_round_trip(self, session, tenant):
        row = write(session, tenant, rules={**ASKED_FOR, "drawdown_basis": "balance"})

        assert custom_rulebooks.to_rules(row.rules).drawdown_basis is ch.DrawdownBasis.BALANCE

    def test_the_default_basis_is_equity(self, session, tenant):
        row = write(session, tenant)

        assert custom_rulebooks.to_rules(row.rules).drawdown_basis is ch.DrawdownBasis.EQUITY


class TestAnAccountIsMeasuredByIt:
    def test_an_account_can_name_a_written_rulebook(self, session, tenant):
        row = write(session, tenant)

        account = challenge_accounts.create(
            session,
            tenant_id=tenant,
            label="RoboForex demo 40k",
            rulebook_key=row.key,
            starting_balance=Decimal("40000"),
            currency_per_r=Decimal("300"),
        )

        assert account.rulebook_key == row.key

    def test_the_account_resolves_to_it(self, session, tenant):
        row = write(session, tenant)
        account = challenge_accounts.create(
            session,
            tenant_id=tenant,
            label="RoboForex demo 40k",
            rulebook_key=row.key,
            starting_balance=Decimal("40000"),
            currency_per_r=Decimal("300"),
        )

        view = challenge_accounts.view_of(session, account)

        assert view.rulebook is not None
        assert view.rulebook.key == row.key

    def test_an_unknown_written_key_is_refused(self, session, tenant):
        with pytest.raises(ValidationFailedError) as raised:
            challenge_accounts.create(
                session,
                tenant_id=tenant,
                label="nowhere",
                rulebook_key="custom:does-not-exist",
                starting_balance=Decimal("40000"),
            )

        assert "custom:does-not-exist" in str(raised.value)

    def test_the_refusal_lists_the_written_ones_too(self, session, tenant):
        write(session, tenant, name="Mine")

        with pytest.raises(ValidationFailedError) as raised:
            challenge_accounts.create(
                session,
                tenant_id=tenant,
                label="nowhere",
                rulebook_key="custom:nope",
                starting_balance=Decimal("40000"),
            )

        assert "custom:mine" in str(raised.value)

    def test_the_transcribed_ones_still_resolve(self, session, tenant):
        account = challenge_accounts.create(
            session,
            tenant_id=tenant,
            label="FTMO 100k",
            rulebook_key="ftmo-challenge-1step",
            starting_balance=Decimal("100000"),
            currency_per_r=Decimal("500"),
        )

        assert challenge_accounts.view_of(session, account).rulebook is not None

    def test_a_written_rulebook_belongs_to_its_tenant(self, session, tenant):
        # Resolving across tenants would measure one holder's account against
        # another holder's rules.
        row = write(session, tenant)
        other = custom_rulebooks.resolve(
            session, tenant_id=_a_different_tenant(session), key=row.key
        )

        assert other is None

    def test_the_written_rules_actually_bind(self, session, tenant):
        row = write(session, tenant, rules={**ASKED_FOR, "max_concurrent_positions": 1})
        rules = custom_rulebooks.to_rules(row.rules)

        verdict = ch.check(rules, quiet_account(open_positions=1), 1.0)

        assert verdict.allowed is False


class TestEditingAndDeleting:
    def test_an_edit_replaces_the_document(self, session, tenant):
        row = write(session, tenant)

        custom_rulebooks.update(
            session,
            tenant_id=tenant,
            key=row.key,
            rules={"profit_target_pct": 0.08},
            now=NOW,
        )

        assert custom_rulebooks.to_rules(row.rules).max_daily_drawdown_pct is None

    def test_an_edit_can_change_a_number(self, session, tenant):
        row = write(session, tenant)

        custom_rulebooks.update(
            session,
            tenant_id=tenant,
            key=row.key,
            rules={**ASKED_FOR, "max_daily_drawdown_pct": 0.03},
            now=NOW,
        )

        assert custom_rulebooks.to_rules(row.rules).max_daily_drawdown_pct == 0.03

    def test_an_edit_records_who(self, session, tenant):
        row = write(session, tenant)

        custom_rulebooks.update(
            session, tenant_id=tenant, key=row.key, notes="tightened", changed_by="aziz"
        )

        assert row.changed_by == "aziz"

    def test_omitting_rules_leaves_them_alone(self, session, tenant):
        row = write(session, tenant)

        custom_rulebooks.update(session, tenant_id=tenant, key=row.key, notes="just a note")

        assert custom_rulebooks.to_rules(row.rules).profit_target_pct == 0.10

    def test_editing_something_that_is_not_there_is_not_found(self, session, tenant):
        with pytest.raises(NotFoundError):
            custom_rulebooks.update(session, tenant_id=tenant, key="custom:ghost", rules={})

    def test_an_invalid_edit_is_refused(self, session, tenant):
        row = write(session, tenant)

        with pytest.raises(ValidationFailedError):
            custom_rulebooks.update(
                session, tenant_id=tenant, key=row.key, rules={"profit_target_pct": 50}
            )

    def test_an_unused_rulebook_can_be_deleted(self, session, tenant):
        row = write(session, tenant)

        custom_rulebooks.remove(session, tenant_id=tenant, key=row.key)

        assert custom_rulebooks.listing(session, tenant_id=tenant) == []

    def test_one_in_use_cannot_be_deleted(self, session, tenant):
        # Deleting it would leave the account resolving to nothing, and an
        # account that resolves to nothing is one the gate waves through.
        row = write(session, tenant)
        challenge_accounts.create(
            session,
            tenant_id=tenant,
            label="RoboForex demo 40k",
            rulebook_key=row.key,
            starting_balance=Decimal("40000"),
            currency_per_r=Decimal("300"),
        )

        with pytest.raises(ValidationFailedError) as raised:
            custom_rulebooks.remove(session, tenant_id=tenant, key=row.key)

        assert "RoboForex demo 40k" in str(raised.value)

    def test_the_refusal_says_what_to_do_instead(self, session, tenant):
        row = write(session, tenant)
        challenge_accounts.create(
            session,
            tenant_id=tenant,
            label="a",
            rulebook_key=row.key,
            starting_balance=Decimal("40000"),
        )

        with pytest.raises(ValidationFailedError) as raised:
            custom_rulebooks.remove(session, tenant_id=tenant, key=row.key)

        assert "Move those accounts" in str(raised.value)

    def test_deleting_something_that_is_not_there_is_not_found(self, session, tenant):
        with pytest.raises(NotFoundError):
            custom_rulebooks.remove(session, tenant_id=tenant, key="custom:ghost")

    def test_the_listing_is_by_name(self, session, tenant):
        write(session, tenant, name="Zebra")
        write(session, tenant, name="Alpha")

        assert [r.name for r in custom_rulebooks.listing(session, tenant_id=tenant)] == [
            "Alpha",
            "Zebra",
        ]


class TestItLooksLikeTheOthersToEveryCaller:
    def test_it_serialises_in_the_shared_shape(self, session, tenant):
        row = write(session, tenant)

        body = custom_rulebooks.to_rulebook(row).as_dict()

        assert set(body) >= {"key", "provider", "profit_target_pct", "source", "retrieved"}

    def test_the_source_says_who_wrote_it(self, session, tenant):
        row = write(session, tenant)

        assert custom_rulebooks.to_rulebook(row).source == custom_rulebooks.SOURCE

    def test_it_carries_no_url_pretending_to_be_a_firms_page(self, session, tenant):
        row = write(session, tenant)

        assert "http" not in custom_rulebooks.to_rulebook(row).source

    def test_the_retrieved_date_is_when_it_was_last_written(self, session, tenant):
        row = write(session, tenant)

        assert custom_rulebooks.to_rulebook(row).retrieved == NOW.date()

    def test_not_imposed_publishes_as_the_word(self, session, tenant):
        # The published shape keeps the three states apart, which is the whole
        # reason the marker is a word rather than an absent key.
        row = write(session, tenant, rules={**ASKED_FOR, "max_trading_days": "not imposed"})

        body = custom_rulebooks.to_rulebook(row).as_dict()

        assert body["max_trading_days"] == "not imposed"

    def test_an_unset_rule_publishes_as_null(self, session, tenant):
        row = write(session, tenant, rules={"profit_target_pct": 0.10})

        assert custom_rulebooks.to_rulebook(row).as_dict()["max_trading_days"] is None

    def test_the_notes_become_the_rulebooks_notes(self, session, tenant):
        row = write(session, tenant, notes="what I actually trade to")

        assert custom_rulebooks.to_rulebook(row).notes == ("what I actually trade to",)

    def test_no_notes_is_an_empty_tuple_not_a_blank_line(self, session, tenant):
        row = write(session, tenant)

        assert custom_rulebooks.to_rulebook(row).notes == ()


def quiet_account(**over) -> ch.ChallengeState:
    base = dict(
        starting_balance=40_000.0,
        current_equity=40_000.0,
        current_balance=40_000.0,
        peak_equity=40_000.0,
        daily_starting_equity=40_000.0,
        daily_profits={},
        days_traded=5,
        open_positions=0,
        current_date=date(2026, 9, 9),
        currency_per_r=300.0,
        current_leverage=0.0,
        in_news_window=False,
        weekend_ahead=False,
        rules_confirmed_by_holder=True,
    )
    base.update(over)
    return ch.ChallengeState(**base)


def _a_different_tenant(session):
    import uuid

    from app.models.tenancy import Tenant

    other = Tenant(name="somebody else", slug=f"other-{uuid.uuid4().hex[:8]}", locale="fa")
    session.add(other)
    session.flush()
    return other.id
