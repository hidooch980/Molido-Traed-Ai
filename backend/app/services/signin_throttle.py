"""How many sign-in attempts an address and an address's neighbours may make.

The gate itself was already the right shape: one failure message for an
unknown address, a wrong password and a disabled account, so a guess learns
nothing about which half was wrong. What it had no answer for was *volume*.

Two different problems, and a single counter would answer neither well.

**Guessing.** PBKDF2 at 480,000 iterations makes each attempt expensive for
the attacker, which is what it is for. But expensive is not impossible, and a
password that survives ten thousand guesses is a different password from one
that survives ten.

**Cost.** The same 480,000 iterations are spent by *this* server, on its four
cores, before it can answer. Ten concurrent guesses is 4.8 million iterations
of work handed to the box by an unauthenticated caller. That is not primarily
a password problem - it is a way to take the site down, and it costs the
attacker one HTTP request.

So the counter runs *before* the hash rather than after the verdict. A
throttled attempt must cost nothing to refuse, or refusing it is the attack.

**Counted per address, and separately in total.** Per address alone lets
someone spray one guess each across a thousand addresses and never trip it.
A total alone lets one noisy address lock out everyone. Both, and the tighter
one wins.

**A successful sign-in clears that address.** Someone who mistypes twice and
then gets it right is not an attacker, and carrying their failures forward
would lock out the person who just proved who they are.

**Counted in Redis, not in this process.** The API runs under gunicorn with
several uvicorn workers, and a module-level counter in each of them is not one
limit of eight - it is one limit of eight per worker, read from whichever
worker happened to answer. That was the first implementation here and it did
not throttle: ten wrong passwords in a row went through and the snapshot
reported zero failures, because the process being asked was not the process
that had counted.

Not the database either. The window is minutes, a restart clearing it is
acceptable, and a write per failed guess would hand an attacker a way to make
the database do work too. Redis is already a hard dependency of this
deployment and expires keys on its own.

**If Redis cannot be reached it falls back to the per-process counter and
says so.** That fallback is weaker by exactly the number of workers, which is
why the snapshot reports which one is in force - a limiter quietly running at
four times its stated limit is worse than one that is honest about it.
Refusing every sign-in instead would lock the operator out of their own
controls at the moment something is already wrong.
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Any

#: How long failures are remembered. Short enough that a person who forgot
#: their password can try again after a coffee; long enough that grinding
#: through a wordlist is not a matter of waiting a few seconds.
WINDOW = timedelta(minutes=15)

#: Failures from one address before it is refused. Generous for a human -
#: a mistyped password, a wrong saved credential, an old one from a manager -
#: and nowhere near enough to search a password space.
PER_EMAIL = 8

#: Failures from everywhere before every sign-in is refused. This is the
#: availability limit rather than the guessing one: it exists so a spray
#: across many addresses cannot spend the server's cores. Set well above
#: what a handful of real people fumbling their passwords would produce.
GLOBAL = 60


class Throttle:
    """A window of recent failures, per address and in total."""

    def __init__(
        self,
        *,
        window: timedelta = WINDOW,
        per_email: int = PER_EMAIL,
        overall: int = GLOBAL,
    ) -> None:
        self.window = window
        self.per_email = per_email
        self.overall = overall
        self._by_email: dict[str, deque[datetime]] = {}
        self._all: deque[datetime] = deque()
        # The API is called from request threads, and a dict mutated from
        # several at once loses entries - which here means losing failures,
        # so the throttle silently stops throttling.
        self._lock = threading.Lock()

    def _prune(self, now: datetime) -> None:
        cutoff = now - self.window
        while self._all and self._all[0] < cutoff:
            self._all.popleft()
        empty = []
        for email, times in self._by_email.items():
            while times and times[0] < cutoff:
                times.popleft()
            if not times:
                empty.append(email)
        for email in empty:
            del self._by_email[email]

    def check(self, email: str, *, now: datetime | None = None) -> str | None:
        """The reason this attempt is refused, or None to let it through.

        Called before the password is hashed. A throttled attempt that still
        paid for the hash would be the attack rather than the defence.
        """
        moment = now or datetime.now(UTC)
        key = email.strip().lower()
        with self._lock:
            self._prune(moment)
            if len(self._by_email.get(key, ())) >= self.per_email:
                return (
                    f"too many failed sign-ins for this address. Try again in "
                    f"{int(self.window.total_seconds() // 60)} minutes"
                )
            if len(self._all) >= self.overall:
                # Deliberately does not say the limit is global. An attacker
                # learning they have tripped a system-wide limit learns the
                # limit exists and roughly where it is.
                return (
                    "too many failed sign-ins. Try again in "
                    f"{int(self.window.total_seconds() // 60)} minutes"
                )
        return None

    def failed(self, email: str, *, now: datetime | None = None) -> None:
        moment = now or datetime.now(UTC)
        key = email.strip().lower()
        with self._lock:
            self._prune(moment)
            self._by_email.setdefault(key, deque()).append(moment)
            self._all.append(moment)

    def succeeded(self, email: str) -> None:
        """Clear this address. Someone who mistyped twice and then got it
        right is not an attacker, and their failures must not follow them."""
        key = email.strip().lower()
        with self._lock:
            self._by_email.pop(key, None)

    def snapshot(self, *, now: datetime | None = None) -> dict[str, int]:
        moment = now or datetime.now(UTC)
        with self._lock:
            self._prune(moment)
            return {
                "addresses_with_failures": len(self._by_email),
                "failures_in_window": len(self._all),
                "per_email_limit": self.per_email,
                "overall_limit": self.overall,
            }




#: Key prefix for the shared counters. Namespaced so a flush of something
#: else's keys cannot silently disable this.
KEY_PREFIX = "molido:signin"


def _redis():
    """A client, or None if Redis cannot be reached quickly.

    The timeout is short on purpose: this runs on the path of every sign-in,
    and a slow limiter is a slow front door.
    """
    try:
        import redis

        from app.core.config import get_settings

        client = redis.Redis.from_url(
            get_settings().redis_url, socket_connect_timeout=1, socket_timeout=1
        )
        client.ping()
        return client
    except Exception:  # noqa: BLE001 - any failure means "use the fallback"
        return None


class SharedThrottle:
    """The same limits, counted where every worker can see them."""

    def __init__(
        self,
        *,
        window: timedelta = WINDOW,
        per_email: int = PER_EMAIL,
        overall: int = GLOBAL,
    ) -> None:
        self.window = window
        self.per_email = per_email
        self.overall = overall
        #: Used when Redis is unreachable. Weaker by the number of workers,
        #: and the snapshot says which is in force.
        self.fallback = Throttle(window=window, per_email=per_email, overall=overall)

    def _keys(self, email: str) -> tuple[str, str]:
        key = email.strip().lower()
        return f"{KEY_PREFIX}:email:{key}", f"{KEY_PREFIX}:all"

    def check(self, email: str, *, now: datetime | None = None) -> str | None:
        client = _redis()
        if client is None:
            return self.fallback.check(email, now=now)

        minutes = int(self.window.total_seconds() // 60)
        email_key, all_key = self._keys(email)
        try:
            per_address = int(client.get(email_key) or 0)
            everyone = int(client.get(all_key) or 0)
        except Exception:  # noqa: BLE001 - a read that failed is not a zero
            return self.fallback.check(email, now=now)

        if per_address >= self.per_email:
            return (
                "too many failed sign-ins for this address. Try again in "
                f"{minutes} minutes"
            )
        if everyone >= self.overall:
            return f"too many failed sign-ins. Try again in {minutes} minutes"
        return None

    def failed(self, email: str, *, now: datetime | None = None) -> None:
        client = _redis()
        if client is None:
            self.fallback.failed(email, now=now)
            return
        email_key, all_key = self._keys(email)
        seconds = int(self.window.total_seconds())
        try:
            pipe = client.pipeline()
            # INCR then EXPIRE rather than SETEX: the window is from the first
            # failure, so a steady drip of guesses cannot keep pushing the
            # expiry out and stay under the limit forever.
            pipe.incr(email_key)
            pipe.expire(email_key, seconds, nx=True)
            pipe.incr(all_key)
            pipe.expire(all_key, seconds, nx=True)
            pipe.execute()
        except Exception:  # noqa: BLE001
            self.fallback.failed(email, now=now)

    def succeeded(self, email: str) -> None:
        self.fallback.succeeded(email)
        client = _redis()
        if client is None:
            return
        email_key, _ = self._keys(email)
        try:
            client.delete(email_key)
        except Exception:  # noqa: BLE001 - the address stays counted, which
            # is the safe direction: it can only refuse, never allow.
            pass

    def snapshot(self, *, now: datetime | None = None) -> dict[str, Any]:
        client = _redis()
        if client is None:
            return {
                **self.fallback.snapshot(now=now),
                "counted_in": "process",
                "warning": (
                    "Redis is unreachable, so each worker is counting on its "
                    "own - the effective limit is this one times the number "
                    "of workers"
                ),
            }
        try:
            everyone = int(client.get(f"{KEY_PREFIX}:all") or 0)
            addresses = len(list(client.scan_iter(f"{KEY_PREFIX}:email:*", count=200)))
        except Exception:  # noqa: BLE001
            return {**self.fallback.snapshot(now=now), "counted_in": "process"}
        return {
            "addresses_with_failures": addresses,
            "failures_in_window": everyone,
            "per_email_limit": self.per_email,
            "overall_limit": self.overall,
            "counted_in": "redis",
        }


#: The one the API uses.
throttle = SharedThrottle()
