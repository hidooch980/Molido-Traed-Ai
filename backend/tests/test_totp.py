"""Time-based one-time passwords, checked against the RFC's own numbers.

A hand-written TOTP that is subtly wrong does not fail loudly. It produces
codes no authenticator app agrees with, and every user experiences that as
"the app says 481920 and the site says it is wrong" - which sends them to
check their phone's clock, their app, and their typing, in that order, and
never to the server.

So the first class here is the published test vectors from RFC 4226 Appendix D
and RFC 6238 Appendix B. If those pass, the algorithm is the one Google
Authenticator implements. If they fail, nothing else in this file matters.

The rest are about the two ways a correct algorithm still makes a weak second
factor: a window wide enough that a shoulder-surfed code stays usable, and a
missing replay check that lets one code be spent twice.
"""

from __future__ import annotations

import base64

import pytest

from app.core import totp

#: RFC 4226 Appendix D and RFC 6238 Appendix B both use this secret: the ASCII
#: digits "12345678901234567890", base32-encoded.
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode("ascii").rstrip("=")


class TestItMatchesTheRFC:
    """Published vectors. Everything else is downstream of these."""

    @pytest.mark.parametrize(
        "counter, expected",
        [
            (0, "755224"), (1, "287082"), (2, "359152"), (3, "969429"), (4, "338314"),
            (5, "254676"), (6, "287922"), (7, "162583"), (8, "399871"), (9, "520489"),
        ],
    )
    def test_rfc_4226_appendix_d(self, counter, expected):
        assert totp._code_at(RFC_SECRET, counter) == expected

    @pytest.mark.parametrize(
        "timestamp, expected",
        [
            (59, "287082"),
            (1111111109, "081804"),
            (1111111111, "050471"),
            (1234567890, "005924"),
            (2000000000, "279037"),
        ],
    )
    def test_rfc_6238_appendix_b_sha1(self, timestamp, expected):
        """The RFC prints eight digits; six-digit codes are the last six."""
        assert totp.code_now(RFC_SECRET, at=timestamp) == expected

    def test_it_uses_sha1_on_purpose(self):
        """Not an oversight. Every authenticator app implements RFC 6238's
        SHA-1 default and several ignore the algorithm parameter entirely, so a
        server that "upgraded" would produce codes those apps cannot generate -
        and the failure looks like the user typing the wrong number."""
        assert "algorithm=SHA1" in totp.enrolment_uri(RFC_SECRET, account="a", issuer="b")


class TestVerification:
    def test_the_current_code_verifies(self):
        secret = totp.generate_secret()
        code = totp.code_now(secret, at=1_800_000_000)

        assert totp.verify(secret, code, at=1_800_000_000) is not None

    def test_a_wrong_code_does_not(self):
        secret = totp.generate_secret()

        assert totp.verify(secret, "000000", at=1_800_000_000) is None

    @pytest.mark.parametrize("junk", ["", "12345", "1234567", "abcdef", None, "12 34 56"])
    def test_malformed_input_is_refused_without_raising(self, junk):
        """Typed by a person into a phone-shaped field. Every shape of nonsense
        has to come back as "no" rather than as a 500."""
        secret = totp.generate_secret()

        assert totp.verify(secret, junk, at=1_800_000_000) is None

    def test_spaces_and_separators_are_tolerated(self):
        """Several apps display the code as "481 920". Refusing that is
        refusing what the user was shown."""
        secret = totp.generate_secret()
        code = totp.code_now(secret, at=1_800_000_000)
        spaced = f"{code[:3]} {code[3:]}"

        assert totp.verify(secret, spaced, at=1_800_000_000) is not None


class TestTheWindow:
    """One step either side. Zero rejects a phone two seconds slow, which is
    most phones; five accepts a code photographed two minutes ago."""

    def test_a_code_from_the_previous_step_still_works(self):
        secret = totp.generate_secret()
        code = totp.code_now(secret, at=1_800_000_000)

        assert totp.verify(secret, code, at=1_800_000_000 + totp.STEP) is not None

    def test_a_code_from_the_next_step_works_too(self):
        """Clock drift runs both ways."""
        secret = totp.generate_secret()
        code = totp.code_now(secret, at=1_800_000_000 + totp.STEP)

        assert totp.verify(secret, code, at=1_800_000_000) is not None

    def test_a_code_two_steps_old_does_not(self):
        secret = totp.generate_secret()
        code = totp.code_now(secret, at=1_800_000_000)

        assert totp.verify(secret, code, at=1_800_000_000 + 2 * totp.STEP) is None

    def test_the_window_stays_narrow(self):
        """Asserted as a number so widening it has to be a deliberate edit.
        Each extra step is another 30 seconds a stolen code keeps working."""
        assert totp.WINDOW == 1


class TestReplayIsRefusable:
    """A code is valid for its whole window, so without recording which step
    was spent, the same six digits work twice. `verify` returns the step so the
    caller can store it - a caller that ignores the return value has built a
    second factor that can be replayed for a minute."""

    def test_verify_reports_which_step_matched(self):
        secret = totp.generate_secret()
        at = 1_800_000_000
        code = totp.code_now(secret, at=at)

        assert totp.verify(secret, code, at=at) == at // totp.STEP

    def test_a_spent_step_is_refused(self):
        secret = totp.generate_secret()
        at = 1_800_000_000
        code = totp.code_now(secret, at=at)
        step = totp.verify(secret, code, at=at)

        assert totp.verify(secret, code, at=at, last_step=step) is None

    def test_an_older_step_is_refused_too(self):
        """Not just the exact step spent. A code from before it is older, and
        accepting it would reopen the window the replay check just closed."""
        secret = totp.generate_secret()
        at = 1_800_000_000
        old = totp.code_now(secret, at=at - totp.STEP)

        assert totp.verify(secret, old, at=at, last_step=at // totp.STEP) is None

    def test_the_next_code_still_works_after_one_is_spent(self):
        """The replay check must not lock the account out of its own second
        factor - only out of reusing one code."""
        secret = totp.generate_secret()
        at = 1_800_000_000
        spent = totp.verify(secret, totp.code_now(secret, at=at), at=at)
        later = at + totp.STEP

        assert totp.verify(secret, totp.code_now(secret, at=later), at=later, last_step=spent)


class TestSecrets:
    def test_two_secrets_are_never_the_same(self):
        assert len({totp.generate_secret() for _ in range(200)}) == 200

    def test_it_is_long_enough_to_be_unguessable(self):
        secret = totp.generate_secret()
        padded = secret + "=" * (-len(secret) % 8)

        assert len(base64.b32decode(padded)) == totp.SECRET_BYTES
        assert totp.SECRET_BYTES >= 20

    def test_it_carries_no_padding(self):
        """`=` is legal base32 and is rejected or mangled by several apps'
        manual-entry fields, which produces an account that enrols and then
        never verifies."""
        assert "=" not in totp.generate_secret()

    def test_it_is_readable_when_typed_by_hand(self):
        """An unbroken 32-character string produces transcription errors that
        surface as "the code is wrong" - the message that sends somebody
        looking at everything except the thing that is wrong."""
        grouped = totp.grouped("ABCDEFGHIJKLMNOP")

        assert grouped == "ABCD EFGH IJKL MNOP"
        assert grouped.replace(" ", "") == "ABCDEFGHIJKLMNOP"


class TestTheEnrolmentURI:
    def test_an_app_can_read_it(self):
        uri = totp.enrolment_uri("ABC234", account="owner@molido.shop", issuer="MolidoTrade")

        assert uri.startswith("otpauth://totp/")
        assert "secret=ABC234" in uri
        assert "digits=6" in uri
        assert "period=30" in uri

    def test_the_issuer_appears_twice(self):
        """Apps disagree about which one they read, and one that finds neither
        files the account under a blank name. Three unlabelled entries and the
        user picks wrong at the worst moment."""
        uri = totp.enrolment_uri("ABC234", account="a@b.c", issuer="MolidoTrade")

        assert uri.count("MolidoTrade") == 2

    def test_an_address_with_awkward_characters_survives(self):
        uri = totp.enrolment_uri("S", account="a+b@molido.shop", issuer="Molido Trade")

        assert " " not in uri
        assert "%20" in uri or "+" in uri
