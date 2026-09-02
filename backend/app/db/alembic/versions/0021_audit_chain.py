"""Chain the audit events, from here on.

Revision ID: 0021_audit_chain
Revises: 0020_telegram_config
Create Date: 2026-09-02

`observability.AuditTrail` hashed every entry to the one before it and could
prove an edit - and lived in memory, in a process that restarts. The table
that actually kept the events had no hash at all, so `audit_chain_intact`
could only ever be "could not be determined".

Three nullable columns on the existing rows, never rewritten: `sequence`,
`previous_hash`, `entry_hash`. Rows written before this migration keep NULLs
and are reported as pre-chain - a count, not a verdict. Manufacturing hashes
for them would be manufacturing continuity, which is the thing a chain exists
to make detectable.

One single-row `audit_chain_head` table serialises appends across the API,
the collector and the chat process: whoever appends locks the row, reads the
last hash, writes the next. A chain with two writers and no lock forks, and
a forked chain verifies as broken through nobody's fault.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021_audit_chain"
down_revision = "0020_telegram_config"
branch_labels = None
depends_on = None

GENESIS = "0" * 64


def upgrade() -> None:
    op.add_column("audit_events", sa.Column("sequence", sa.BigInteger(), nullable=True))
    op.add_column("audit_events", sa.Column("previous_hash", sa.String(64), nullable=True))
    op.add_column("audit_events", sa.Column("entry_hash", sa.String(64), nullable=True))
    op.create_index(
        "ix_audit_events_sequence", "audit_events", ["sequence"], unique=True
    )
    op.create_table(
        "audit_chain_head",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("entry_hash", sa.String(64), nullable=False),
    )
    op.execute(
        sa.text(
            "INSERT INTO audit_chain_head (id, sequence, entry_hash) "
            f"VALUES (1, -1, '{GENESIS}')"
        )
    )


def downgrade() -> None:
    op.drop_table("audit_chain_head")
    op.drop_index("ix_audit_events_sequence", table_name="audit_events")
    op.drop_column("audit_events", "entry_hash")
    op.drop_column("audit_events", "previous_hash")
    op.drop_column("audit_events", "sequence")
