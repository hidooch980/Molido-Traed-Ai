"""What one account trades and how much it risks, set from the site.

Revision ID: 0023_account_policy
Revises: 0022_slo_observations
Create Date: 2026-09-03

Both settings lived in environment variables, so changing either was an SSH
session and a container recreate - the env file is read when the process
starts. Twice in one day an operator had to ask an engineer to change a
number, and both times the recreate killed the cycle that was in flight.

The table starts empty and an empty table changes nothing: a login with no
row falls back to the deployment's own figures, which is what every account
did before this existed.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0023_account_policy"
down_revision = "0022_slo_observations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_policy",
        sa.Column("id", sa.Uuid(), primary_key=True),
        # The broker login as text. Logins exceed 32 bits on some brokers and
        # carry leading zeros on others; stored as a machine integer, one of
        # them eventually mangles, and a mangled login is an account whose
        # settings silently stop applying.
        sa.Column("login", sa.String(32), nullable=False, unique=True),
        sa.Column(
            "strategies",
            postgresql.JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=False,
            server_default="[]",
        ),
        # Nullable rather than defaulted to the fleet figure: a stored copy of
        # the default would keep applying after somebody changed the default,
        # and the account would quietly diverge from the fleet it never meant
        # to leave.
        sa.Column("risk_percent", sa.Float(), nullable=True),
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
    op.drop_table("account_policy")
