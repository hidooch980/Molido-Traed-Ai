"""What one account is allowed to trade, set from the site.

Revision ID: 0027_account_symbols
Revises: 0026_tradingview
Create Date: 2026-09-21

`account_policy` already carries one account's own brains and risk apart
from the deployment's; the instruments an account may trade sat only in one
env var (`MOLIDO_TRADED_SYMBOLS`) shared by the whole fleet. An owner who
wants a single account confined to gold and EURUSD - to run it as its own
measurement, or because that is the only book they trust with a bigger
position - had no way to say so without narrowing every other account too.

Empty means the same as every other column here: not set for this account,
the deployment's own list (or no list) applies. A stored empty list is not a
way to stop an account from trading anything - that is the kill switch.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0027_account_symbols"
down_revision = "0026_tradingview"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "account_policy",
        sa.Column(
            "symbols",
            postgresql.JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("account_policy", "symbols")
