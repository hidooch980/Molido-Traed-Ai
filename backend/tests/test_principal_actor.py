"""Who a change is recorded against.

Routes that write `changed_by` used to read `principal.subject`, an attribute
`Principal` never had, so an account's risk could be changed and the row said
nobody changed it. Found by the virtual-tester pilot on 2026-09-14.
"""

from __future__ import annotations

import uuid

from app.api.deps import ANONYMOUS, Principal
from app.core.enums import Permission, UserRole


def test_a_signed_in_user_is_recorded_by_id():
    who = uuid.uuid4()
    principal = Principal(
        tenant_id=uuid.uuid4(),
        user_id=who,
        role=UserRole.OWNER,
        permissions=frozenset({Permission.READ}),
        authenticated=True,
    )
    assert principal.actor == str(who)


def test_a_caller_without_a_user_is_recorded_by_role():
    assert ANONYMOUS.actor == UserRole.VIEWER.value
    assert ANONYMOUS.actor != ""


def test_no_route_reads_the_attribute_that_never_existed():
    from pathlib import Path

    app = Path(__file__).resolve().parents[1] / "app"
    offenders = [
        str(path)
        for path in app.rglob("*.py")
        if 'getattr(principal, "subject"' in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
