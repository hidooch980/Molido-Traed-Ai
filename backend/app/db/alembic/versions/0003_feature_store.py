"""Feature store: materialized feature values.

Revision ID: 0003_feature_store
Revises: 0002_session_calendar
Create Date: 2026-08-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_feature_store"
down_revision = "0002_session_calendar"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)


def _timescale_enabled(conn) -> bool:
    return bool(
        conn.execute(
            sa.text("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'")
        ).scalar()
    )


def upgrade() -> None:
    conn = op.get_bind()

    op.create_table(
        "feature_values",
        sa.Column(
            "instrument_id",
            UUID,
            sa.ForeignKey("instruments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("feature_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("event_time", TS, nullable=False),
        sa.Column("computed_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("value", sa.Numeric(28, 12), nullable=True),
        sa.Column("source_revision", sa.Integer, nullable=False, server_default="1"),
        sa.Column("quality_score", sa.Numeric(4, 3), nullable=False, server_default="1.0"),
        sa.PrimaryKeyConstraint(
            "instrument_id", "timeframe", "name", "feature_version", "event_time"
        ),
    )
    op.create_index(
        "ix_feature_values_lookup",
        "feature_values",
        ["instrument_id", "timeframe", "name", "event_time"],
    )
    op.create_index("ix_feature_values_computed", "feature_values", ["computed_at"])

    if _timescale_enabled(conn):
        op.execute(
            "SELECT create_hypertable('feature_values', 'event_time', "
            "chunk_time_interval => INTERVAL '30 days', migrate_data => TRUE)"
        )
        op.execute(
            "ALTER TABLE feature_values SET (timescaledb.compress, "
            "timescaledb.compress_segmentby = 'instrument_id, timeframe, name')"
        )
        op.execute("SELECT add_compression_policy('feature_values', INTERVAL '180 days')")


def downgrade() -> None:
    op.drop_table("feature_values")
