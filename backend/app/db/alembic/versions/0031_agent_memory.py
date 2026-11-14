"""Agent memory, council decisions, failures and learning records (agents stage 5).

Revision ID: 0031_agent_memory
Revises: 0030_agent_llm_usage
Create Date: 2026-11-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0031_agent_memory"
down_revision = "0030_agent_llm_usage"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "agent_memory",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("agent_id", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("content", JSON, nullable=False),
        sa.Column("source_ref", sa.String(128), nullable=False),
    )
    op.create_index("ix_agent_memory_agent_kind_time", "agent_memory",
                    ["agent_id", "kind", "created_at"])
    op.create_table(
        "agent_council_decisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("weights_version", sa.Integer(), nullable=False),
        sa.Column("verdict", JSON, nullable=False),
        sa.Column("opinions", JSON, nullable=False),
        sa.Column("outcome_r", sa.Float(), nullable=True),
        sa.Column("resolved_at", TS, nullable=True),
    )
    op.create_index("ix_agent_council_decisions_symbol_time", "agent_council_decisions",
                    ["symbol", "created_at"])
    op.create_table(
        "agent_failures",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("agent_id", sa.String(16), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("ref", sa.String(128), nullable=False),
        sa.Column("details", JSON, nullable=False),
    )
    op.create_index("ix_agent_failures_category_time", "agent_failures",
                    ["category", "created_at"])
    op.create_table(
        "agent_learning_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("agent_id", sa.String(16), nullable=False),
        sa.Column("change", JSON, nullable=False),
        sa.Column("evidence", JSON, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("decided_by", sa.String(128), nullable=False),
        sa.Column("decided_at", TS, nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
    )
    op.create_index("ix_agent_learning_records_status", "agent_learning_records", ["status"])


def downgrade() -> None:
    for index, table in (
        ("ix_agent_learning_records_status", "agent_learning_records"),
        ("ix_agent_failures_category_time", "agent_failures"),
        ("ix_agent_council_decisions_symbol_time", "agent_council_decisions"),
        ("ix_agent_memory_agent_kind_time", "agent_memory"),
    ):
        op.drop_index(index, table_name=table)
        op.drop_table(table)
