"""Issue a proof of work, and let it be spent exactly once.

Revision ID: 0013_human_challenges
Revises: 0012_login_attempts
Create Date: 2026-08-25

A table rather than a signed token, for one property. A stateless challenge is
cheaper to implement and fails at the only thing this is for: an attacker
solves one, replays the solution on every request until it expires, and a
five-minute window becomes five minutes of unimpeded guessing.

So a challenge is a row and verifying deletes it. The rows are small, live for
minutes, and are pruned by expiry - which is the one index this table needs,
because expiry is the only thing ever scanned. Lookups are by primary key.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_human_challenges"
down_revision = "0012_login_attempts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "human_challenges",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("salt", sa.String(64), nullable=False),
        # Stored per challenge, not read from configuration at verify time:
        # raising the setting would otherwise invalidate every challenge
        # already in flight, which reads to the caller as a broken login.
        sa.Column("difficulty", sa.Integer(), nullable=False),
        # So a proof solved for the sign-in form cannot be spent on the
        # registration form, which would make the cheapest form the mint.
        sa.Column("purpose", sa.String(32), nullable=False),
    )
    op.create_index("ix_human_challenges_expiry", "human_challenges", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_human_challenges_expiry", table_name="human_challenges")
    op.drop_table("human_challenges")
