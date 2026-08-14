"""Record what the account was worth, so a trailing floor can be placed.

Revision ID: 0009_equity_series
Revises: 0008_referrals_and_verification
Create Date: 2026-08-15

The bridge has published equity every twenty seconds since it was built and
nothing kept it, so there was no series to take a maximum of. `peak_equity`
returned None honestly, and every trailing-drawdown check refused - correctly,
because the right answer to "how much rope is left" when nobody has been
watching is that nobody knows.

FTMO's floor trails "the highest account balance achieved at 00:00 CE(S)T of
any preceding trading day", which is not the same as the highest equity ever
seen. Both are recorded here: `equity` for the live picture, `balance` because
that is what the rule is actually written against. Deriving one from the other
afterwards is not possible, and picking only one would mean re-reading the
provider's terms and discovering the wrong column was kept.

`recorded_at` is when the snapshot was taken, not when it was written. Those
diverge whenever the writer falls behind, and a peak attributed to the wrong
minute puts the floor in the wrong place on exactly the day it matters.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_equity_series"
down_revision = "0008_referrals_and_verification"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "equity_samples",
        sa.Column("id", UUID, primary_key=True),
        # The broker login, as a string. Not a foreign key to challenge_accounts:
        # an account can be connected and publishing long before anybody
        # registers it as a challenge, and losing those samples would leave a
        # gap in the series exactly where the account was newest.
        sa.Column("account_key", sa.String(64), nullable=False, index=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("equity", sa.Numeric(18, 2), nullable=False),
        # Both, because FTMO's trailing floor is written against balance at
        # 00:00 and the live picture needs equity. Neither derives from the
        # other after the fact.
        sa.Column("balance", sa.Numeric(18, 2), nullable=False),
        sa.Column("margin", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("open_positions", sa.Integer, nullable=False, server_default="0"),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
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

    # The query this table exists to answer: the peak for one account over a
    # window. Without the composite index that is a full scan on a table which
    # grows by three rows a minute per account.
    op.create_index(
        "ix_equity_samples_account_time",
        "equity_samples",
        ["account_key", "recorded_at"],
    )

    # One sample per account per instant. The bridge republishes the same
    # snapshot when the writer runs faster than the terminal does, and a
    # duplicated peak is not wrong but a duplicated *count* is - it makes a
    # quiet hour look like a busy one to anything measuring sample density.
    op.create_unique_constraint(
        "uq_equity_samples_account_instant",
        "equity_samples",
        ["account_key", "recorded_at"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_equity_samples_account_instant", "equity_samples", type_="unique"
    )
    op.drop_index("ix_equity_samples_account_time", table_name="equity_samples")
    op.drop_table("equity_samples")
