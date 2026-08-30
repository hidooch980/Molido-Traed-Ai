"""Which timeframe a journal entry was decided on.

Revision ID: 0016_journal_timeframe
Revises: 0015_terminals
Create Date: 2026-08-26

The forward measurement ran on hourly bars alone, so nothing in the journal
needed to say which timeframe an entry came from - there was only one. Widening
it to four made that omission a bug in two ways at once.

The unique key was `(symbol, opened_at, arm, price_source)`. Every hour the
hourly, fifteen, five and one minute bars all close on the same timestamp, so
at those instants four entries collide on one key and three are silently
discarded as duplicates. The measurement would have looked like it was
recording four timeframes while recording roughly one.

And the readings would have been mixed. The whole reason widening is safe is
that "no edge at one minute" must be an answer about one minute - if a
five-minute entry and an hourly one land in the same undifferentiated series,
the cheap timeframe's costs contaminate the expensive one's result and neither
number means anything.

Existing rows are stamped H1 because that is what they are: this column is
being added on a deployment whose forward recorder has only ever run hourly,
and the setting that made it so is in the history beside this file. Defaulting
them to anything else would be inventing a provenance.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_journal_timeframe"
down_revision = "0015_terminals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "journal_entries",
        sa.Column("timeframe", sa.String(8), nullable=False, server_default="H1"),
    )

    # Replaced rather than added beside: the old key would still reject the
    # second timeframe at a shared timestamp, which is the whole defect.
    op.drop_constraint(
        "uq_journal_symbol_bar_arm_source", "journal_entries", type_="unique"
    )
    op.create_unique_constraint(
        "uq_journal_symbol_bar_arm_source_tf",
        "journal_entries",
        ["symbol", "opened_at", "arm", "price_source", "timeframe"],
    )

    # Every read that separates the timeframes goes through this.
    op.create_index(
        "ix_journal_timeframe_time", "journal_entries", ["timeframe", "opened_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_journal_timeframe_time", table_name="journal_entries")
    op.drop_constraint(
        "uq_journal_symbol_bar_arm_source_tf", "journal_entries", type_="unique"
    )
    op.create_unique_constraint(
        "uq_journal_symbol_bar_arm_source",
        "journal_entries",
        ["symbol", "opened_at", "arm", "price_source"],
    )
    op.drop_column("journal_entries", "timeframe")
