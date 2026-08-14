"""Operational memory: what broke, what was tried, whether it worked.

Revision ID: 0007_incidents
Revises: 0006_challenge_accounts
Create Date: 2026-08-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_incidents"
down_revision = "0006_challenge_accounts"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB


def upgrade() -> None:
    op.create_table(
        "incidents",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("fingerprint", sa.String(200), nullable=False),
        sa.Column("source", sa.String(60), nullable=False),
        sa.Column("summary", sa.String(400), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("occurrences", sa.Integer, nullable=False, server_default="1"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("remedy", sa.Text, nullable=True),
        sa.Column(
            "remedy_confirmed", sa.Boolean, nullable=False, server_default=sa.false()
        ),
        sa.Column("last_alerted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("details", JSONB, nullable=False, server_default="{}"),
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
    # One row per fingerprint is the whole mechanism: it is what makes "the
    # same thing again" countable, and what an alert cooldown hangs off. A
    # unique index rather than application logic, so a race cannot produce two.
    op.create_index(
        "uq_incidents_fingerprint", "incidents", ["fingerprint"], unique=True
    )
    op.create_index("ix_incidents_source", "incidents", ["source"])
    op.create_index("ix_incidents_severity", "incidents", ["severity"])
    op.create_index("ix_incidents_last_seen_at", "incidents", ["last_seen_at"])


def downgrade() -> None:
    op.drop_index("ix_incidents_last_seen_at", table_name="incidents")
    op.drop_index("ix_incidents_severity", table_name="incidents")
    op.drop_index("ix_incidents_source", table_name="incidents")
    op.drop_index("uq_incidents_fingerprint", table_name="incidents")
    op.drop_table("incidents")
