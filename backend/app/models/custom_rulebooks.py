"""A rulebook the holder wrote, rather than one transcribed from a firm's page.

`app.brain.rulebooks` holds ten rulebooks read off published pages on stated
dates. Those are a record of somebody else's document and nothing in this
deployment may edit them: a number that can be changed here is a number that
stops being evidence of what the firm published, and the whole point of
carrying the source URL and the retrieval date is that the transcription can
be checked against the page it came from.

This table is the other kind. A holder rehearsing on a demo, or trading their
own money to a discipline they set themselves, has real limits that no firm
published - and before this existed the only way to enforce them was to
register the account against somebody else's programme and quietly mean
something different by it.

**The two kinds never share a namespace.** Every key here is stored with a
`custom:` prefix, so a custom rulebook cannot shadow `fundednext-stellar-1step`
and a log line naming a key says which kind it was without a lookup.

**The three states of a rule survive the round trip.** `None` means nobody
said and blocks; `NOT_IMPOSED` means this rulebook deliberately caps nothing;
a number is a number. Two of those look like an empty column in SQL, so the
rules are held in one JSON document where the marker can stay a word - the
same shape `_publish` already uses when a rulebook is handed to a caller.

**Authoring is not confirming.** A custom rulebook is still born
unconfirmed, and the account that uses it still has to be confirmed the way
any other account is. Writing a limit down is not the same act as checking it
against the account it will end, and collapsing the two would remove the one
gate that exists because a mistyped daily loss does not fail - it passes a
trade that ends the account.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import JSONType, UUIDType

#: What every custom key begins with. Checked on the way in rather than
#: assumed, so no row can exist whose key would collide with a transcribed one.
KEY_PREFIX = "custom:"


class CustomRulebook(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "custom_rulebooks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_custom_rulebooks_tenant_key"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )

    #: `custom:<slug>`, unique per tenant. The prefix is stored rather than
    #: added on the way out, because the key is written into
    #: `challenge_accounts.rulebook_key` and a prefix applied at read time
    #: would leave the stored account pointing at an ambiguous string.
    key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)

    #: What the holder calls it - "my demo discipline", "the rules I actually
    #: trade". Shown wherever a provider name is shown for a transcribed one.
    name: Mapped[str] = mapped_column(String(120), nullable=False)

    #: One JSON document holding every rule, so that "nobody said" and "this
    #: rulebook imposes nothing" stay distinguishable. Absent key or `null`
    #: means nobody said; the string "not imposed" means the second; anything
    #: else is the value.
    rules: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)

    #: Why these numbers, in the holder's words. A custom rulebook has no
    #: source URL to point at, and an unexplained limit is one nobody can
    #: audit six months later.
    notes: Mapped[str] = mapped_column(String(2000), default="", nullable=False)

    #: Who last wrote it. A transcribed rulebook has a URL and a date; this is
    #: the equivalent provenance for one somebody typed.
    changed_by: Mapped[str] = mapped_column(String(120), default="", nullable=False)
