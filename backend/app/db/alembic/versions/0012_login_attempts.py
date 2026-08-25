"""Record every sign-in attempt, so the guard has something to count.

Revision ID: 0012_login_attempts
Revises: 0011_price_source
Create Date: 2026-08-25

There was nothing between a password guess and the next password guess. The
sign-in route checked one password per request, returned the same refusal for
every kind of failure - which is right - and then accepted the next request
immediately. An address and a wordlist were the whole attack, and the only
evidence it had happened was a `last_login_at` that changed if it worked.

Two indexes and one table fix that, because the guard's question is a count:
how many failures for this address, or from this caller, since a moment. Both
are composite and end in the timestamp, which is the shape of the query.

Deliberately not stored in `audit_events`, which already exists and already
records things. That table's payload is JSON, and counting failures by caller
address would mean filtering inside a JSON column on the hot path of every
sign-in. The two are kept for different reasons: this one is read to make a
decision and can be pruned the moment its rows fall outside the longest
window; the audit row is the record and stays.

No password reaches this table. Not hashed, not truncated, not its length.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_login_attempts"
down_revision = "0011_price_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        # 320 is the maximum length of an email address. Not a foreign key to
        # `users`: most failed attempts name an account that does not exist,
        # and a guard blind to those is blind to enumeration.
        sa.Column("subject", sa.String(320), nullable=False),
        # Nullable: a deployment behind a proxy that forwards no address leaves
        # this empty, and the guard skips the address rule rather than counting
        # every such caller in one shared bucket.
        sa.Column("address", sa.String(64), nullable=True),
        sa.Column("succeeded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(256), nullable=True),
    )
    op.create_index(
        "ix_login_attempts_subject", "login_attempts", ["subject", "attempted_at"]
    )
    op.create_index(
        "ix_login_attempts_address", "login_attempts", ["address", "attempted_at"]
    )
    # For the pruner, which deletes by age alone.
    op.create_index("ix_login_attempts_time", "login_attempts", ["attempted_at"])


def downgrade() -> None:
    op.drop_index("ix_login_attempts_time", table_name="login_attempts")
    op.drop_index("ix_login_attempts_address", table_name="login_attempts")
    op.drop_index("ix_login_attempts_subject", table_name="login_attempts")
    op.drop_table("login_attempts")
