"""Symbol DNA: stored behavioural profiles.

Revision ID: 0004_symbol_dna
Revises: 0003_feature_store
Create Date: 2026-08-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_symbol_dna"
down_revision = "0003_feature_store"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "symbol_profiles",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "instrument_id",
            UUID,
            sa.ForeignKey("instruments.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("profile_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("as_of", TS, nullable=False),
        sa.Column("computed_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("sample_size", sa.Integer, nullable=False, server_default="0"),
        sa.Column("coverage_start", TS, nullable=True),
        sa.Column("coverage_end", TS, nullable=True),
        sa.Column("data", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_symbol_profiles_lookup",
        "symbol_profiles",
        ["instrument_id", "timeframe", "kind", "as_of"],
    )


def downgrade() -> None:
    op.drop_table("symbol_profiles")
