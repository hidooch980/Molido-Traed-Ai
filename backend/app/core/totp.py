"""Time-based one-time passwords, RFC 6238 (spec §52).

A password is a secret that travels. It is typed into a phone on a hotel wifi,
saved in a browser on a shared laptop, reused on a forum that gets breached,
and once it has leaked there is nothing between whoever holds it and an account
that can connect a broker. This is the second factor: a six-digit code derived
from a shared secret and the current half-minute, which is worthless thirty
seconds after it is read over somebody's shoulder.

**Standard library only.** HMAC-SHA1 and base32 are both in it, and the whole
algorithm is forty lines. Adding `pyotp` would put a dependency in the
authentication path for code that is easier to read than the import line, and
this deployment already chose PBKDF2 from the standard library over a C
extension for the same reason.

**SHA-1 here is not a mistake.** RFC 6238's default is HMAC-SHA1, and every
authenticator app - Google Authenticator, Aegis, 1Password, Bitwarden -
implements that default; several ignore the `algorithm` parameter in the
enrolment URI entirely and use SHA-1 whatever it says. A server that "upgraded"
to SHA-256 would produce codes those apps cannot generate, and the failure
looks like a user typing the wrong number. HMAC's security does not rest on
collision resistance, which is what is broken in SHA-1, and the secret is 160
bits of randomness rather than anything guessable.

**A window of one step, not zero and not five.** Zero rejects a phone whose
clock is two seconds slow, which is most phones. Five accepts a code somebody
photographed two minutes ago. One step either side accepts a ninety-second
span, which covers ordinary clock drift and typing speed.

**Replay is refused above this module.** A correct code stays correct for its
whole window, so an attacker who reads one over a shoulder can use it - unless
the last accepted step is recorded and never accepted twice. `verify` reports
which step matched so the caller can store it; a caller that ignores that
return value has built a second factor that can be replayed for a minute.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
from urllib.parse import quote

#: Seconds per code. RFC 6238's default and what every authenticator assumes.
STEP = 30

#: Digits per code. Six, for the same reason.
DIGITS = 6

#: How many steps either side of now are accepted. See the module docstring:
#: one covers ordinary clock drift; more turns a shoulder-surfed code into a
#: usable credential for minutes.
WINDOW = 1

#: Bytes of secret. 20 is the SHA-1 block-friendly size RFC 4226 specifies and
#: what authenticator apps expect; 160 bits is far beyond guessable.
SECRET_BYTES = 20


def generate_secret() -> str:
    """A fresh base32 secret, in the form an authenticator app reads.

    Base32 without padding: the `=` characters are legal in the encoding and
    are rejected or silently mangled by several apps' manual-entry fields,
    which produces an account that enrols and then never verifies.
    """
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode("ascii").rstrip("=")


def _code_at(secret: str, step: int) -> str:
    """The code for one 30-second step. RFC 4226 dynamic truncation."""
    # Padding restored for decoding; apps are given the stripped form and hand
    # it back the same way, so this has to tolerate both.
    padded = secret.strip().replace(" ", "").upper()
    padded += "=" * (-len(padded) % 8)
    key = base64.b32decode(padded, casefold=True)

    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(truncated % (10**DIGITS)).zfill(DIGITS)


def code_now(secret: str, *, at: float) -> str:
    """The code a correctly-set authenticator is showing at `at`.

    `at` is a required unix timestamp rather than a call to `time.time()`. A
    module that reads the clock itself cannot be tested at a step boundary, and
    the step boundary is where every off-by-one in this file would live.
    """
    return _code_at(secret, int(at) // STEP)


def verify(secret: str, code: str, *, at: float, last_step: int | None = None) -> int | None:
    """Check a code. Returns the step it matched, or None.

    The step is returned rather than a boolean because the caller **must**
    store it: a code is valid for its whole window, so without recording which
    step was spent, the same six digits work twice. `last_step` refuses
    anything at or below what has already been accepted.

    Comparison is constant-time. A naive `==` leaks how many leading digits
    were right through timing, and six digits is a small enough space that the
    leak is worth something.
    """
    cleaned = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(cleaned) != DIGITS:
        return None

    now_step = int(at) // STEP
    for offset in range(-WINDOW, WINDOW + 1):
        step = now_step + offset
        if last_step is not None and step <= last_step:
            # Already spent, or older than something already spent. Skipped
            # rather than compared, so a replayed code cannot even be timed.
            continue
        if hmac.compare_digest(_code_at(secret, step), cleaned):
            return step
    return None


def enrolment_uri(secret: str, *, account: str, issuer: str) -> str:
    """The `otpauth://` URI an authenticator app scans.

    Both `issuer` parameters are supplied - the label prefix and the query
    parameter - because apps disagree about which they read, and one that finds
    neither files the account under a blank name. A user with three unlabelled
    entries cannot tell which is which, and picks wrong at the worst moment.
    """
    label = quote(f"{issuer}:{account}", safe="")
    return (
        f"otpauth://totp/{label}"
        f"?secret={secret}"
        f"&issuer={quote(issuer, safe='')}"
        f"&algorithm=SHA1"
        f"&digits={DIGITS}"
        f"&period={STEP}"
    )


def grouped(secret: str, *, per_group: int = 4) -> str:
    """The secret in readable groups, for the people who cannot scan.

    Typed by hand off a screen, an unbroken 32-character string produces
    transcription errors that surface as "the code is wrong" - the one error
    message that sends somebody looking at the wrong thing.
    """
    return " ".join(secret[i : i + per_group] for i in range(0, len(secret), per_group))
