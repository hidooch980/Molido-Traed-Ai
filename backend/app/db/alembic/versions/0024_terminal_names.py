"""What the operator calls a terminal, as opposed to what it is.

Revision ID: 0024_terminal_names
Revises: 0023_account_policy
Create Date: 2026-09-04

The fleet is `term-b` through `term-h`, which is correct and says nothing:
which one holds the five hundred dollars, which one is the cent account.
Working that out meant opening each page and reading a login, and the logins
differ by one digit in the middle.

The label is decoration. Nothing routes on it - the key stays the identity,
and an empty table therefore changes nothing anywhere.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_terminal_names"
down_revision = "0023_account_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "terminal_names",
        sa.Column("id", sa.Uuid(), primary_key=True),
        # The terminal key exactly as `bridge_dirs` publishes it. Unique
        # because a terminal with two names has none.
        sa.Column("terminal", sa.String(64), nullable=False, unique=True),
        sa.Column("label", sa.String(60), nullable=False, server_default=""),
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
    )


def downgrade() -> None:
    op.drop_table("terminal_names")
