"""What one account trades and how much it risks, set from the site.

These two settings lived in environment variables, which meant changing
either one was an SSH session, an edit to `.env.prod`, and a container
recreate - the env file is read when the process starts, so nothing less
than a recreate takes effect. Twice in one day the operator had to ask an
engineer to change a number, and both times the recreate killed the trading
cycle that was in flight.

A setting nobody can change is a setting nobody tunes. So they live here,
where a page can write them and the next cycle reads them.

One row per login, and the login is the key rather than the terminal name:
a terminal is a piece of infrastructure and an account is the thing with
money in it. Moving an account to a different terminal must not silently
move its risk limit to whoever takes the old one.

Absent is not zero. A login with no row here falls back to the deployment's
own figures, which is what every account did before this table existed - so
an empty table changes nothing, and that is the point.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import JSONType


class AccountPolicy(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One account's own strategy assignment and risk, or nothing."""

    __tablename__ = "account_policy"

    #: The broker login, as a string. Logins exceed 32 bits on some brokers
    #: and carry leading zeros on others; anything that stores them as
    #: machine integers eventually mangles one, and a mangled login is an
    #: account whose settings silently stop applying.
    login: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)

    #: Which brains this account trades. Empty means "not set here" and the
    #: deployment's own assignment applies - it does not mean "trade
    #: nothing", which is a decision and belongs to the kill switch.
    strategies: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)

    #: Percent of equity behind one stop. None means not set here.
    #:
    #: Nullable rather than defaulted to the fleet figure: a stored copy of
    #: the default would keep applying after somebody changed the default,
    #: and the account would quietly diverge from the fleet it was never
    #: meant to leave.
    risk_percent: Mapped[float | None] = mapped_column(Float, nullable=True)

    #: Who last changed it. An account's risk is the one number worth being
    #: able to attribute later.
    changed_by: Mapped[str] = mapped_column(String(120), default="", nullable=False)

    def as_dict(self) -> dict[str, Any]:
        return {
            "login": self.login,
            "strategies": list(self.strategies or []),
            "risk_percent": self.risk_percent,
            "changed_by": self.changed_by or None,
            "changed_at": self.updated_at.isoformat() if self.updated_at else None,
        }
