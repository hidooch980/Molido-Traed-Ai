"""Enrolling, checking and recovering the second factor.

`test_totp` proves the arithmetic matches the RFC. These are about the
decisions around it, and most of them exist because the obvious
implementation locks somebody out of their own account:

- a QR scanned into the wrong phone and closed, with no way to prove it
- a recovery code that works twice, or one that never works because it was
  written down with the hyphens the screen showed
- a stolen session removing the factor that was supposed to survive it
- an owner locked out of the dashboard their kill switch is on

The last one is why the roles that need a second factor are the ones that can
reach money, and no others.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.api.deps import AuthenticationError
from app.core import totp
from app.core.enums import UserRole
from app.core.errors import ValidationFailedError
from app.core.security import hash_password
from app.models.recovery_codes import RecoveryCode
from app.models.tenancy import Tenant, User
from app.services import two_factor

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)


@pytest.fixture()
def person(session):
    def make(role: UserRole = UserRole.OWNER) -> User:
        tenant = session.scalar(select(Tenant).limit(1))
        if tenant is None:
            tenant = Tenant(slug="default", name="MolidoTrade")
            session.add(tenant)
            session.flush()
        user = User(
            tenant_id=tenant.id,
            email=f"{role.value}@molido.test",
            display_name=role.value,
            role=role,
            password_hash=hash_password("a-password-nobody-else-knows"),
            is_active=True,
        )
        session.add(user)
        session.flush()
        return user

    return make


def enrol(session, user, *, now=NOW):
    """Take an account all the way through enrolment; return its codes."""
    started = two_factor.begin(session, user)
    code = totp.code_now(started.secret, at=now.timestamp())
    return started, two_factor.confirm(session, user, code, now=now)


class TestWhoMustHaveOne:
    """Forced on an account with nothing to protect, a second factor teaches
    people the whole mechanism is an obstacle - and the accounts that matter
    end up guarded by somebody's irritation."""

    @pytest.mark.parametrize("role", [UserRole.OWNER, UserRole.TRADER])
    def test_the_roles_that_can_reach_money_must(self, role):
        assert two_factor.required_for(role) is True

    @pytest.mark.parametrize("role", [UserRole.VIEWER, UserRole.ANALYST, UserRole.ADMIN])
    def test_the_roles_that_cannot_are_not_forced(self, role):
        assert two_factor.required_for(role) is False

    def test_an_administrator_is_not_forced_because_it_cannot_trade(self):
        """The role table already says admin holds neither EXECUTE nor
        BROKER_MANAGE. This requirement is derived from that rather than
        listed, so a role given EXECUTE tomorrow inherits it."""
        from app.api.deps import ROLE_PERMISSIONS
        from app.core.enums import Permission

        assert Permission.EXECUTE not in ROLE_PERMISSIONS[UserRole.ADMIN]
        assert two_factor.required_for(UserRole.ADMIN) is False


class TestIssuingASecretIsNotEnrolling:
    """A QR somebody scanned into the wrong phone and then closed must not
    lock them out of themselves with no way to prove it."""

    def test_beginning_does_not_enrol(self, session, person):
        user = person()

        two_factor.begin(session, user)

        assert user.totp_secret
        assert user.totp_confirmed_at is None
        assert two_factor.status(session, user).enrolled is False

    def test_an_unconfirmed_secret_blocks_nothing(self, session, person):
        user = person(UserRole.TRADER)
        two_factor.begin(session, user)

        assert two_factor.status(session, user).blocking_sign_in is True
        assert two_factor.status(session, user).started is True

    def test_beginning_again_issues_a_clean_secret(self, session, person):
        """Somebody who abandoned an enrolment halfway should get a fresh QR,
        not one that half-matches whatever is still in their phone."""
        user = person()
        first = two_factor.begin(session, user)
        second = two_factor.begin(session, user)

        assert first.secret != second.secret

    def test_confirming_with_a_wrong_code_does_not_enrol(self, session, person):
        user = person()
        two_factor.begin(session, user)

        with pytest.raises(ValidationFailedError, match="does not match"):
            two_factor.confirm(session, user, "000000", now=NOW)

        assert user.totp_confirmed_at is None

    def test_the_wrong_code_message_points_at_the_clock(self, session, person):
        """A phone more than a minute out produces codes that look right and
        are not, and nobody checks the clock unless told to."""
        user = person()
        two_factor.begin(session, user)

        with pytest.raises(ValidationFailedError, match="clock"):
            two_factor.confirm(session, user, "000000", now=NOW)

    def test_a_correct_code_enrols(self, session, person):
        user = person()
        enrol(session, user)

        assert user.totp_confirmed_at is not None
        assert two_factor.status(session, user).enrolled is True

    def test_a_confirmed_account_cannot_silently_re_enrol(self, session, person):
        """Replacing a working secret should require proving you hold the
        current one."""
        user = person()
        enrol(session, user)

        with pytest.raises(ValidationFailedError, match="already has a second factor"):
            two_factor.begin(session, user)


class TestCheckingACodeAtSignIn:
    def test_a_current_code_passes(self, session, person):
        user = person()
        started, _ = enrol(session, user)
        later = NOW + timedelta(seconds=totp.STEP * 2)

        how = two_factor.check(
            session, user, totp.code_now(started.secret, at=later.timestamp()), now=later
        )

        assert how == "totp"

    def test_a_wrong_code_is_an_authentication_failure(self, session, person):
        """Not a validation error. It is a failed authentication and belongs in
        the same shape as a wrong password."""
        user = person()
        enrol(session, user)

        with pytest.raises(AuthenticationError):
            two_factor.check(session, user, "000000", now=NOW)

    def test_the_same_code_cannot_be_used_twice(self, session, person):
        """A code is valid for its whole window. The second use is the one
        somebody read over a shoulder."""
        user = person()
        started, _ = enrol(session, user)
        later = NOW + timedelta(seconds=totp.STEP * 3)
        code = totp.code_now(started.secret, at=later.timestamp())

        assert two_factor.check(session, user, code, now=later) == "totp"

        with pytest.raises(AuthenticationError):
            two_factor.check(session, user, code, now=later)

    def test_the_next_code_still_works(self, session, person):
        """The replay guard must lock out reuse, not the account."""
        user = person()
        started, _ = enrol(session, user)
        first = NOW + timedelta(seconds=totp.STEP * 3)
        two_factor.check(session, user, totp.code_now(started.secret, at=first.timestamp()), now=first)

        second = first + timedelta(seconds=totp.STEP)
        how = two_factor.check(
            session, user, totp.code_now(started.secret, at=second.timestamp()), now=second
        )

        assert how == "totp"

    def test_an_account_with_no_factor_cannot_be_checked(self, session, person):
        user = person()

        with pytest.raises(AuthenticationError, match="no second factor"):
            two_factor.check(session, user, "123456", now=NOW)


class TestRecoveryCodes:
    def test_confirmation_issues_them(self, session, person):
        user = person()
        _, codes = enrol(session, user)

        assert len(codes) == two_factor.RECOVERY_CODES
        assert two_factor.status(session, user).recovery_codes_left == two_factor.RECOVERY_CODES

    def test_none_exist_before_confirmation(self, session, person):
        """Codes beside a QR that was never scanned are ten strings nobody
        wrote down for a factor that was never turned on."""
        user = person()
        two_factor.begin(session, user)

        assert two_factor.status(session, user).recovery_codes_left == 0

    def test_only_hashes_are_stored(self, session, person):
        user = person()
        _, codes = enrol(session, user)

        stored = " ".join(
            row.code_hash for row in session.scalars(select(RecoveryCode))
        )

        for code in codes:
            assert code not in stored
            assert code.replace("-", "") not in stored

    def test_one_gets_you_in(self, session, person):
        user = person()
        _, codes = enrol(session, user)

        assert two_factor.check(session, user, codes[0], now=NOW) == "recovery"

    def test_it_is_spent_afterwards(self, session, person):
        user = person()
        _, codes = enrol(session, user)
        two_factor.check(session, user, codes[0], now=NOW)

        with pytest.raises(AuthenticationError):
            two_factor.check(session, user, codes[0], now=NOW)

        assert two_factor.status(session, user).recovery_codes_left == two_factor.RECOVERY_CODES - 1

    def test_the_others_still_work(self, session, person):
        user = person()
        _, codes = enrol(session, user)
        two_factor.check(session, user, codes[0], now=NOW)

        assert two_factor.check(session, user, codes[1], now=NOW) == "recovery"

    @pytest.mark.parametrize("mangle", [str.lower, lambda c: c.replace("-", ""), lambda c: f" {c} ", lambda c: c.replace("-", " ")])
    def test_it_is_accepted_however_it_was_written_down(self, session, person, mangle):
        """Typed off paper weeks later, with whatever spacing the person used.
        Refusing a correct code over a hyphen refuses the thing they were told
        to write down."""
        user = person()
        _, codes = enrol(session, user)

        assert two_factor.check(session, user, mangle(codes[0]), now=NOW) == "recovery"

    def test_the_alphabet_has_no_ambiguous_characters(self):
        """These are read off a screen and typed back. "The code is wrong" is
        the least useful thing to tell somebody about their own handwriting."""
        for pair in ("0O", "1I", "1L"):
            present = [ch for ch in pair if ch in two_factor.RECOVERY_ALPHABET]
            assert len(present) <= 1, pair

    def test_reissuing_replaces_the_whole_set(self, session, person):
        """Somebody with three left who is handed seven more cannot tell which
        of the ten on their screen still work."""
        user = person()
        started, codes = enrol(session, user)
        later = NOW + timedelta(seconds=totp.STEP * 4)

        fresh = two_factor.reissue_recovery_codes(
            session, user, totp.code_now(started.secret, at=later.timestamp()), now=later
        )

        assert len(fresh) == two_factor.RECOVERY_CODES
        assert set(fresh).isdisjoint(codes)
        assert two_factor.status(session, user).recovery_codes_left == two_factor.RECOVERY_CODES
        with pytest.raises(AuthenticationError):
            two_factor.check(session, user, codes[0], now=later)

    def test_reissuing_needs_a_current_code(self, session, person):
        user = person()
        enrol(session, user)

        with pytest.raises(AuthenticationError):
            two_factor.reissue_recovery_codes(session, user, "000000", now=NOW)


class TestTurningItOff:
    """A stolen session is exactly what a second factor exists to survive. One
    that could remove the factor would survive nothing."""

    def test_it_needs_a_current_code(self, session, person):
        user = person()
        enrol(session, user)

        with pytest.raises(AuthenticationError):
            two_factor.disable(session, user, "000000", now=NOW)

        assert user.totp_confirmed_at is not None

    def test_a_correct_code_removes_it(self, session, person):
        user = person()
        started, _ = enrol(session, user)
        later = NOW + timedelta(seconds=totp.STEP * 5)

        two_factor.disable(
            session, user, totp.code_now(started.secret, at=later.timestamp()), now=later
        )

        assert user.totp_confirmed_at is None
        assert user.totp_secret is None

    def test_the_recovery_codes_go_with_it(self, session, person):
        """Codes that outlived the factor they recover are a way in that
        nobody remembers exists."""
        user = person()
        started, _ = enrol(session, user)
        later = NOW + timedelta(seconds=totp.STEP * 5)

        two_factor.disable(
            session, user, totp.code_now(started.secret, at=later.timestamp()), now=later
        )

        assert session.scalar(select(RecoveryCode).limit(1)) is None

    def test_a_recovery_code_can_also_turn_it_off(self, session, person):
        """The phone is gone. Being unable to remove a factor you cannot use is
        being locked out with extra steps."""
        user = person()
        _, codes = enrol(session, user)

        two_factor.disable(session, user, codes[0], now=NOW)

        assert user.totp_confirmed_at is None
