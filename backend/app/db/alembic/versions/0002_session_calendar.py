"""Session calendar: market holidays and instrument market codes.

Revision ID: 0002_session_calendar
Revises: 0001_foundation
Create Date: 2026-08-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_session_calendar"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column(
        "instruments",
        sa.Column("market_code", sa.String(16), nullable=False, server_default="FX"),
    )
    op.create_index("ix_instruments_market_code", "instruments", ["market_code"])

    op.create_table(
        "market_holidays",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("market_code", sa.String(16), nullable=False),
        sa.Column(
            "instrument_id",
            UUID,
            sa.ForeignKey("instruments.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("holiday_date", sa.Date, nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default="closed"),
        sa.Column("name", sa.String(120), nullable=False, server_default=""),
        sa.Column("opens_at", sa.Time, nullable=True),
        sa.Column("closes_at", sa.Time, nullable=True),
        sa.Column("is_confirmed", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("source", sa.Text, nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "market_code", "instrument_id", "holiday_date", name="uq_market_holiday_day"
        ),
    )
    op.create_index(
        "ix_market_holidays_lookup", "market_holidays", ["market_code", "holiday_date"]
    )


def downgrade() -> None:
    op.drop_table("market_holidays")
    op.drop_index("ix_instruments_market_code", table_name="instruments")
    op.drop_column("instruments", "market_code")
