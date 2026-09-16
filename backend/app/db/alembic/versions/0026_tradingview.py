"""TradingView webhook secret and received alerts.

Revision ID: 0026_tradingview
Revises: 0025_custom_rulebooks
Create Date: 2026-09-16

Record only. Nothing reads these tables on the way to an order.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0026_tradingview"
down_revision = "0025_custom_rulebooks"
branch_labels = None
depends_on = None


def _stamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "tradingview_config",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("secret_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("secret_hint", sa.String(8), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_stamps(),
    )
    op.create_table(
        "tradingview_alerts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False, server_default=""),
        sa.Column("action", sa.String(16), nullable=False, server_default=""),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("timeframe", sa.String(16), nullable=False, server_default=""),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "payload",
            postgresql.JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=False,
            server_default="{}",
        ),
        *_stamps(),
    )
    op.create_index("ix_tradingview_alerts_symbol", "tradingview_alerts", ["symbol"])
    op.create_index("ix_tradingview_alerts_created_at", "tradingview_alerts", ["created_at"])


def downgrade() -> None:
    op.drop_table("tradingview_alerts")
    op.drop_table("tradingview_config")
