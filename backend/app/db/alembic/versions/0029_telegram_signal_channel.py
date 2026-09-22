"""A Telegram channel that receives the trades the fleet opens and closes.

Revision ID: 0029_telegram_signal_channel
Revises: 0028_account_trailing_weekend
Create Date: 2026-09-23

Separate from `chat_ids`: those are the admins the bot answers and alerts,
and a channel's subscribers are neither. Empty means no channel, which is
the state every existing deployment is in.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029_telegram_signal_channel"
down_revision = "0028_account_trailing_weekend"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "telegram_config",
        sa.Column("signal_channel", sa.String(64), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("telegram_config", "signal_channel")
