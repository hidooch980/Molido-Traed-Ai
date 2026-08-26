"""Registering terminals, and the key that becomes a directory name.

Most of this file is about one property. The key a caller supplies is turned
into a path segment, so a key that can express a separator or a parent
reference is a key that can write outside the bridge root - over another
account's files, or over anything else the process can reach.

The stakes are not abstract. The provider is explicit that the published files
carry no account identity, so the directory *is* the account. Two terminals
resolving to one folder means one account's balance sizing the other's orders.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.errors import ValidationFailedError
from app.models.tenancy import Tenant
from app.services import terminals


@pytest.fixture()
def tenant_id(session):
    tenant = Tenant(slug="test", name="Test", is_active=True)
    session.add(tenant)
    session.flush()
    return tenant.id


class TestTheKeyCannotEscapeItsRoot:
    @pytest.mark.parametrize(
        "key",
        [
            "../etc",
            "..",
            "a/b",
            "a\\b",
            "/absolute",
            "with space",
            "Upper",
            "trailing-",
            "-leading",
            "",
            ".",
            "a" * 65,
        ],
    )
    def test_a_key_that_is_not_plainly_a_name_is_refused(self, key):
        """A whitelist, not a blacklist.

        A list of dangerous characters has to stay complete forever against
        somebody who only has to find one that was missed. A list of permitted
        ones is finished the day it is written.
        """
        with pytest.raises(ValidationFailedError):
            terminals.validate_key(key)

    @pytest.mark.parametrize(
        "key", ["main", "fundednext-60k", "robo_pro_1", "acct2", "a1"]
    )
    def test_ordinary_keys_are_accepted(self, key):
        assert terminals.validate_key(key) == key

    def test_upper_case_is_refused_rather_than_folded(self, key="Main"):
        """Two keys differing only by case are two directories on Linux and
        one on the machine somebody typed them on."""
        with pytest.raises(ValidationFailedError):
            terminals.validate_key(key)

    def test_a_valid_key_resolves_one_level_inside_the_root(self):
        """Both sides resolved before comparing.

        Comparing a resolved path against an unresolved one passes on Linux
        and fails on Windows, where `resolve` prepends a drive - which is
        exactly the mistake this assertion was written with the first time.
        """
        resolved = terminals.directory_for("fundednext-60k")
        assert resolved.parent == terminals.BRIDGE_ROOT.resolve()
        assert resolved.name == "fundednext-60k"

    def test_the_key_is_refused_rather_than_rewritten(self):
        """Silently turning `My Account` into `my-account` produces a terminal
        whose key is not the one somebody typed into their expert - and the
        symptom is a terminal publishing into a directory nobody reads."""
        with pytest.raises(ValidationFailedError):
            terminals.directory_for("My Account")


class TestRegistering:
    def test_a_terminal_is_stored_and_listed(self, session, tenant_id, tmp_path, monkeypatch):
        monkeypatch.setattr(terminals, "BRIDGE_ROOT", tmp_path)
        terminals.register(
            session, tenant_id=tenant_id, key="robo-pro", label="RoboForex Pro",
            broker="RoboForex", kind="demo",
        )

        rows = terminals.listing(session, tenant_id=tenant_id)
        assert [r.key for r in rows] == ["robo-pro"]
        assert rows[0].label == "RoboForex Pro"

    def test_the_directory_is_created_on_registration(
        self, session, tenant_id, tmp_path, monkeypatch
    ):
        """So a new terminal shows as "registered, nothing received yet"
        rather than as nothing at all."""
        monkeypatch.setattr(terminals, "BRIDGE_ROOT", tmp_path)
        terminals.register(session, tenant_id=tenant_id, key="acct1")

        assert (tmp_path / "acct1").is_dir()

    def test_registering_the_same_key_twice_is_refused_by_name(
        self, session, tenant_id, tmp_path, monkeypatch
    ):
        """With eleven accounts the usual cause is re-adding one from weeks
        ago, and the useful answer is that it exists rather than that
        something failed."""
        monkeypatch.setattr(terminals, "BRIDGE_ROOT", tmp_path)
        terminals.register(session, tenant_id=tenant_id, key="acct1", label="First")

        with pytest.raises(ValidationFailedError) as refused:
            terminals.register(session, tenant_id=tenant_id, key="acct1")
        assert "First" in refused.value.message

    def test_a_terminal_is_switched_off_rather_than_deleted(
        self, session, tenant_id, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(terminals, "BRIDGE_ROOT", tmp_path)
        created = terminals.register(session, tenant_id=tenant_id, key="acct1")

        terminals.set_active(
            session, tenant_id=tenant_id, terminal_id=created.id, active=False
        )

        rows = terminals.listing(session, tenant_id=tenant_id)
        assert len(rows) == 1
        assert rows[0].is_active is False

    def test_an_inactive_terminal_stops_resolving(
        self, session, tenant_id, tmp_path, monkeypatch
    ):
        """A switched-off terminal must not accept publishes.

        Otherwise "off" means only that it is hidden on a page, while the
        endpoint keeps filing its data.
        """
        monkeypatch.setattr(terminals, "BRIDGE_ROOT", tmp_path)
        created = terminals.register(session, tenant_id=tenant_id, key="acct1")
        assert "acct1" in terminals.registered_dirs(session)

        terminals.set_active(
            session, tenant_id=tenant_id, terminal_id=created.id, active=False
        )
        assert "acct1" not in terminals.registered_dirs(session)

    def test_setting_active_on_an_unknown_terminal_is_refused(self, session, tenant_id):
        with pytest.raises(ValidationFailedError):
            terminals.set_active(
                session, tenant_id=tenant_id, terminal_id=uuid.uuid4(), active=True
            )


class TestTheBridgeMapMergesThem:
    def test_a_registered_terminal_appears_in_the_bridge_map(
        self, session, tenant_id, tmp_path, monkeypatch
    ):
        from app.providers import metatrader

        monkeypatch.setattr(terminals, "BRIDGE_ROOT", tmp_path)
        monkeypatch.delenv("MOLIDO_MT5_BRIDGE_DIRS", raising=False)
        terminals.register(session, tenant_id=tenant_id, key="acct1")

        assert "acct1" in metatrader.bridge_dirs(session=session)

    def test_the_environment_wins_on_a_collision(
        self, session, tenant_id, tmp_path, monkeypatch
    ):
        """It is the one an operator set by hand on the machine.

        A row in a table quietly overriding it would move a terminal's
        directory without anyone touching the configuration they believe is in
        force.
        """
        from app.providers import metatrader

        monkeypatch.setattr(terminals, "BRIDGE_ROOT", tmp_path)
        monkeypatch.setenv("MOLIDO_MT5_BRIDGE_DIRS", "acct1=/explicit/path")
        terminals.register(session, tenant_id=tenant_id, key="acct1")

        assert str(metatrader.bridge_dirs(session=session)["acct1"]) in (
            "/explicit/path",
            "\\explicit\\path",
        )

    def test_without_a_session_only_the_environment_is_seen(
        self, session, tenant_id, tmp_path, monkeypatch
    ):
        """Callers outside a request have no session, and must not crash."""
        from app.providers import metatrader

        monkeypatch.setattr(terminals, "BRIDGE_ROOT", tmp_path)
        monkeypatch.setenv("MOLIDO_MT5_BRIDGE_DIRS", "only=/one")
        terminals.register(session, tenant_id=tenant_id, key="acct1")

        assert set(metatrader.bridge_dirs()) == {"only"}


class TestNoCredentialsAreStored:
    def test_the_model_has_no_password_shaped_column(self):
        """A table that could hold a broker password is one somebody
        eventually puts a broker password in."""
        from app.models.terminals import Terminal

        columns = {c.name for c in Terminal.__table__.columns}
        for forbidden in ("password", "secret", "token", "api_key", "login"):
            assert forbidden not in columns
