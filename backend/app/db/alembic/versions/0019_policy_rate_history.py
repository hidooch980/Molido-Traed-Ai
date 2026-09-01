"""Historical policy rates, point-in-time.

Revision ID: 0019_policy_rate_history
Revises: 0018_journal_strategy
Create Date: 2026-09-01

The live policy-rate reader deliberately refuses `as_of` - a replay that
quietly knows next month's rate decision produces a strategy that cannot
exist. The carry brain needs the other half: the same BIS series with its
observation dates, so a historical measurement reads the rate in force at
the instant being decided on and nothing newer.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019_policy_rate_history"
down_revision = "0018_journal_strategy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "policy_rate_observations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("observed", sa.Date(), nullable=False),
        sa.Column("rate", sa.Float(), nullable=False),
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
        sa.UniqueConstraint("currency", "observed", name="uq_policy_rate_ccy_day"),
    )
    op.create_index(
        "ix_policy_rate_ccy_observed",
        "policy_rate_observations",
        ["currency", "observed"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_policy_rate_ccy_observed", table_name="policy_rate_observations"
    )
    op.drop_table("policy_rate_observations")
