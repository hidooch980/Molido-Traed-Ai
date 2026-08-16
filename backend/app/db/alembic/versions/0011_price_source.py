"""Run the measurement on both price series at once.

Revision ID: 0011_price_source
Revises: 0010_journal
Create Date: 2026-08-16

The broker's prices and the public feed's differ by 33-39% of the stop distance
on every major pair - measured, not estimated, over 490 shared hourly bars. A
rule whose entry, stop and target come from one series and whose fills come
from the other starts a third of the way to its stop in a random direction, and
the edge being measured is 0.021 R.

So one series is not enough to answer the question. Yahoo has the universe the
rule was tested on and two years of history, and is a market nobody can trade
in. The broker has the prices that actually fill and three weeks of history
across 23 instruments. Each answers half the question.

Both run. The difference between them is itself the measurement nobody has:
how much of the edge the gap between quoted and filled prices eats.

`price_source` is a column rather than a suffix on `arm`. Encoding two facts in
one string is how a filter that meant "the control arm" quietly starts matching
"control on broker prices" as well.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_price_source"
down_revision = "0010_journal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "journal_entries",
        sa.Column(
            "price_source",
            sa.String(24),
            nullable=False,
            server_default="yfinance",
        ),
    )

    # The old constraint allowed one row per (symbol, bar, arm). With two price
    # series that is one row too few: the rule's decision on Yahoo prices and
    # its decision on broker prices are different decisions about the same bar.
    op.drop_constraint("uq_journal_symbol_bar_arm", "journal_entries", type_="unique")
    op.create_unique_constraint(
        "uq_journal_symbol_bar_arm_source",
        "journal_entries",
        ["symbol", "opened_at", "arm", "price_source"],
    )

    # The comparison query filters on all three. Without this it is a full scan
    # of every decision ever recorded.
    op.create_index(
        "ix_journal_source_arm_time",
        "journal_entries",
        ["price_source", "arm", "opened_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_journal_source_arm_time", table_name="journal_entries")
    op.drop_constraint(
        "uq_journal_symbol_bar_arm_source", "journal_entries", type_="unique"
    )
    op.create_unique_constraint(
        "uq_journal_symbol_bar_arm",
        "journal_entries",
        ["symbol", "opened_at", "arm"],
    )
    op.drop_column("journal_entries", "price_source")
