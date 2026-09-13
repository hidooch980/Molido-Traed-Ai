"""A rulebook the holder writes, beside the ten transcribed from firms' pages.

Revision ID: 0025_custom_rulebooks
Revises: 0024_terminal_names
Create Date: 2026-09-09

The transcribed rulebooks carry a source URL and a retrieval date, and nothing
in the deployment may edit them - a number that can be changed here stops
being evidence of what the firm published. But a holder rehearsing on a demo,
or trading their own money to a discipline they set, has real limits nobody
published, and the only way to enforce those was to register the account
against somebody else's programme and quietly mean something different.

The table starts empty and an empty table changes nothing: every account keeps
resolving to the transcribed rulebook it already names.

Keys carry a `custom:` prefix so the two kinds can never collide, which is why
this needs no foreign key to anything - `challenge_accounts.rulebook_key` is a
string, and the prefix is what tells a reader which side it points at.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0025_custom_rulebooks"
down_revision = "0024_terminal_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "custom_rulebooks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(80), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        # One JSON document rather than a column per rule. Three states have to
        # survive the round trip - nobody said, deliberately not imposed, and a
        # value - and two of those are an empty column in SQL.
        sa.Column(
            "rules",
            postgresql.JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("notes", sa.String(2000), nullable=False, server_default=""),
        sa.Column("changed_by", sa.String(120), nullable=False, server_default=""),
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
        sa.UniqueConstraint("tenant_id", "key", name="uq_custom_rulebooks_tenant_key"),
    )
    op.create_index("ix_custom_rulebooks_tenant_id", "custom_rulebooks", ["tenant_id"])
    op.create_index("ix_custom_rulebooks_key", "custom_rulebooks", ["key"])


def downgrade() -> None:
    op.drop_index("ix_custom_rulebooks_key", table_name="custom_rulebooks")
    op.drop_index("ix_custom_rulebooks_tenant_id", table_name="custom_rulebooks")
    op.drop_table("custom_rulebooks")
