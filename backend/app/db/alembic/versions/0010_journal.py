"""Give the journal somewhere to live.

Revision ID: 0010_journal
Revises: 0009_equity_series
Create Date: 2026-08-15

`app/brain/journal.py` has been complete and tested since early in this project
and nothing ever stored what it produced, so the page for it stayed grey and
every decision the system made vanished when the process restarted.

That matters more now than it did. The live loop records a decision every cycle
and the only thing that can prove or kill the edge is the forward series those
decisions make. A journal with no storage is a forward measurement that resets
every deploy.

The shape follows the module rather than the other way round. Before, during
and after are separate JSON columns because they are written at different times
by different events - a thesis at the open, observations while it runs, an
outcome at the close - and flattening them would mean rewriting the whole row
to add one observation.

`probability` is a column of its own rather than only a key inside the before
blob, because the one query this table exists to answer is "was the system's
confidence calibrated", and that cannot be a scan of every JSON document.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_journal"
down_revision = "0009_equity_series"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB


def upgrade() -> None:
    op.create_table(
        "journal_entries",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False, index=True),
        sa.Column("decision", sa.String(16), nullable=False),
        # The broker login this decision was made for. A string, and not a
        # foreign key, for the same reason the equity samples are not: a
        # decision can be recorded before anybody registers the account it
        # belongs to, and dropping those loses the earliest entries.
        sa.Column("account_key", sa.String(64), nullable=True, index=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        # Pulled out of the blob because "was the confidence calibrated" is the
        # question this table exists to answer, and it cannot be a scan of
        # every JSON document. Nullable, because a decision that recorded no
        # probability must not be stored as 0.5 - that invents a forecast the
        # system never made, which is worse than none because it is
        # indistinguishable from one it did.
        sa.Column("probability", sa.Float, nullable=True),
        sa.Column("r_multiple", sa.Float, nullable=True),
        sa.Column("outcome", sa.String(24), nullable=True, index=True),
        # Whether this row is the system's decision or the random control's
        # entry on the same bar. Both are stored in one table so a comparison
        # is a filter rather than a join between two shapes that can drift.
        sa.Column("arm", sa.String(16), nullable=False, server_default="rule"),
        sa.Column("before", JSONB, nullable=False, server_default="{}"),
        sa.Column("during", JSONB, nullable=False, server_default="{}"),
        sa.Column("after", JSONB, nullable=True),
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

    # The comparison query: one arm's outcomes over a window. Without this it
    # is a full scan of every decision ever made.
    op.create_index(
        "ix_journal_arm_time", "journal_entries", ["arm", "opened_at"]
    )
    # One decision per symbol per bar per arm. The loop republishes the same
    # decision whenever a cycle overlaps the previous one, and a duplicated
    # entry inflates the sample the whole measurement rests on.
    op.create_unique_constraint(
        "uq_journal_symbol_bar_arm",
        "journal_entries",
        ["symbol", "opened_at", "arm"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_journal_symbol_bar_arm", "journal_entries", type_="unique")
    op.drop_index("ix_journal_arm_time", table_name="journal_entries")
    op.drop_table("journal_entries")
