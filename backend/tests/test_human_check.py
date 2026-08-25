"""The "I am not a robot" box, without a third party.

What it proves is not humanity - it proves the caller burned processor time.
These are written around the two ways that stops being true: a solution that
can be spent twice, and a challenge that survives a wrong answer so a caller
can grind nonces against it for free.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models.human_checks import HumanChallenge
from app.services import human_check

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)

#: Low enough that solving is instant in a test, high enough that a wrong
#: answer is not accidentally right. Difficulty itself is tested separately.
EASY = 8


def issued(session, *, purpose=human_check.SIGN_IN, failures=0, now=NOW):
    return human_check.issue(session, purpose=purpose, failures=failures, now=now)


class TestAnHonestSolutionPasses:
    def test_a_solved_challenge_verifies(self, session):
        challenge = issued(session)
        nonce = human_check.solve(challenge.salt, challenge.difficulty)

        human_check.verify(
            session,
            challenge_id=challenge.challenge_id,
            nonce=nonce,
            purpose=human_check.SIGN_IN,
            now=NOW,
        )

    def test_the_reference_solver_and_the_verifier_agree(self, session):
        """They live in one module for this reason. A client and a server that
        disagree by one colon produce a login that rejects every correct
        password, and the failure names the password."""
        for difficulty in (4, 8, 12):
            salt = "fixed-salt"
            nonce = human_check.solve(salt, difficulty)

            assert human_check.leading_zero_bits(
                human_check._digest(salt, nonce)
            ) >= difficulty


class TestASolutionIsSpentOnce:
    """The property the whole table exists for. A stateless signed challenge
    would be cheaper and would let an attacker solve once and replay for the
    lifetime of the token."""

    def test_the_same_solution_cannot_be_used_twice(self, session):
        challenge = issued(session)
        nonce = human_check.solve(challenge.salt, challenge.difficulty)
        kwargs = dict(
            challenge_id=challenge.challenge_id,
            nonce=nonce,
            purpose=human_check.SIGN_IN,
            now=NOW,
        )

        human_check.verify(session, **kwargs)

        with pytest.raises(human_check.HumanCheckError, match="used already"):
            human_check.verify(session, **kwargs)

    def test_a_wrong_answer_also_spends_it(self, session):
        """Otherwise a caller grinds nonces against one issued challenge for
        five minutes, which is the same as having no difficulty at all."""
        challenge = issued(session)

        with pytest.raises(human_check.HumanCheckError, match="not solved"):
            human_check.verify(
                session,
                challenge_id=challenge.challenge_id,
                nonce="definitely-wrong",
                purpose=human_check.SIGN_IN,
                now=NOW,
            )

        nonce = human_check.solve(challenge.salt, challenge.difficulty)
        with pytest.raises(human_check.HumanCheckError, match="used already"):
            human_check.verify(
                session,
                challenge_id=challenge.challenge_id,
                nonce=nonce,
                purpose=human_check.SIGN_IN,
                now=NOW,
            )


class TestAChallengeIsBoundToItsForm:
    def test_a_sign_in_proof_cannot_be_spent_on_registration(self, session):
        """Or the cheapest form becomes the mint for every other one."""
        challenge = issued(session, purpose=human_check.SIGN_IN)
        nonce = human_check.solve(challenge.salt, challenge.difficulty)

        with pytest.raises(human_check.HumanCheckError, match="different form"):
            human_check.verify(
                session,
                challenge_id=challenge.challenge_id,
                nonce=nonce,
                purpose=human_check.REGISTER,
                now=NOW,
            )


class TestExpiry:
    def test_a_stale_challenge_is_refused(self, session):
        challenge = issued(session)
        nonce = human_check.solve(challenge.salt, challenge.difficulty)

        with pytest.raises(human_check.HumanCheckError, match="expired"):
            human_check.verify(
                session,
                challenge_id=challenge.challenge_id,
                nonce=nonce,
                purpose=human_check.SIGN_IN,
                now=NOW + human_check.LIFETIME + timedelta(seconds=1),
            )

    def test_pruning_removes_only_the_dead(self, session):
        issued(session, now=NOW - human_check.LIFETIME - timedelta(minutes=1))
        alive = issued(session, now=NOW)

        removed = human_check.prune(session, now=NOW)

        assert removed == 1
        nonce = human_check.solve(alive.salt, alive.difficulty)
        human_check.verify(
            session,
            challenge_id=alive.challenge_id,
            nonce=nonce,
            purpose=human_check.SIGN_IN,
            now=NOW,
        )


class TestMalformedInput:
    @pytest.mark.parametrize(
        "challenge_id, nonce, message",
        [
            (None, 1, "needs a completed human check"),
            (uuid.uuid4(), None, "needs a completed human check"),
            ("not-a-uuid", 1, "not one this server issued"),
            (uuid.uuid4(), 1, "used already"),
        ],
    )
    def test_it_says_which_thing_went_wrong(self, session, challenge_id, nonce, message):
        """Every one of these is a client bug in the ordinary case, and an
        unexplained login failure is worse than a rude one."""
        with pytest.raises(human_check.HumanCheckError, match=message):
            human_check.verify(
                session,
                challenge_id=challenge_id,
                nonce=nonce,
                purpose=human_check.SIGN_IN,
                now=NOW,
            )


class TestTheLadder:
    def test_a_clean_caller_gets_the_cheap_rung(self):
        assert human_check.difficulty_for(0) == human_check.BASE_DIFFICULTY

    def test_it_rises_with_failures(self):
        assert human_check.difficulty_for(6) > human_check.difficulty_for(0)

    def test_it_stops_rising(self):
        """A proof that takes a person ten seconds is a proof they will not
        wait for, and a login nobody can face using gets switched off."""
        assert human_check.difficulty_for(10_000) == human_check.MAX_DIFFICULTY

    def test_the_top_rung_is_still_under_a_second_of_work(self):
        """Roughly a million hashes. Stated as an assertion rather than a
        comment so raising MAX_DIFFICULTY has to be a deliberate act."""
        assert human_check.MAX_DIFFICULTY <= 22

    def test_the_challenge_carries_its_own_difficulty(self, session):
        """Read from the row at verify time, not from the module. Raising the
        setting must not invalidate every challenge already in flight."""
        challenge = issued(session, failures=0)
        human_check.BASE_DIFFICULTY, original = 30, human_check.BASE_DIFFICULTY
        try:
            nonce = human_check.solve(challenge.salt, challenge.difficulty)
            human_check.verify(
                session,
                challenge_id=challenge.challenge_id,
                nonce=nonce,
                purpose=human_check.SIGN_IN,
                now=NOW,
            )
        finally:
            human_check.BASE_DIFFICULTY = original


class TestCountingZeroBits:
    @pytest.mark.parametrize(
        "digest, expected",
        [
            (bytes([0xFF]), 0),
            (bytes([0x7F]), 1),
            (bytes([0x01]), 7),
            (bytes([0x00, 0xFF]), 8),
            (bytes([0x00, 0x00, 0x80]), 16),
            (bytes([0x00, 0x00]), 16),
        ],
    )
    def test_it_counts_bits_not_characters(self, digest, expected):
        """Bits, so difficulty can double instead of multiplying by sixteen.
        A ladder whose only step is 16x has one usable rung."""
        assert human_check.leading_zero_bits(digest) == expected


class TestTheBrowserAndTheServerHashTheSameString:
    """The failure this guards against has no good symptom.

    The proof is found in `frontend/src/lib/humanCheck.ts` and checked here. If
    the two sides ever disagree about what is hashed - one colon, one order of
    concatenation - every correct password is rejected with a message about the
    human check, and nothing in either codebase looks wrong.

    The vectors below were produced by the browser implementation and are
    asserted against this one. They are constants on purpose: a test that
    called the Python solver for both halves would agree with itself forever.
    """

    #: (salt, difficulty, nonce) - the output of the TypeScript solver, run
    #: and copied here rather than guessed. A vector nobody measured proves
    #: nothing about a second implementation.
    VECTORS = [
        ("test-salt", 16, 10177),
        ("test-salt", 12, 281),
        ("fixed-salt", 8, 62),
        ("molido-shop", 18, 43973),
        ("a", 4, 0),
    ]

    @pytest.mark.parametrize("salt, difficulty, nonce", VECTORS)
    def test_a_nonce_found_in_the_browser_verifies_here(self, salt, difficulty, nonce):
        assert human_check.leading_zero_bits(human_check._digest(salt, nonce)) >= difficulty

    @pytest.mark.parametrize("salt, difficulty, nonce", VECTORS)
    def test_both_solvers_find_the_same_first_nonce(self, salt, difficulty, nonce):
        """Both search upward from zero, so the first answer is the same one.
        This is what catches a difficulty comparison that drifted by a bit."""
        assert human_check.solve(salt, difficulty) == nonce

    @pytest.mark.parametrize("salt, difficulty, nonce", VECTORS)
    def test_such_a_nonce_is_accepted_by_the_endpoint_path(self, session, salt, difficulty, nonce):
        """Not just the arithmetic - the whole verify, including spending.

        The issued challenge's salt is overwritten with the vector's, because
        a real salt is random and a fixed vector needs a fixed one."""
        challenge = human_check.issue(session, purpose=human_check.SIGN_IN, now=NOW)
        row = session.get(HumanChallenge, challenge.challenge_id)
        assert row is not None
        row.salt, row.difficulty = salt, difficulty
        session.flush()

        human_check.verify(
            session,
            challenge_id=challenge.challenge_id,
            nonce=nonce,
            purpose=human_check.SIGN_IN,
            now=NOW,
        )
