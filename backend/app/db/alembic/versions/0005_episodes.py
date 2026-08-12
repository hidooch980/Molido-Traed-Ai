"""Historical episodes.

Revision ID: 0005_episodes
Revises: 0004_symbol_dna
Create Date: 2026-08-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_episodes"
down_revision = "0004_symbol_dna"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB
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
        "episodes",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "instrument_id",
            UUID,
            sa.ForeignKey("instruments.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("builder_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("event_time", TS, nullable=False),
        sa.Column("horizon_bars", sa.Integer, nullable=False),
        sa.Column("outcome_ready_at", TS, nullable=False),
        sa.Column("computed_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("entry_price", sa.Numeric(20, 10), nullable=False),
        sa.Column("session_labels", JSONB, nullable=False, server_default="[]"),
        sa.Column("features", JSONB, nullable=False, server_default="{}"),
        sa.Column("max_up_pct", sa.Numeric(20, 10), nullable=True),
        sa.Column("max_down_pct", sa.Numeric(20, 10), nullable=True),
        sa.Column("forward_return_pct", sa.Numeric(20, 10), nullable=True),
        sa.Column("bars_to_max_up", sa.Integer, nullable=True),
        sa.Column("bars_to_max_down", sa.Integer, nullable=True),
        sa.Column("outcome_bars", sa.Integer, nullable=False, server_default="0"),
        sa.Column("regime", sa.String(32), nullable=True),
        sa.Column("strategy", sa.String(64), nullable=True),
        sa.Column("decision", sa.String(16), nullable=True),
        sa.Column("r_multiple", sa.Numeric(12, 6), nullable=True),
        sa.Column("execution_quality", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "instrument_id",
            "timeframe",
            "event_time",
            "horizon_bars",
            "builder_version",
            name="uq_episode_moment",
        ),
    )
    op.create_index(
        "ix_episodes_ready", "episodes", ["instrument_id", "timeframe", "outcome_ready_at"]
    )
    op.create_index(
        "ix_episodes_lookup", "episodes", ["instrument_id", "timeframe", "event_time"]
    )

    if _timescale_enabled(conn):
        # Episodes are queried by maturity and similarity rather than swept by
        # time range, so this stays an ordinary table — a hypertable would add
        # chunk overhead for no gain. Compression still pays once it is large.
        pass


def downgrade() -> None:
    op.drop_table("episodes")
