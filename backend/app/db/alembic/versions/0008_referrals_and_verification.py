"""Account verification, and the referral tree it makes trustworthy.

Revision ID: 0008_referrals_and_verification
Revises: 0007_incidents
Create Date: 2026-08-14

These two arrive in one migration because they are one mechanism. A referral
system that pays out on registration is a machine for printing points: the
referrer registers their own downline and collects. What stops that is proof
the new account belongs to somebody else, and control of a real inbox is the
cheapest such proof available here - so a referral is confirmed by the same
event that verifies the account, and by nothing else.

`referred_by_id` has no ON DELETE CASCADE. Deleting a referrer must not delete
the people they introduced; the column is SET NULL so the tree loses a branch
rather than the accounts under it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_referrals_and_verification"
down_revision = "0007_incidents"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    # ------------------------------------------------------------ users
    op.add_column("users", sa.Column("referral_code", sa.String(16), nullable=True))
    op.add_column("users", sa.Column("referred_by_id", UUID, nullable=True))
    op.add_column(
        "users", sa.Column("referral_confirmed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "users", sa.Column("points", sa.Integer, nullable=False, server_default="0")
    )

    # Unique, because the code is what a stranger types to say who sent them.
    # Two accounts sharing one would silently credit whichever the query found
    # first, which is a bug nobody notices until somebody is owed points.
    op.create_index("ix_users_referral_code", "users", ["referral_code"], unique=True)
    op.create_index("ix_users_referred_by_id", "users", ["referred_by_id"])
    op.create_foreign_key(
        "fk_users_referred_by",
        "users",
        "users",
        ["referred_by_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ------------------------------------------------- verification tokens
    op.create_table(
        "account_tokens",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "user_id",
            UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # What the token is for. A verification token that also resets a
        # password is a verification link that takes over an account.
        sa.Column("purpose", sa.String(32), nullable=False),
        # The hash, never the token. A leaked database must not hand out
        # working links, and this table is the one an email address is joined
        # to - exactly the table an attacker reads first.
        sa.Column("token_hash", sa.String(255), nullable=False),
        # The non-secret half, so a lookup does not need to scan and compare
        # every row. Same shape the session tokens already use.
        sa.Column("token_prefix", sa.String(16), nullable=False, index=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
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
    op.drop_table("account_tokens")
    op.drop_constraint("fk_users_referred_by", "users", type_="foreignkey")
    op.drop_index("ix_users_referred_by_id", table_name="users")
    op.drop_index("ix_users_referral_code", table_name="users")
    op.drop_column("users", "points")
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "referral_confirmed_at")
    op.drop_column("users", "referred_by_id")
    op.drop_column("users", "referral_code")
