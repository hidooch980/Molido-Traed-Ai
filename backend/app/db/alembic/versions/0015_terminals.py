"""Terminals that publish into the bridge, registered rather than configured.

Revision ID: 0015_terminals
Revises: 0014_two_factor
Create Date: 2026-08-26

Bridge directories came from `MOLIDO_MT5_BRIDGE_DIRS`, which is the right shape
for the one terminal this platform was built around and the wrong shape for
eleven. Every new account meant editing an environment file, rebuilding a
container, and needing somebody with a shell - so the person who owns the
accounts could not add one, and the person who could had no way to know which
account was which.

The key is unique per tenant and becomes a directory name, which is why the
column is narrow and the service that writes it validates the shape. The
provider is blunt about the stakes: the published files carry no account
identity, so the directory *is* the account. Two terminals resolving to one
folder means one account's balance sizing the other's orders.

No credentials. A row here is a name, a key, a broker and whether it is still
in use; the login and password live in MetaTrader's own configuration and the
API key the expert authenticates with lives in the key store, hashed, with
every other key. A table that could hold a broker password is a table somebody
eventually puts one in.

Deactivated rather than deleted, for the reason every other soft delete here
exists: the bridge directory keeps whatever it last published, and a decision
recorded against a terminal that no longer resolves is a decision about nobody.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_terminals"
down_revision = "0014_two_factor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "terminals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("label", sa.String(120), nullable=False, server_default=""),
        sa.Column("broker", sa.String(120), nullable=False, server_default=""),
        sa.Column("kind", sa.String(32), nullable=False, server_default=""),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("tenant_id", "key", name="uq_terminals_tenant_key"),
    )


def downgrade() -> None:
    op.drop_table("terminals")
