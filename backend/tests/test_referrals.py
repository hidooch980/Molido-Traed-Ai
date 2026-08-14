"""Referral codes, and the one question the design turns on.

What stops a referrer from registering their own downline and collecting? The
answer here is that points are paid on verification and never on registration -
registering costs nothing and proves nothing, which is exactly what makes it
worth faking a hundred times. Most of this file is that rule, stated from
several directions so it cannot be quietly removed.

None of it makes the system abuse-proof. Somebody with a hundred real inboxes
can still farm it. It makes abuse cost something, which is the honest goal, and
these tests hold that cost in place.
"""

from __future__ import annotations

import pytest

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.models.tenancy import User
from app.services import referrals, verification
from app.services import users as user_service

GOOD_PASSWORD = "a long enough phrase"
OTHER_PASSWORD = "another long phrase"


@pytest.fixture()
def owner(session):
    created = user_service.claim(session, email="owner@example.com", password=GOOD_PASSWORD)
    session.flush()
    return session.get(User, created.id)


def register(session, email, code=None):
    created = user_service.register(
        session, email=email, password=OTHER_PASSWORD, referral_code=code
    )
    session.flush()
    return session.get(User, created.id)


class TestTheCode:
    def test_every_account_gets_one(self, session, owner):
        code = referrals.ensure_code(session, owner)

        assert len(code) == referrals.CODE_LENGTH

    def test_it_avoids_the_characters_people_confuse(self, session, owner):
        """A code exists to be read aloud and typed by somebody else, and O/0
        and I/1/l are the pairs that get it wrong."""
        code = referrals.ensure_code(session, owner)

        assert not set(code) & set("O0I1L")

    def test_asking_twice_gives_the_same_code(self, session, owner):
        """A code that changes is a code somebody already shared and that now
        credits nobody."""
        assert referrals.ensure_code(session, owner) == referrals.ensure_code(session, owner)

    def test_a_new_registration_gets_its_own(self, session, owner):
        """Otherwise only the first account can invite anybody."""
        joiner = register(session, "joiner@example.com")

        assert joiner.referral_code
        assert joiner.referral_code != owner.referral_code


class TestResolvingACode:
    def test_it_is_matched_case_and_dash_insensitively(self, session, owner):
        """People retype these from a message, a screenshot or out loud."""
        code = referrals.ensure_code(session, owner)

        assert referrals.resolve_code(session, code.lower()).id == owner.id
        assert referrals.resolve_code(session, f" {code[:4]}-{code[4:]} ").id == owner.id

    def test_an_unknown_code_is_refused_not_ignored(self, session, owner):
        """Silently dropping it means somebody registers believing their friend
        was credited, and nobody finds out until the friend asks."""
        with pytest.raises(NotFoundError):
            referrals.resolve_code(session, "ZZZZZZZZ")

    def test_registering_with_a_bad_code_fails_the_registration(self, session, owner):
        """The account must not exist afterwards with no referrer attached -
        that is the silent version of the same bug."""
        with pytest.raises(NotFoundError):
            user_service.register(
                session,
                email="joiner@example.com",
                password=OTHER_PASSWORD,
                referral_code="ZZZZZZZZ",
            )

    def test_a_closed_account_cannot_refer(self, session, owner):
        joiner = register(session, "joiner@example.com")
        code = referrals.ensure_code(session, joiner)
        joiner.is_active = False
        session.flush()

        with pytest.raises(ValidationFailedError):
            referrals.resolve_code(session, code)


class TestTheTreeCannotBeGamed:
    def test_an_account_cannot_refer_itself(self, session, owner):
        with pytest.raises(ValidationFailedError):
            referrals.attach(session, owner, owner)

    def test_two_accounts_cannot_refer_each_other(self, session, owner):
        """Not a clever edge case - two people paying each other for nothing."""
        joiner = register(session, "joiner@example.com", referrals.ensure_code(session, owner))

        with pytest.raises(ValidationFailedError):
            referrals.attach(session, owner, joiner)

    def test_a_referrer_cannot_be_changed_afterwards(self, session, owner):
        """A field that can be repointed later stops describing who actually
        introduced whom."""
        joiner = register(session, "joiner@example.com", referrals.ensure_code(session, owner))
        third = register(session, "third@example.com")

        with pytest.raises(ConflictError):
            referrals.attach(session, joiner, third)


class TestPointsArePaidOnVerificationNotRegistration:
    """The rule the whole design rests on. If any of these ever passes with the
    payment moved to registration, the system is a machine for printing points
    and this file is the only thing that would have said so."""

    def test_registering_pays_nobody(self, session, owner):
        before = owner.points or 0

        register(session, "joiner@example.com", referrals.ensure_code(session, owner))

        assert (owner.points or 0) == before

    def test_verifying_pays_the_referrer(self, session, owner):
        joiner = register(session, "joiner@example.com", referrals.ensure_code(session, owner))
        before = owner.points or 0

        referrals.confirm(session, joiner)

        assert (owner.points or 0) == before + referrals.POINTS_PER_CONFIRMED_REFERRAL

    def test_verifying_pays_the_new_account_too(self, session, owner):
        """Paid whether or not anybody referred them - tying the only reward to
        arriving through a referral quietly punishes people who found the site
        by themselves."""
        alone = register(session, "alone@example.com")

        referrals.confirm(session, alone)

        assert alone.points == referrals.POINTS_FOR_VERIFYING

    def test_confirming_twice_pays_once(self, session, owner):
        """A link clicked twice, or a retry after a timeout, must not pay
        twice. The stamp is the guard, not the caller's good intentions."""
        joiner = register(session, "joiner@example.com", referrals.ensure_code(session, owner))
        referrals.confirm(session, joiner)
        after_first = owner.points

        second = referrals.confirm(session, joiner)

        assert second["already"] is True
        assert owner.points == after_first

    def test_a_closed_referrer_earns_nothing(self, session, owner):
        """Paying a closed account is a balance nobody can spend and a number
        that makes the totals wrong."""
        joiner = register(session, "joiner@example.com", referrals.ensure_code(session, owner))
        owner.is_active = False
        session.flush()

        result = referrals.confirm(session, joiner)

        assert result["awarded_to_referrer"] == 0


class TestStanding:
    def test_it_counts_invited_and_confirmed_separately(self, session, owner):
        code = referrals.ensure_code(session, owner)
        one = register(session, "one@example.com", code)
        register(session, "two@example.com", code)
        referrals.confirm(session, one)

        standing = referrals.standing(session, owner.id)

        assert standing.invited_total == 2
        assert standing.invited_confirmed == 1
        assert standing.as_dict()["invited"]["awaiting_verification"] == 1

    def test_it_shows_the_referrers_code_not_their_address(self, session, owner):
        """A downline must not be a way to read the email of the person above
        you."""
        code = referrals.ensure_code(session, owner)
        joiner = register(session, "joiner@example.com", code)

        standing = referrals.standing(session, joiner.id)

        assert standing.referred_by == code
        assert "owner@example.com" not in str(standing.as_dict())


class TestVerificationTokens:
    def test_a_token_verifies_and_confirms_in_one_step(self, session, owner):
        """Verification is what confirms a referral, and nothing else is."""
        joiner = register(session, "joiner@example.com", referrals.ensure_code(session, owner))
        issued = verification.issue(session, joiner)

        redeemed = verification.redeem(session, issued.token)
        verification.mark_verified(session, redeemed)
        referrals.confirm(session, redeemed)

        assert redeemed.id == joiner.id
        assert joiner.email_verified_at is not None
        assert joiner.referral_confirmed_at is not None

    def test_a_token_works_once(self, session, owner):
        joiner = register(session, "joiner@example.com")
        issued = verification.issue(session, joiner)
        verification.redeem(session, issued.token)

        with pytest.raises(ValidationFailedError):
            verification.redeem(session, issued.token)

    def test_asking_for_a_new_link_burns_the_old_one(self, session, owner):
        """Somebody asks for a second link because the first did not arrive or
        was seen by the wrong person. Leaving five working links in five inboxes
        is the opposite of what they asked for."""
        joiner = register(session, "joiner@example.com")
        first = verification.issue(session, joiner)
        verification.issue(session, joiner)

        with pytest.raises(ValidationFailedError):
            verification.redeem(session, first.token)

    def test_an_expired_token_is_refused(self, session, owner):
        from datetime import timedelta

        joiner = register(session, "joiner@example.com")
        issued = verification.issue(session, joiner)

        with pytest.raises(ValidationFailedError):
            verification.redeem(
                session,
                issued.token,
                now=issued.expires_at + timedelta(seconds=1),
            )

    def test_a_token_for_one_purpose_does_not_work_for_another(self, session, owner):
        """A verification token that also resets a password is a verification
        link that takes over an account."""
        joiner = register(session, "joiner@example.com")
        issued = verification.issue(session, joiner, purpose=verification.VERIFY_EMAIL)

        with pytest.raises(ValidationFailedError):
            verification.redeem(session, issued.token, purpose="reset_password")

    def test_the_clear_token_is_never_stored(self, session, owner):
        """This is the table an email address is joined to, which makes it the
        first one an attacker reads. A leaked database must not hand out working
        links."""
        from sqlalchemy import select

        from app.models.tenancy import AccountToken

        joiner = register(session, "joiner@example.com")
        issued = verification.issue(session, joiner)

        rows = session.scalars(select(AccountToken)).all()

        assert rows
        assert all(issued.token != row.token_hash for row in rows)
        assert all(issued.token not in str(row.token_hash) for row in rows)

    def test_the_payload_carries_no_working_link(self, session, owner):
        """Anything that serialises this - a log line, an API response, an error
        report - must not contain a token that still works."""
        joiner = register(session, "joiner@example.com")
        issued = verification.issue(session, joiner)

        assert issued.token not in str(issued.as_dict())

    def test_the_refusal_does_not_say_which_way_it_failed(self, session, owner):
        """Telling somebody holding a token whether it expired or was already
        spent describes the state of an account they may not own."""
        joiner = register(session, "joiner@example.com")
        issued = verification.issue(session, joiner)
        verification.redeem(session, issued.token)

        with pytest.raises(ValidationFailedError) as spent:
            verification.redeem(session, issued.token)
        with pytest.raises(ValidationFailedError) as unknown:
            verification.redeem(session, "totally-made-up-token-value")

        assert str(spent.value) == str(unknown.value)


class TestUnconfiguredMailIsStatedNotSilent:
    def test_no_relay_reports_a_reason(self):
        from app.integrations import email

        ready, reason = email.configured()

        assert ready is False
        assert "cannot send mail" in reason

    def test_sending_without_a_relay_reports_failure_rather_than_success(self):
        """A verification flow that reports success for a message nobody
        receives is worse than one that reports nothing, because the person who
        could fix it never learns there is something to fix."""
        from app.integrations import email

        result = email.send(to="somebody@example.com", subject="x", body="y")

        assert result.sent is False
        assert result.reason
