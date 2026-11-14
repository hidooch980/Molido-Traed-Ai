"""Per-agent language-model usage ledger (agents stage 3).

Revision ID: 0030_agent_llm_usage
Revises: 0029_telegram_signal_channel
Create Date: 2026-11-14

Portable types only, so the SQLite migration test can build it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0030_agent_llm_usage"
down_revision = "0029_telegram_signal_channel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_llm_usage",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent_id", sa.String(16), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("priority", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("cached_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("reasoning_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("cache_hit", sa.Boolean(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
    )
    op.create_index(
        "ix_agent_llm_usage_agent_time", "agent_llm_usage", ["agent_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_agent_llm_usage_agent_time", table_name="agent_llm_usage")
    op.drop_table("agent_llm_usage")
