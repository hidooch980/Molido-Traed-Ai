"""What the operator calls a terminal, as opposed to what it is.

The fleet is `term-b` through `term-h`. Those names are correct, unique, and
say nothing: which one holds the five hundred dollars, which one is the cent
account, which one is the demo that exists to be broken. Working that out
meant opening each page and reading the login, and the logins differ by one
digit in the middle.

So a terminal gets a second name, and the second name is decoration.

**The key stays the identity.** Nothing routes on a label - not an order, not
a bridge directory, not a policy row. The directory *is* the account, as the
provider module says at length, and a display name that could select one
would be a way to send money to the wrong terminal by typing a word.

That is also why a label may not be another terminal's key, and why two
terminals may not share one. Both would produce a page where two rows read
the same, and the whole reason this table exists is that rows reading the
same is how an operator acts on the wrong account.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TerminalName(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One terminal's display name, or no row at all."""

    __tablename__ = "terminal_names"

    #: The terminal key, exactly as `bridge_dirs` publishes it. Unique
    #: because a terminal with two names has none.
    terminal: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    #: What to show instead of the key. Bounded because it lands in a table
    #: column on a page, not in a paragraph.
    label: Mapped[str] = mapped_column(String(60), nullable=False, default="")

    #: Who last changed it. Cheap to record and the only way to answer "who
    #: called it that" once a name has confused somebody.
    changed_by: Mapped[str] = mapped_column(String(120), nullable=False, default="")

    def as_dict(self) -> dict[str, Any]:
        return {
            "terminal": self.terminal,
            "label": self.label,
            "changed_by": self.changed_by or None,
            "changed_at": self.updated_at.isoformat() if self.updated_at else None,
        }
