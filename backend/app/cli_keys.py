"""Mint the API key the broker-link form needs (spec §45, §52).

One command, because the alternative is a hand-written INSERT and a hash
computed in a shell, and a credential created that way is one nobody can
revoke because nobody recorded what it was for.

The raw key is printed once and never stored. Only a bcrypt hash and a
non-secret prefix reach the database, which is why a lost key is replaced
rather than recovered - and why this prints it to a file the owner reads
themselves rather than to a log somebody else can scroll back through.

    python -m app.cli_keys mint --label "broker form" --role trader
    python -m app.cli_keys list
    python -m app.cli_keys revoke <prefix>
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.enums import UserRole
from app.core.security import generate_api_key
from app.db.session import session_scope
from app.models.tenancy import ApiKey, Tenant, User


def _tenant_and_user(session, role: UserRole) -> tuple[Tenant, User]:
    """The default tenant and a user carrying `role`, created if absent.

    A key with no user resolves to VIEWER, which holds READ only - so a key
    minted without one would be accepted by the API and refused by every route
    that needed it, which reads as a broken key rather than a wrong role.
    """
    tenant = session.scalar(select(Tenant).where(Tenant.slug == "default"))
    if tenant is None:
        tenant = Tenant(slug="default", name="MolidoTrade", locale="fa")
        session.add(tenant)
        session.flush()

    email = f"{role.value}@molidotrade.local"
    user = session.scalar(
        select(User).where(User.tenant_id == tenant.id, User.email == email)
    )
    if user is None:
        user = User(
            tenant_id=tenant.id,
            email=email,
            display_name=f"{role.value} (key holder)",
            role=role,
            locale="fa",
            is_active=True,
            # No password. This user exists to carry a role for an API key and
            # cannot sign in; a hash here would be a credential nobody needs.
            password_hash=None,
        )
        session.add(user)
        session.flush()
    elif user.role != role:
        user.role = role

    return tenant, user


def mint(label: str, role: UserRole) -> str:
    raw, prefix, hashed = generate_api_key()
    with session_scope() as session:
        tenant, user = _tenant_and_user(session, role)
        session.add(
            ApiKey(
                tenant_id=tenant.id,
                user_id=user.id,
                label=label,
                key_prefix=prefix,
                key_hash=hashed,
                scopes=role.value,
            )
        )
    return raw


def listing() -> list[str]:
    with session_scope() as session:
        rows = session.scalars(select(ApiKey).order_by(ApiKey.created_at)).all()
        return [
            f"{key.key_prefix}  {key.label:24} {key.scopes:10} "
            f"{'revoked' if key.revoked_at else 'active'}  "
            f"last used {key.last_used_at or 'never'}"
            for key in rows
        ]


def revoke(prefix: str) -> bool:
    with session_scope() as session:
        key = session.scalar(select(ApiKey).where(ApiKey.key_prefix == prefix))
        if key is None or key.revoked_at is not None:
            return False
        key.revoked_at = datetime.now(UTC)
        return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    minter = sub.add_parser("mint", help="create a key and print it once")
    minter.add_argument("--label", required=True)
    minter.add_argument(
        "--role",
        default=UserRole.TRADER.value,
        choices=[r.value for r in UserRole],
        help="trader carries read+simulate+execute; analyst stops at simulate",
    )

    sub.add_parser("list", help="show every key by prefix, never the key itself")

    revoker = sub.add_parser("revoke", help="revoke by prefix")
    revoker.add_argument("prefix")

    args = parser.parse_args()

    if args.command == "mint":
        raw = mint(args.label, UserRole(args.role))
        print(raw)
        print(
            "\nThis is the only time this key is printed. The database holds a "
            "hash and a prefix, so a lost key is replaced rather than recovered.",
            file=sys.stderr,
        )
        return 0

    if args.command == "list":
        rows = listing()
        print("\n".join(rows) if rows else "no keys")
        return 0

    ok = revoke(args.prefix)
    print("revoked" if ok else "no active key with that prefix")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
