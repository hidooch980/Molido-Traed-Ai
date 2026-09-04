"""Calling a terminal something a person recognises.

`term-b` through `term-h` are unique, correct and say nothing. The name added
here is decoration and every test below is about keeping it that way: the key
stays the identity, an unnamed terminal behaves exactly as it did before the
table existed, and two rows may never come to read the same - which is the
confusion the name exists to remove.
"""

from __future__ import annotations

import pytest

from app.core.errors import ValidationFailedError
from app.services import terminal_names

KNOWN = {"term-b": "/b", "term-c": "/c", "term-d": "/d"}


@pytest.fixture(autouse=True)
def _clean_cache():
    terminal_names.invalidate()
    yield
    terminal_names.invalidate()


@pytest.fixture()
def stored(monkeypatch):
    """Pretend the table holds these rows, without touching a database."""

    def _set(rows):
        monkeypatch.setattr(terminal_names, "_load", lambda: rows)
        terminal_names.invalidate()

    return _set


class TestAbsentIsNotBlank:
    def test_an_empty_table_shows_every_terminal_under_its_key(self, stored):
        """The whole safety of the migration: nothing named is nothing
        changed."""
        stored({})

        assert terminal_names.label_for("term-b") is None
        assert terminal_names.display("term-b") == "term-b"

    def test_a_database_that_cannot_be_read_falls_back_to_the_key(self, monkeypatch):
        """A display name must never be the reason a fleet listing breaks."""

        def explode():
            raise RuntimeError("no database")

        monkeypatch.setattr(terminal_names, "_load", explode)
        terminal_names.invalidate()

        assert terminal_names.display("term-b") == "term-b"

    def test_an_empty_table_is_still_a_reading(self, monkeypatch):
        """An empty table is the ordinary state of a fresh deployment, and
        testing the cache for truth would query on every single call - the
        exact behaviour the cache exists to prevent, in the case it matters
        most."""
        calls = {"n": 0}

        def counted():
            calls["n"] += 1
            return {}

        monkeypatch.setattr(terminal_names, "_load", counted)
        terminal_names.invalidate()

        terminal_names.all_names(now=100.0)
        terminal_names.all_names(now=105.0)
        terminal_names.all_names(now=110.0)

        assert calls["n"] == 1

    def test_a_rename_is_live_within_the_time_to_live(self, monkeypatch):
        rows = {"term-b": "cent 500"}
        monkeypatch.setattr(terminal_names, "_load", lambda: dict(rows))
        terminal_names.invalidate()

        assert terminal_names.all_names(now=100.0)["term-b"] == "cent 500"
        rows["term-b"] = "the demo"
        # Still cached.
        assert terminal_names.all_names(now=110.0)["term-b"] == "cent 500"
        # And read again once the reading has expired.
        assert (
            terminal_names.all_names(now=100.0 + terminal_names.CACHE_SECONDS)["term-b"]
            == "the demo"
        )


class TestTwoRowsMayNotReadTheSame:
    def test_a_name_may_not_be_another_terminals_key(self, stored):
        """A label that is somebody else's identity is how an operator acts on
        the wrong account by way of a word."""
        stored({})

        with pytest.raises(ValidationFailedError):
            terminal_names.clean("term-c", terminal="term-b", known=KNOWN)

    def test_a_terminal_may_be_named_after_its_own_key(self, stored):
        """Pointless, and not a collision: it names itself."""
        stored({})

        assert terminal_names.clean("term-b", terminal="term-b", known=KNOWN) == "term-b"

    def test_two_terminals_may_not_share_one_name(self, stored):
        stored({"term-c": "cent 500"})

        with pytest.raises(ValidationFailedError):
            terminal_names.clean("cent 500", terminal="term-b", known=KNOWN)

    def test_the_comparison_ignores_case(self, stored):
        """"Cent 500" and "cent 500" are one name to a reader, which is the
        only reader this matters to."""
        stored({"term-c": "cent 500"})

        with pytest.raises(ValidationFailedError):
            terminal_names.clean("Cent 500", terminal="term-b", known=KNOWN)

    def test_a_terminal_may_keep_its_own_name(self, stored):
        """Saving the form again without changing the field is not a
        collision with itself."""
        stored({"term-b": "cent 500"})

        assert terminal_names.clean("cent 500", terminal="term-b", known=KNOWN) == "cent 500"


class TestWhatANameMayBe:
    def test_whitespace_is_collapsed(self, stored):
        stored({})

        assert terminal_names.clean("  cent   500 ", terminal="term-b", known=KNOWN) == "cent 500"

    def test_blank_clears_the_name(self, stored):
        stored({})

        assert terminal_names.clean("   ", terminal="term-b", known=KNOWN) == ""

    def test_control_and_direction_characters_are_refused(self, stored):
        """A name carrying a right-to-left override renders as something
        other than what was typed, and in a list of accounts that is where
        somebody reaches for the wrong row."""
        stored({})

        with pytest.raises(ValidationFailedError):
            terminal_names.clean("cent\u202e005", terminal="term-b", known=KNOWN)

    def test_a_persian_name_is_accepted(self, stored):
        """The operator reads Persian. A rule that only admitted ASCII would
        make the feature useless to the person it is for."""
        stored({})

        assert (
            terminal_names.clean("حساب سنتی ۵۰۰", terminal="term-b", known=KNOWN)
            == "حساب سنتی ۵۰۰"
        )

    def test_a_name_longer_than_the_column_is_refused_not_truncated(self, stored):
        """Truncating would store a name the operator never chose and show it
        back as though they had."""
        stored({})

        with pytest.raises(ValidationFailedError):
            terminal_names.clean("x" * (terminal_names.MAX_LABEL + 1), terminal="term-b", known=KNOWN)


class TestTheRoute:
    """Written against HTTP rather than the service, because the two
    refusals that matter here - a terminal that does not exist, and a caller
    who may not rename one - live in the route and nowhere else."""

    @pytest.fixture()
    def client(self, session, monkeypatch):
        import pathlib
        import uuid as uuid_module

        from fastapi.testclient import TestClient

        from app.api.deps import ROLE_PERMISSIONS, Principal, resolve_principal
        from app.api.v1 import brokers as brokers_module
        from app.core.enums import UserRole
        from app.db.session import get_db
        from app.main import app

        dirs = {key: pathlib.Path(path) for key, path in KNOWN.items()}
        monkeypatch.setattr(brokers_module, "bridge_dirs", lambda *a, **k: dirs)
        # The service reads through its own session, which in a test is the
        # one the fixture holds - otherwise a name written by the route is
        # invisible to the read that follows it.
        monkeypatch.setattr(
            "app.db.session.session_scope",
            lambda *a, **k: __import__("contextlib").nullcontext(session),
        )

        app.dependency_overrides[get_db] = lambda: session
        app.dependency_overrides[resolve_principal] = lambda: Principal(
            tenant_id=uuid_module.uuid4(),
            user_id=uuid_module.uuid4(),
            role=UserRole.OWNER,
            permissions=frozenset(ROLE_PERMISSIONS[UserRole.OWNER]),
            authenticated=True,
        )
        with TestClient(app) as test_client:
            yield test_client
        app.dependency_overrides.clear()

    def test_a_terminal_that_does_not_exist_is_refused(self, client):
        """A row naming a key nothing publishes would sit in the table naming
        nothing - and would name the next account to take that key."""
        response = client.put(
            "/api/v1/brokers/terminals/term-z/name", json={"label": "whatever"}
        )

        assert response.status_code >= 400

    def test_a_name_is_stored_and_read_back(self, client):
        assert (
            client.put(
                "/api/v1/brokers/terminals/term-b/name", json={"label": "cent 500"}
            ).json()["label"]
            == "cent 500"
        )
        assert terminal_names.label_for("term-b") == "cent 500"

    def test_a_blank_name_clears_it(self, client):
        client.put("/api/v1/brokers/terminals/term-b/name", json={"label": "cent 500"})

        body = client.put(
            "/api/v1/brokers/terminals/term-b/name", json={"label": ""}
        ).json()

        assert body["label"] is None
        assert terminal_names.label_for("term-b") is None

    def test_a_viewer_may_not_rename_a_terminal(self, session, monkeypatch):
        """It is a display name and it still decides which row somebody
        reaches for at two in the morning."""
        import pathlib
        import uuid as uuid_module

        from fastapi.testclient import TestClient

        from app.api.deps import ROLE_PERMISSIONS, Principal, resolve_principal
        from app.api.v1 import brokers as brokers_module
        from app.core.enums import UserRole
        from app.db.session import get_db
        from app.main import app

        dirs = {key: pathlib.Path(path) for key, path in KNOWN.items()}
        monkeypatch.setattr(brokers_module, "bridge_dirs", lambda *a, **k: dirs)
        app.dependency_overrides[get_db] = lambda: session
        app.dependency_overrides[resolve_principal] = lambda: Principal(
            tenant_id=uuid_module.uuid4(),
            user_id=uuid_module.uuid4(),
            role=UserRole.VIEWER,
            permissions=frozenset(ROLE_PERMISSIONS[UserRole.VIEWER]),
            authenticated=True,
        )
        with TestClient(app) as viewer:
            response = viewer.put(
                "/api/v1/brokers/terminals/term-b/name", json={"label": "mine now"}
            )
        app.dependency_overrides.clear()

        assert response.status_code in (401, 403)
