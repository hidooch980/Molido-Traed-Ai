"""An unknown email and a wrong password must cost the same work.

The message was already identical, but an unknown email skipped the password
hash and answered about three times faster - so the response time said which
emails have accounts. Found by the virtual-tester pilot on 2026-09-14.
"""

from __future__ import annotations

import pytest

from app.api.deps import AuthenticationError
from app.core.enums import UserRole
from app.core.security import hash_password
from app.models.tenancy import Tenant, User
from app.services import sessions_auth

EMAIL = "someone@molido.test"
PASSWORD = "a-password-nobody-else-knows"


@pytest.fixture()
def user(session):
    tenant = Tenant(slug="default", name="MolidoTrade", locale="fa")
    session.add(tenant)
    session.flush()
    row = User(
        tenant_id=tenant.id,
        email=EMAIL,
        display_name="someone",
        role=UserRole.VIEWER,
        password_hash=hash_password(PASSWORD),
        is_active=True,
    )
    session.add(row)
    session.flush()
    return row


def _count_checks(monkeypatch) -> list[str]:
    calls: list[str] = []
    real = sessions_auth.verify_password

    def counting(password: str, digest: str) -> bool:
        calls.append(digest)
        return real(password, digest)

    monkeypatch.setattr(sessions_auth, "verify_password", counting)
    return calls


def _sign_in(session, email: str, password: str):
    return sessions_auth.sign_in(session, email=email, password=password)


def test_an_unknown_email_still_checks_a_hash(session, user, monkeypatch):
    calls = _count_checks(monkeypatch)
    with pytest.raises(AuthenticationError) as unknown:
        _sign_in(session, "nobody@molido.test", "wrong-password-123")
    assert len(calls) == 1

    with pytest.raises(AuthenticationError) as wrong:
        _sign_in(session, EMAIL, "wrong-password-123")
    assert len(calls) == 2
    assert str(unknown.value) == str(wrong.value)


def test_the_right_password_still_signs_in(session, user):
    _sign_in(session, EMAIL, PASSWORD)
