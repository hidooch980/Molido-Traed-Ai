"""Service-level observations, in a table a restart cannot empty.

Revision ID: 0022_slo_observations
Revises: 0021_audit_chain
Create Date: 2026-09-02

`slo_window_populated` asked for a hundred observations from a list that
lived in the API process and emptied on every deploy. See `app.ops.slo`.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022_slo_observations"
down_revision = "0021_audit_chain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "slo_observations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metric", sa.String(64), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_index(
        "ix_slo_observations_metric_time", "slo_observations", ["metric", "observed_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_slo_observations_metric_time", table_name="slo_observations")
    op.drop_table("slo_observations")
