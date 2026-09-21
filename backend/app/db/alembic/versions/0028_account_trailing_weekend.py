"""Trailing and the weekend lock, self-service from the account page.

Revision ID: 0028_account_trailing_weekend
Revises: 0027_account_symbols
Create Date: 2026-09-21

Two more account-level settings lived only in an env var: which accounts
run the trailing-stop worker (`MOLIDO_TRAILING_LOGINS`) and which are prop
challenges the weekend lock must hold (`MOLIDO_WEEKEND_LOCK_LOGINS`). Both
meant an owner adding a new account had to ask an engineer to edit
`.env.prod` and recreate the container before the new login was covered.

Trailing gets its own column here, following `symbols` and `strategies`:
off by default, on when an account asks for it, changeable from the page.

The weekend lock gets no new column - a registered challenge account
(`app/services/challenge_accounts.py`) is now locked automatically, because
`_is_prop_account` already answers "is this login a prop challenge" with
the same login-matching `_challenge_gate` trusts to apply a rulebook's
limits in the first place. The env var still works, additively, for an
account that wants the lock without being registered as a challenge.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028_account_trailing_weekend"
down_revision = "0027_account_symbols"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "account_policy",
        sa.Column("trailing", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("account_policy", "trailing")
