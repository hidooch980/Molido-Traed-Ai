"""Password hashing and API-key handling (spec §52).

Two rules that are cheap here and expensive to retrofit.

**A plaintext secret never leaves this module.** Passwords are hashed on the
way in and compared by hash; API keys are generated once, shown once, and
stored only as a hash plus a non-secret prefix for display. If a database dump
leaks, it must not contain anything usable.

**Comparison is constant-time.** A naive `==` on a token leaks its length and
its matching prefix through timing, which is enough to recover a key given
patience. `secrets.compare_digest` is the same one-liner without the hole.

The hash is PBKDF2-HMAC-SHA256 from the standard library rather than bcrypt or
argon2, which are stronger but are C extensions. That is a deliberate,
documented trade: this deployment has no password-cracking threat model yet
(there is one operator), and adding a build dependency to the container for a
marginal gain is not worth the deployment fragility. The iteration count is
tuned high and the format is versioned, so moving to argon2 later is a
migration, not a rewrite.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

PBKDF2_ITERATIONS = 480_000
SALT_BYTES = 16
KEY_PREFIX = "molido_"
KEY_PREFIX_DISPLAY_LEN = 12


def hash_password(password: str) -> str:
    """Return a self-describing hash: `pbkdf2$<iterations>$<salt>$<hash>`.

    The parameters travel with the hash so an old password still verifies
    after the iteration count is raised.
    """
    if not password:
        raise ValueError("password must not be empty")
    salt = secrets.token_bytes(SALT_BYTES)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return "$".join(
        [
            "pbkdf2",
            str(PBKDF2_ITERATIONS),
            base64.b64encode(salt).decode(),
            base64.b64encode(derived).decode(),
        ]
    )


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-time verification.

    Returns False rather than raising for a malformed or absent hash: an
    account with no password must fail authentication, not crash the login
    endpoint and reveal that the account exists.
    """
    if not password or not stored:
        return False
    try:
        scheme, iterations, salt_b64, hash_b64 = stored.split("$")
        if scheme != "pbkdf2":
            return False
        derived = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode(),
            base64.b64decode(salt_b64),
            int(iterations),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(derived, base64.b64decode(hash_b64))


def generate_api_key() -> tuple[str, str, str]:
    """Create a new key. Returns `(full_key, prefix, hash)`.

    The full key is returned exactly once, to be shown to the operator and then
    forgotten. Only the prefix and hash are ever stored, so a database leak
    yields nothing that can authenticate.
    """
    raw = KEY_PREFIX + secrets.token_urlsafe(32)
    return raw, raw[:KEY_PREFIX_DISPLAY_LEN], hash_api_key(raw)


def hash_api_key(raw: str) -> str:
    """Plain SHA-256, no salt — deliberately different from passwords.

    An API key is 256 bits of machine-generated randomness, so it has no
    dictionary to attack and a per-key salt would buy nothing. It would,
    however, make lookup impossible: verification has to find the row *by*
    hash, and a salted scheme would force a full table scan on every request.
    """
    return hashlib.sha256(raw.encode()).hexdigest()


def api_key_matches(raw: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_api_key(raw), stored_hash)
