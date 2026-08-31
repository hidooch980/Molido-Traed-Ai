"""Which brain a journal entry belongs to.

Revision ID: 0018_journal_strategy
Revises: 0017_account_kind
Create Date: 2026-08-31

One recorder meant one brain, so nothing in the journal needed to say whose
decision a row was. Recording the candidate rules beside the incumbent makes
that omission a defect in the same two ways the missing timeframe was.

The unique key was `(symbol, opened_at, arm, price_source, timeframe)`. Two
rules that disagree about one symbol on one bar - which a reversal rule and a
momentum rule do by construction - collide on that key, and the second one is
silently discarded as a duplicate. The measurement would have looked like it
was recording three brains while recording whichever ran first.

And the trading would have been mixed. An account assigned one brain must see
only that brain's decisions; without the column, the filter cannot exist and
every account trades a blend nobody designed.

Existing rows are stamped cross-sectional-stretch because that is what they
are: the forward recorder has only ever run that rule, and its name is already
inside every row's `before` payload. Defaulting them to anything else would be
inventing a provenance.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018_journal_strategy"
down_revision = "0017_account_kind"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "journal_entries",
        sa.Column(
            "strategy",
            sa.String(48),
            nullable=False,
            server_default="cross-sectional-stretch",
        ),
    )

    # Replaced rather than added beside: the old key would still reject the
    # second brain's disagreement at a shared instant, which is the defect.
    op.drop_constraint(
        "uq_journal_symbol_bar_arm_source_tf", "journal_entries", type_="unique"
    )
    op.create_unique_constraint(
        "uq_journal_symbol_bar_arm_source_tf_strat",
        "journal_entries",
        ["symbol", "opened_at", "arm", "price_source", "timeframe", "strategy"],
    )

    # Every read that separates the brains goes through this.
    op.create_index(
        "ix_journal_strategy_time", "journal_entries", ["strategy", "opened_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_journal_strategy_time", table_name="journal_entries")
    op.drop_constraint(
        "uq_journal_symbol_bar_arm_source_tf_strat",
        "journal_entries",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_journal_symbol_bar_arm_source_tf",
        "journal_entries",
        ["symbol", "opened_at", "arm", "price_source", "timeframe"],
    )
    op.drop_column("journal_entries", "strategy")
