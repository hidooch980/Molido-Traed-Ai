"""A MetaTrader terminal that publishes into this platform.

Bridge directories were configured through `MOLIDO_MT5_BRIDGE_DIRS`, which is
the right shape for one terminal and the wrong shape for eleven: every new
account meant editing an environment file, rebuilding a container and asking
somebody with a shell to do it. The person who owns the accounts could not add
one, and the person who could had no reason to know which account was which.

So a terminal registers itself here, and its directory follows from its key
rather than being chosen. That is deliberate. The provider's own warning is
that the directory *is* the account - the published files carry no identity of
their own - so letting a caller name both the key and the path would let two
accounts be pointed at one folder, and the symptom of that is one terminal's
balance being used to size the other's orders.

**No credentials, ever.** A terminal record is a name, a key and whether it is
still in use. The broker login and password live in MetaTrader's own
configuration and nowhere else - this platform never needs them, and a table
that could hold them is a table somebody will eventually put them in.

The API key the expert authenticates with is not here either. Those live in the
key store with every other key, are hashed there, and are revoked there.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UUIDType

#: What a key may contain, and it is narrow on purpose: the key becomes a
#: directory name. Anything that can express a path separator or a parent
#: reference is a key that can write outside the bridge root.
KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}[a-z0-9]$")


class Terminal(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "terminals"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_terminals_tenant_key"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )

    #: The name the expert publishes under, and the directory it publishes
    #: into. Lower case and restricted by `KEY_PATTERN`, because a key that
    #: differs from another only by case is two directories on Linux and one
    #: on the machine somebody typed it on.
    key: Mapped[str] = mapped_column(String(64), nullable=False)

    #: What the holder calls it. Theirs, and it can say "FundedNext 100k
    #: phase 2" where the key has to say `fundednext-100k-p2`.
    label: Mapped[str] = mapped_column(String(120), nullable=False, default="")

    #: Which broker, as the holder describes it. Recorded rather than derived:
    #: the terminal publishes its own server name, and the two disagreeing is
    #: worth seeing rather than worth hiding.
    broker: Mapped[str] = mapped_column(String(120), nullable=False, default="")

    #: What kind of money this is. Free text rather than an enum, because the
    #: categories that matter here are the holder's - "challenge", "funded",
    #: "live", "demo" - and an enum would need a migration every time a prop
    #: firm invented a product name.
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="")

    #: Switched off rather than deleted. The bridge directory keeps whatever it
    #: last published, and a decision recorded against a terminal that no
    #: longer resolves is a decision about nobody.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
