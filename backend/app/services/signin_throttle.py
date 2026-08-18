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

In memory rather than in the database. The window is minutes, a restart
clearing it is acceptable, and a write on every failed guess would hand an
attacker a way to make the database do work too.
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import UTC, datetime, timedelta

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


#: The one the API uses. A module-level instance because the window is
#: per-process state and there is one process serving these routes.
throttle = Throttle()
