"""The chat channel's configuration, set from the site.

Revision ID: 0020_telegram_config
Revises: 0019_policy_rate_history
Create Date: 2026-09-01

The token lived in the env file, so changing it was an SSH session and a
container restart - and in practice it was never set. A channel nobody can
configure is a channel nobody uses.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0020_telegram_config"
down_revision = "0019_policy_rate_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_config",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("bot_token", sa.String(200), nullable=False, server_default=""),
        sa.Column(
            "chat_ids",
            postgresql.JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
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
    )


def downgrade() -> None:
    op.drop_table("telegram_config")
