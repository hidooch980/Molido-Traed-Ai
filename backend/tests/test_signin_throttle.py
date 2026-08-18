"""How many sign-in attempts an address, and everyone together, may make.

The gate was already the right shape - one failure message whichever half of
the guess was wrong - and had no answer for volume. Two problems live here and
a single counter answers neither well: guessing a password, and spending the
server's cores on PBKDF2 at 480,000 iterations from an unauthenticated caller.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.signin_throttle import GLOBAL, PER_EMAIL, WINDOW, Throttle

AT = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)


class TestPerAddress:
    def test_a_fresh_address_is_let_through(self):
        assert Throttle().check("a@b.com") is None

    def test_it_refuses_after_the_limit(self):
        throttle = Throttle(per_email=3)
        for _ in range(3):
            throttle.failed("a@b.com")

        assert "too many failed sign-ins for this address" in (
            throttle.check("a@b.com") or ""
        )

    def test_one_short_of_the_limit_is_still_allowed(self):
        """A person mistyping a password is the ordinary case, not the
        attack, and the limit is generous on purpose."""
        throttle = Throttle(per_email=3)
        throttle.failed("a@b.com")
        throttle.failed("a@b.com")

        assert throttle.check("a@b.com") is None

    def test_one_address_does_not_refuse_another(self):
        throttle = Throttle(per_email=2)
        throttle.failed("a@b.com")
        throttle.failed("a@b.com")

        assert throttle.check("c@d.com") is None

    def test_the_address_is_matched_case_insensitively(self):
        """Otherwise the same address in different case is a fresh budget."""
        throttle = Throttle(per_email=2)
        throttle.failed("A@B.com")
        throttle.failed("a@b.COM")

        assert throttle.check(" a@b.com ") is not None


class TestTheGlobalLimit:
    """Per address alone lets someone spray one guess each across a thousand
    addresses and never trip it."""

    def test_many_addresses_together_trip_it(self):
        throttle = Throttle(per_email=100, overall=5)
        for i in range(5):
            throttle.failed(f"user{i}@example.com")

        assert throttle.check("someone-else@example.com") is not None

    def test_the_global_message_does_not_say_it_is_global(self):
        """An attacker learning they tripped a system-wide limit learns the
        limit exists and roughly where it is."""
        throttle = Throttle(per_email=100, overall=2)
        throttle.failed("a@b.com")
        throttle.failed("c@d.com")

        message = throttle.check("e@f.com") or ""

        assert "this address" not in message
        assert "too many failed sign-ins" in message


class TestSuccessClearsTheAddress:
    def test_getting_it_right_forgives_the_fumbles(self):
        throttle = Throttle(per_email=3)
        throttle.failed("a@b.com")
        throttle.failed("a@b.com")

        throttle.succeeded("a@b.com")

        assert throttle.check("a@b.com") is None

    def test_it_clears_only_that_address(self):
        throttle = Throttle(per_email=2)
        throttle.failed("a@b.com")
        throttle.failed("c@d.com")
        throttle.failed("c@d.com")

        throttle.succeeded("a@b.com")

        assert throttle.check("c@d.com") is not None


class TestTheWindowExpires:
    def test_failures_outside_the_window_stop_counting(self):
        throttle = Throttle(per_email=2, window=timedelta(minutes=15))
        throttle.failed("a@b.com", now=AT)
        throttle.failed("a@b.com", now=AT)

        assert throttle.check("a@b.com", now=AT) is not None
        assert throttle.check("a@b.com", now=AT + timedelta(minutes=16)) is None

    def test_a_failure_inside_the_window_still_counts(self):
        throttle = Throttle(per_email=2, window=timedelta(minutes=15))
        throttle.failed("a@b.com", now=AT)
        throttle.failed("a@b.com", now=AT + timedelta(minutes=14))

        assert throttle.check("a@b.com", now=AT + timedelta(minutes=14)) is not None

    def test_expired_addresses_are_forgotten_rather_than_kept_empty(self):
        """Otherwise the map grows for every address ever tried."""
        throttle = Throttle(window=timedelta(minutes=15))
        throttle.failed("a@b.com", now=AT)

        after = throttle.snapshot(now=AT + timedelta(minutes=16))

        assert after["addresses_with_failures"] == 0


class TestTheDefaults:
    def test_a_person_gets_several_tries(self):
        assert PER_EMAIL >= 5

    def test_the_global_limit_is_above_ordinary_fumbling(self):
        """Set so a handful of real people mistyping cannot lock the door."""
        assert GLOBAL > PER_EMAIL * 5

    def test_the_window_is_minutes_not_hours(self):
        """Long enough that a wordlist is not a matter of waiting seconds,
        short enough that a person who forgot can try again after a coffee."""
        assert timedelta(minutes=5) <= WINDOW <= timedelta(hours=1)


class TestTheSnapshot:
    def test_it_reports_what_is_being_counted(self):
        throttle = Throttle(per_email=8, overall=60)
        throttle.failed("a@b.com", now=AT)
        throttle.failed("c@d.com", now=AT)

        assert throttle.snapshot(now=AT) == {
            "addresses_with_failures": 2,
            "failures_in_window": 2,
            "per_email_limit": 8,
            "overall_limit": 60,
        }


class TestTheRouteRefusesBeforeItHashes:
    """PBKDF2 at 480,000 iterations is paid by this server before it can
    answer, so a throttled attempt that still paid for the hash would be the
    attack rather than the defence."""

    def test_a_throttled_attempt_never_reaches_the_password_check(
        self, monkeypatch
    ):
        from app.api.deps import AuthenticationError
        from app.api.v1 import session as route
        from app.services import signin_throttle

        reached = []

        def should_not_run(*args, **kwargs):
            reached.append(1)
            raise AuthenticationError("no")

        monkeypatch.setattr(route.sessions_auth, "sign_in", should_not_run)
        monkeypatch.setattr(
            signin_throttle, "throttle", Throttle(per_email=1)
        )
        signin_throttle.throttle.failed("a@b.com")

        credentials = route.Credentials(email="a@b.com", password="x" * 12)

        try:
            route.sign_in(credentials, response=None, session=None)
        except AuthenticationError as refused:
            assert "too many failed sign-ins" in str(refused)
        else:  # pragma: no cover - the call must refuse
            raise AssertionError("a throttled attempt was allowed through")

        assert reached == [], "the password was hashed despite the throttle"


class FakeRedis:
    """Enough of a client to count with, including the expiry semantics."""

    def __init__(self, *, broken: bool = False):
        self.store: dict[str, int] = {}
        self.expiries: dict[str, int] = {}
        self.broken = broken

    def _boom(self):
        if self.broken:
            raise RuntimeError("redis is down")

    def ping(self):
        self._boom()
        return True

    def get(self, key):
        self._boom()
        return self.store.get(key)

    def incr(self, key):
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    def expire(self, key, seconds, nx=False):
        # nx means "only if it has no expiry yet", which is what keeps the
        # window measured from the first failure.
        if nx and key in self.expiries:
            return False
        self.expiries[key] = seconds
        return True

    def delete(self, key):
        self._boom()
        self.store.pop(key, None)

    def scan_iter(self, match, count=None):
        self._boom()
        prefix = match.rstrip("*")
        return [k for k in self.store if k.startswith(prefix)]

    def pipeline(self):
        self._boom()
        return self

    def execute(self):
        return True


class TestItCountsWhereEveryWorkerCanSee:
    """The API runs under gunicorn with several uvicorn workers. A counter in
    each of them is not one limit of eight - it is eight per worker, read from
    whichever answered. The first implementation here did exactly that: ten
    wrong passwords went through and the snapshot reported zero."""

    def build(self, monkeypatch, client):
        from app.services import signin_throttle

        monkeypatch.setattr(signin_throttle, "_redis", lambda: client)
        return signin_throttle.SharedThrottle(per_email=3, overall=10)

    def test_failures_are_counted_in_redis(self, monkeypatch):
        client = FakeRedis()
        throttle = self.build(monkeypatch, client)

        throttle.failed("a@b.com")
        throttle.failed("a@b.com")

        assert client.store["molido:signin:email:a@b.com"] == 2
        assert client.store["molido:signin:all"] == 2

    def test_the_limit_refuses(self, monkeypatch):
        client = FakeRedis()
        throttle = self.build(monkeypatch, client)
        for _ in range(3):
            throttle.failed("a@b.com")

        assert "this address" in (throttle.check("a@b.com") or "")

    def test_a_second_worker_sees_the_first_worker_s_failures(self, monkeypatch):
        """The whole point. Two instances, one shared counter."""
        client = FakeRedis()
        worker_one = self.build(monkeypatch, client)
        worker_two = self.build(monkeypatch, client)

        for _ in range(3):
            worker_one.failed("a@b.com")

        assert worker_two.check("a@b.com") is not None

    def test_success_clears_the_address_everywhere(self, monkeypatch):
        client = FakeRedis()
        throttle = self.build(monkeypatch, client)
        for _ in range(3):
            throttle.failed("a@b.com")

        throttle.succeeded("a@b.com")

        assert throttle.check("a@b.com") is None

    def test_the_window_runs_from_the_first_failure(self, monkeypatch):
        """A steady drip of guesses must not keep pushing the expiry out and
        stay under the limit forever."""
        client = FakeRedis()
        throttle = self.build(monkeypatch, client)

        throttle.failed("a@b.com")
        first = dict(client.expiries)
        throttle.failed("a@b.com")

        assert client.expiries == first

    def test_the_snapshot_says_it_is_counting_in_redis(self, monkeypatch):
        throttle = self.build(monkeypatch, FakeRedis())

        assert throttle.snapshot()["counted_in"] == "redis"


class TestWhenRedisIsUnreachable:
    """Weaker by exactly the number of workers, and honest about it. A
    limiter quietly running at four times its stated limit is worse than one
    that says so."""

    def build(self, monkeypatch):
        from app.services import signin_throttle

        monkeypatch.setattr(signin_throttle, "_redis", lambda: None)
        return signin_throttle.SharedThrottle(per_email=2, overall=10)

    def test_it_still_throttles(self, monkeypatch):
        """Falling back to something is better than falling back to nothing."""
        throttle = self.build(monkeypatch)
        throttle.failed("a@b.com")
        throttle.failed("a@b.com")

        assert throttle.check("a@b.com") is not None

    def test_the_snapshot_warns(self, monkeypatch):
        snapshot = self.build(monkeypatch).snapshot()

        assert snapshot["counted_in"] == "process"
        assert "times the number of workers" in snapshot["warning"]

    def test_it_does_not_lock_everyone_out(self, monkeypatch):
        """Refusing every sign-in would lock the operator out of their own
        controls at the moment something is already wrong."""
        assert self.build(monkeypatch).check("fresh@example.com") is None

    def test_a_broken_client_falls_back_rather_than_raising(self, monkeypatch):
        from app.services import signin_throttle

        monkeypatch.setattr(signin_throttle, "_redis", lambda: FakeRedis(broken=True))
        throttle = signin_throttle.SharedThrottle(per_email=2)

        throttle.failed("a@b.com")
        throttle.failed("a@b.com")

        assert throttle.check("a@b.com") is not None
