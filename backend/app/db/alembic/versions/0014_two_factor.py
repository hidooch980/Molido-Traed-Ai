"""A second factor, and a way back in when the phone is gone.

Revision ID: 0014_two_factor
Revises: 0013_human_challenges
Create Date: 2026-08-25

A password is a secret that travels: typed on hotel wifi, saved in a browser on
a shared laptop, reused on a forum that gets breached. Once it has leaked there
is nothing between whoever holds it and an account that can connect a broker.

Three columns and one table.

`totp_secret` cannot be hashed - the server has to compute the same code the
phone does - so it is stored as issued. That is a real trade and it is written
here rather than glossed: Postgres publishes no host port on this deployment,
and the nightly dump is the only copy that leaves the machine. Encrypting it
would need a key the application can read, which is the same threat model with
one more file in it.

`totp_confirmed_at` exists because issuing a secret is not enrolling. Enrolment
finishes when the user proves the app works by typing a code it produced. An
account with a secret and no confirmation has no second factor, and must not be
locked out of itself by a QR code somebody scanned and then closed.

`totp_last_step` is the replay guard. A code is valid for its whole 30-second
window, so without recording which step was spent the same six digits work
twice - and the second time is the one somebody read over a shoulder.
`BigInteger` because a step is a unix time divided by 30, which passed the
32-bit range in 1972.

`recovery_codes` is the way back in. A second factor that cannot be recovered
is a way to lose an account, and here losing the account means losing the
dashboard the kill switch is reached from. Hashed like passwords, because a
recovery code is a password that bypasses the second factor.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_two_factor"
down_revision = "0013_human_challenges"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("totp_secret", sa.String(64), nullable=True))
    op.add_column(
        "users", sa.Column("totp_confirmed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("users", sa.Column("totp_last_step", sa.BigInteger(), nullable=True))

    op.create_table(
        "recovery_codes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("code_hash", sa.String(255), nullable=False),
        # Stamped on the code that was spent rather than decrementing a
        # counter, so "which are left" and "when was each used" are both
        # answerable and a replay meets a row that already carries a time.
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    # The only query: this user's unused codes.
    op.create_index("ix_recovery_codes_user", "recovery_codes", ["user_id", "used_at"])


def downgrade() -> None:
    op.drop_index("ix_recovery_codes_user", table_name="recovery_codes")
    op.drop_table("recovery_codes")
    op.drop_column("users", "totp_last_step")
    op.drop_column("users", "totp_confirmed_at")
    op.drop_column("users", "totp_secret")
