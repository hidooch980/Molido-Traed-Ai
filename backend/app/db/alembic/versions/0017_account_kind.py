"""Which kind of account each row is, and a rulebook that may be absent.

Revision ID: 0017_account_kind
Revises: 0016_journal_timeframe
Create Date: 2026-08-26

The table held prop challenges only, and every row was required to name a
transcribed rulebook. That made two accounts the holder actually trades
unrecordable: a funded prop account, and an ordinary live account at a broker.

The funded case was awkward rather than impossible - the rulebooks already
carry funded phases, so a row could point at one. The live case was impossible.
Nobody but the holder sets the limits on their own money, so there is no
rulebook to name, and requiring one would have meant inventing a prop programme
for an account that is not on any.

So `rulebook_key` becomes nullable, and the meaning of a null is pinned by the
service rather than left to the reader: a prop account without a rulebook is
refused, so a null here says "nothing external imposes limits on this account"
and never "somebody forgot to fill this in".

Existing rows are stamped `challenge`. That is what they are - this column is
being added to a table that could not have held anything else - and defaulting
them to any other kind would be inventing a history.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_account_kind"
down_revision = "0016_journal_timeframe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "challenge_accounts",
        sa.Column(
            "kind", sa.String(16), nullable=False, server_default="challenge"
        ),
    )
    op.create_index(
        "ix_challenge_accounts_kind", "challenge_accounts", ["kind"]
    )
    op.alter_column(
        "challenge_accounts",
        "rulebook_key",
        existing_type=sa.String(80),
        nullable=True,
    )


def downgrade() -> None:
    # Rows with no rulebook cannot survive the old shape, and there is no
    # honest value to give them - a live account belongs to no programme. They
    # go, rather than being relabelled as challenges nobody is sitting.
    op.execute("DELETE FROM challenge_accounts WHERE rulebook_key IS NULL")
    op.alter_column(
        "challenge_accounts",
        "rulebook_key",
        existing_type=sa.String(80),
        nullable=False,
    )
    op.drop_index("ix_challenge_accounts_kind", table_name="challenge_accounts")
    op.drop_column("challenge_accounts", "kind")
