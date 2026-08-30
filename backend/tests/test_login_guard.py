"""What stands between a password guess and the next one.

Nothing did. One password per request, the same refusal for every kind of
failure, and the next request accepted immediately - an address and a wordlist
were the whole attack.

The rule these are mostly written around is the one that is easy to get
backwards: **the account holder must not be lockable out of their own kill
switch**. An attacker who cannot guess the password can still fail on purpose,
and if failing on purpose buys an hour of the owner being unable to sign in,
the guard has become the attack. So the subject ladder is capped short and the
long one is on the caller's address, where being wrong costs a change of
network.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.services import login_guard

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
WHO = "owner@example.test"
WHERE = "203.0.113.7"


def fail(session, *, email=WHO, address=WHERE, at=NOW, times=1):
    for step in range(times):
        login_guard.record(
            session,
            email=email,
            address=address,
            succeeded=False,
            reason="wrong password",
            now=at + timedelta(seconds=step),
        )


class TestAFreshCallerIsNotObstructed:
    def test_the_first_attempt_is_allowed(self, session):
        verdict = login_guard.check(session, email=WHO, address=WHERE, now=NOW)

        assert verdict.allowed
        assert verdict.retry_after is None
        assert not verdict.human_check_required

    def test_enforce_returns_rather_than_raises(self, session):
        assert login_guard.enforce(session, email=WHO, address=WHERE, now=NOW).allowed


class TestTheProofOfWorkComesBeforeTheWait:
    """Asking for a proof of work is cheap for a person and expensive for a
    loop, so it is asked well before anybody is made to wait."""

    def test_it_is_required_before_any_cooldown(self, session):
        fail(session, times=login_guard.HUMAN_CHECK_AFTER)

        verdict = login_guard.check(session, email=WHO, address=WHERE, now=NOW)

        assert verdict.human_check_required
        assert verdict.allowed, "asking for proof is not the same as refusing"

    def test_it_is_not_required_before_that(self, session):
        fail(session, times=login_guard.HUMAN_CHECK_AFTER - 1)

        assert not login_guard.check(
            session, email=WHO, address=WHERE, now=NOW
        ).human_check_required


class TestTheSubjectLadder:
    def test_the_threshold_is_where_waiting_starts(self, session):
        fail(session, times=login_guard.SUBJECT_THRESHOLD - 1)
        assert login_guard.check(session, email=WHO, address=None, now=NOW).allowed

        fail(session, times=1, at=NOW + timedelta(seconds=10))
        assert not login_guard.check(
            session, email=WHO, address=None, now=NOW + timedelta(seconds=11)
        ).allowed

    def test_the_wait_doubles(self, session):
        first = login_guard._cooldown(
            login_guard.SUBJECT_THRESHOLD, login_guard.SUBJECT_THRESHOLD, timedelta(days=1)
        )
        second = login_guard._cooldown(
            login_guard.SUBJECT_THRESHOLD + 1,
            login_guard.SUBJECT_THRESHOLD,
            timedelta(days=1),
        )

        assert second == first * 2

    def test_the_wait_is_capped_short(self, session):
        """The load-bearing assertion of this module. Twenty failures must not
        buy an attacker an hour of the owner being locked out of the dashboard
        the kill switch lives on."""
        enormous = login_guard._cooldown(
            200, login_guard.SUBJECT_THRESHOLD, login_guard.SUBJECT_MAX_COOLDOWN
        )

        assert enormous == login_guard.SUBJECT_MAX_COOLDOWN
        assert login_guard.SUBJECT_MAX_COOLDOWN <= timedelta(minutes=15)

    def test_the_cooldown_expires(self, session):
        fail(session, times=login_guard.SUBJECT_THRESHOLD)
        later = NOW + login_guard.SUBJECT_MAX_COOLDOWN + timedelta(seconds=1)

        assert login_guard.check(session, email=WHO, address=None, now=later).allowed

    def test_failures_outside_the_window_do_not_count(self, session):
        fail(session, times=login_guard.SUBJECT_THRESHOLD * 3)
        long_after = NOW + login_guard.WINDOW + timedelta(minutes=1)

        verdict = login_guard.check(session, email=WHO, address=None, now=long_after)

        assert verdict.allowed
        assert verdict.subject_failures == 0

    def test_case_and_spacing_do_not_dodge_it(self, session):
        fail(session, times=login_guard.SUBJECT_THRESHOLD)

        verdict = login_guard.check(
            session, email=f"  {WHO.upper()} ", address=None, now=NOW
        )

        assert not verdict.allowed


class TestTheAddressLadder:
    def test_it_tolerates_more_than_the_subject_ladder(self, session):
        """One office or one phone network is legitimately several people
        behind one address."""
        assert login_guard.ADDRESS_THRESHOLD > login_guard.SUBJECT_THRESHOLD

    def test_many_accounts_from_one_place_is_caught(self, session):
        """The shape of enumeration: every attempt names a different account,
        so the subject counter never reaches its threshold."""
        for n in range(login_guard.ADDRESS_THRESHOLD):
            fail(session, email=f"victim{n}@example.test", at=NOW + timedelta(seconds=n))

        verdict = login_guard.check(
            session,
            email="victim999@example.test",
            address=WHERE,
            now=NOW + timedelta(seconds=login_guard.ADDRESS_THRESHOLD),
        )

        assert not verdict.allowed
        assert verdict.subject_failures == 0, "no single account was targeted"
        assert "from this address" in verdict.reason

    def test_it_may_bite_harder_than_the_subject_ladder(self, session):
        assert login_guard.ADDRESS_MAX_COOLDOWN > login_guard.SUBJECT_MAX_COOLDOWN


class TestAnUnknownAddressIsNotOneSharedBucket:
    """A deployment behind a proxy that forwards no address would otherwise
    put every caller in the world into one counter, and the first fifteen
    mistyped passwords anywhere would lock out everybody."""

    def test_attempts_with_no_address_do_not_lock_a_different_caller(self, session):
        for n in range(login_guard.ADDRESS_THRESHOLD * 2):
            fail(session, email=f"x{n}@example.test", address=None, at=NOW + timedelta(seconds=n))

        verdict = login_guard.check(
            session, email="innocent@example.test", address=None, now=NOW
        )

        assert verdict.allowed
        assert verdict.address_failures == 0


class TestSucceedingClearsTheLadder:
    def test_the_next_mistake_starts_from_zero(self, session):
        """Five wrong attempts and then the right one must not leave the
        ladder standing against somebody who has just proved they own the
        account."""
        fail(session, times=login_guard.SUBJECT_THRESHOLD - 1)

        cleared = login_guard.clear(session, email=WHO)

        assert cleared == login_guard.SUBJECT_THRESHOLD - 1
        assert login_guard.check(session, email=WHO, address=None, now=NOW).subject_failures == 0

    def test_it_does_not_clear_somebody_else(self, session):
        fail(session, times=2)
        fail(session, email="other@example.test", times=2)

        login_guard.clear(session, email=WHO)

        assert (
            login_guard.check(
                session, email="other@example.test", address=None, now=NOW
            ).subject_failures
            == 2
        )

    def test_a_success_is_recorded_too(self, session):
        """A table of failures alone cannot answer the question an owner asks
        after a scare: did anybody actually get in?"""
        row = login_guard.record(
            session,
            email=WHO,
            address=WHERE,
            succeeded=True,
            user_id=uuid.uuid4(),
            now=NOW,
        )

        assert row.succeeded
        assert row.user_id is not None


class TestTheRefusalSaysWhenToComeBack:
    def test_enforce_raises_with_a_retry_after(self, session):
        fail(session, times=login_guard.SUBJECT_THRESHOLD)

        with pytest.raises(login_guard.TooManyAttemptsError) as caught:
            login_guard.enforce(session, email=WHO, address=None, now=NOW)

        assert caught.value.http_status == 429
        assert caught.value.context["retry_after_seconds"] > 0

    def test_the_message_does_not_say_whether_the_account_exists(self, session):
        fail(session, times=login_guard.SUBJECT_THRESHOLD)

        with pytest.raises(login_guard.TooManyAttemptsError) as caught:
            login_guard.enforce(session, email=WHO, address=None, now=NOW)

        assert "account" not in caught.value.message.lower()


class TestNothingSecretIsStored:
    def test_the_password_is_nowhere_on_the_row(self, session):
        row = login_guard.record(
            session,
            email=WHO,
            address=WHERE,
            succeeded=False,
            reason="wrong password",
            now=NOW,
        )
        stored = " ".join(str(v) for v in vars(row).values())

        assert "hunter2" not in stored
        # The column set itself, so a password column added later fails here.
        assert not any(
            "password" in column.name for column in row.__table__.columns
        ), [c.name for c in row.__table__.columns]

    def test_a_long_user_agent_is_truncated_rather_than_refused(self, session):
        row = login_guard.record(
            session, email=WHO, address=WHERE, succeeded=False, user_agent="x" * 5000, now=NOW
        )

        assert row.user_agent is not None
        assert len(row.user_agent) == 256


class TestPruning:
    def test_old_attempts_go_and_recent_ones_stay(self, session):
        fail(session, times=1, at=NOW - login_guard.RETENTION - timedelta(days=1))
        fail(session, times=1, at=NOW)

        removed = login_guard.prune(session, now=NOW)

        assert removed == 1
        assert login_guard.check(session, email=WHO, address=None, now=NOW).subject_failures == 1


class TestTheArithmeticCannotRaise:
    """The guard runs on every sign-in. An exception inside it is the door
    jamming for everybody, not one attempt being refused - so the ladder is
    clamped before the doubling rather than after it. `2 ** 200` is a fine
    Python integer and a `timedelta` that refuses to be constructed."""

    @pytest.mark.parametrize("failures", [0, 1, 5, 50, 200, 5_000, 1_000_000])
    def test_no_failure_count_breaks_it(self, session, failures):
        for cap in (login_guard.SUBJECT_MAX_COOLDOWN, login_guard.ADDRESS_MAX_COOLDOWN):
            wait = login_guard._cooldown(failures, login_guard.SUBJECT_THRESHOLD, cap)

            assert wait is None or wait <= cap

    def test_the_clamp_is_above_every_cap_it_has_to_reach(self):
        """So the ladder is bounded by policy, not by the overflow guard."""
        reached = login_guard.BASE_COOLDOWN * (2**login_guard.MAX_DOUBLINGS)

        assert reached > login_guard.ADDRESS_MAX_COOLDOWN
