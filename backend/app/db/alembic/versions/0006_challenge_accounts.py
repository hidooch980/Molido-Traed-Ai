"""Challenge accounts the holder has confirmed the rules for.

Revision ID: 0006_challenge_accounts
Revises: 0005_episodes
Create Date: 2026-08-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_challenge_accounts"
down_revision = "0005_episodes"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "challenge_accounts",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "tenant_id",
            UUID,
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("rulebook_key", sa.String(80), nullable=False),
        # Numeric, not float. A balance is money, and money that rounds
        # differently on two machines fails a drawdown check on one of them.
        sa.Column("starting_balance", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("currency_per_r", sa.Numeric(18, 4), nullable=True),
        # Defaults to false because that is the honest state of a row nobody
        # has checked against a contract yet.
        sa.Column(
            "rules_confirmed", sa.Boolean, nullable=False, server_default=sa.false()
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.String(2000), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
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
        sa.UniqueConstraint(
            "tenant_id", "label", name="uq_challenge_accounts_tenant_label"
        ),
    )
    op.create_index(
        "ix_challenge_accounts_tenant_id", "challenge_accounts", ["tenant_id"]
    )
    op.create_index(
        "ix_challenge_accounts_rulebook_key", "challenge_accounts", ["rulebook_key"]
    )


def downgrade() -> None:
    op.drop_index("ix_challenge_accounts_rulebook_key", table_name="challenge_accounts")
    op.drop_index("ix_challenge_accounts_tenant_id", table_name="challenge_accounts")
    op.drop_table("challenge_accounts")
