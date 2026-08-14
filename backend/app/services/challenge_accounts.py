"""Challenge accounts, and the confirmation that makes their rules usable.

The rulebooks in `app.brain.rulebooks` were transcribed from a published page
on a stated date, and every one carries `confirmed_by_holder: false`. That flag
gates a real feature: `Condition.RULEBOOK_CONFIRMED` in the plan catalogue,
which withholds challenge tracking until somebody has checked the numbers
against their own contract. Tracking an account against rules nobody verified
produces a confident verdict about the wrong document.

This module is where the flag flips, and it flips per account rather than per
rulebook. Two people on the same program can hold different contracts - a
provider changes terms and honours the old ones for existing accounts - so
confirmation belongs to the account, not to the transcription.

Nothing here holds a credential. A challenge account is rules and a balance;
the broker login that trades it lives in MetaTrader's own config.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.brain import rulebooks as rulebook_module
from app.core.errors import NotFoundError, ValidationFailedError
from app.models.challenge_accounts import ChallengeAccount

MAX_LABEL = 120
MAX_NOTES = 2000
#: Below this a percentage drawdown is smaller than a cent, and every headroom
#: figure rounds to zero - which blocks, correctly, and unhelpfully.
MIN_BALANCE = Decimal("100")


@dataclass(frozen=True)
class AccountView:
    """One account, with the rulebook resolved and its confirmation stated."""

    account: ChallengeAccount
    rulebook: Any | None

    def as_dict(self) -> dict[str, Any]:
        book = self.rulebook
        return {
            "id": str(self.account.id),
            "label": self.account.label,
            "rulebook_key": self.account.rulebook_key,
            "provider": book.provider if book else None,
            "program": book.program if book else None,
            "phase": book.phase if book else None,
            # Missing rather than zero when the rulebook has gone. A key that
            # no longer resolves means the transcription was renamed or
            # removed, and inventing numbers for it would be worse than saying
            # so.
            "rulebook_available": book is not None,
            "starting_balance": float(self.account.starting_balance),
            "currency": self.account.currency,
            "currency_per_r": (
                float(self.account.currency_per_r)
                if self.account.currency_per_r is not None
                else None
            ),
            "rules_confirmed": self.account.rules_confirmed,
            "confirmed_at": (
                self.account.confirmed_at.isoformat()
                if self.account.confirmed_at
                else None
            ),
            "notes": self.account.notes,
            "is_active": self.account.is_active,
            "tracking_available": self.account.rules_confirmed and book is not None,
            "why_not": (
                None
                if (self.account.rules_confirmed and book is not None)
                else (
                    "the rulebook this account points at is no longer published"
                    if book is None
                    else "the rules have not been confirmed against this account's "
                    "contract, and tracking against unverified rules produces a "
                    "verdict about the wrong document"
                )
            ),
        }


#: A single-tenant deployment still needs a row for the foreign key to point
#: at. Named rather than nullable so the column means the same thing on the day
#: a second tenant appears, instead of "the first one, probably".
DEFAULT_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def default_tenant(session: Session) -> uuid.UUID:
    """The tenant challenge accounts hang off, created if it is missing.

    Created here rather than assumed by a migration: a seeded row is invisible
    to anybody reading the model, and its absence surfaced as a foreign-key
    error at the first insert - in a test, luckily, rather than the first time
    somebody pressed the button.
    """
    from app.models.tenancy import Tenant

    tenant = session.get(Tenant, DEFAULT_TENANT_ID)
    if tenant is None:
        tenant = Tenant(
            id=DEFAULT_TENANT_ID,
            slug="default",
            name="MolidoTrade",
            locale="fa",
        )
        session.add(tenant)
        session.flush()
    return tenant.id


def _resolve(key: str):
    return next((book for book in rulebook_module.RULEBOOKS if book.key == key), None)


def create(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    label: str,
    rulebook_key: str,
    starting_balance: Decimal,
    currency: str = "USD",
    currency_per_r: Decimal | None = None,
    rules_confirmed: bool = False,
    notes: str = "",
    now: datetime | None = None,
) -> ChallengeAccount:
    """Record a challenge account.

    An unconfirmed account is stored rather than refused. Somebody part-way
    through setup has a real account with rules nobody has checked, and that is
    a state worth recording honestly - the row simply cannot be tracked against
    until the flag flips.
    """
    label = label.strip()
    if not label or len(label) > MAX_LABEL:
        raise ValidationFailedError(f"A label is required, up to {MAX_LABEL} characters.")

    if _resolve(rulebook_key) is None:
        known = ", ".join(book.key for book in rulebook_module.RULEBOOKS)
        raise ValidationFailedError(
            f"No transcribed rulebook has the key {rulebook_key!r}. Known keys: {known}"
        )

    if starting_balance < MIN_BALANCE:
        raise ValidationFailedError(
            f"A starting balance of at least {MIN_BALANCE} is required: below that "
            "a percentage drawdown rounds to nothing and every check blocks."
        )

    if currency_per_r is not None and currency_per_r <= 0:
        raise ValidationFailedError("One R must be worth more than nothing.")

    if len(notes) > MAX_NOTES:
        raise ValidationFailedError(f"Notes are limited to {MAX_NOTES} characters.")

    existing = session.scalar(
        select(ChallengeAccount).where(
            ChallengeAccount.tenant_id == tenant_id, ChallengeAccount.label == label
        )
    )
    if existing is not None:
        raise ValidationFailedError(f"An account called {label!r} already exists.")

    moment = now or datetime.now(UTC)
    account = ChallengeAccount(
        tenant_id=tenant_id,
        label=label,
        rulebook_key=rulebook_key,
        starting_balance=starting_balance,
        currency=currency.upper()[:8],
        currency_per_r=currency_per_r,
        rules_confirmed=rules_confirmed,
        # Stamped only when the flag is actually set, so a false row does not
        # carry a timestamp implying somebody looked.
        confirmed_at=moment if rules_confirmed else None,
        notes=notes.strip(),
    )
    session.add(account)
    session.flush()
    return account


def confirm(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    account_id: uuid.UUID,
    notes: str = "",
    now: datetime | None = None,
) -> ChallengeAccount:
    """Mark an account's rules as checked against its contract."""
    account = session.scalar(
        select(ChallengeAccount).where(
            ChallengeAccount.id == account_id, ChallengeAccount.tenant_id == tenant_id
        )
    )
    if account is None:
        raise NotFoundError("No challenge account with that id.")

    account.rules_confirmed = True
    account.confirmed_at = now or datetime.now(UTC)
    if notes.strip():
        account.notes = notes.strip()[:MAX_NOTES]
    session.flush()
    return account


def listing(session: Session, *, tenant_id: uuid.UUID | None = None) -> list[AccountView]:
    query = select(ChallengeAccount).order_by(ChallengeAccount.created_at)
    if tenant_id is not None:
        query = query.where(ChallengeAccount.tenant_id == tenant_id)
    return [
        AccountView(account=account, rulebook=_resolve(account.rulebook_key))
        for account in session.scalars(query)
    ]


def summary(session: Session, *, tenant_id: uuid.UUID | None = None) -> dict[str, Any]:
    """The counts, split by whether they can actually be tracked.

    Confirmed and unconfirmed are counted apart because they are different
    states of readiness, and a single total would let an account nobody has
    verified pad the number that suggests the system is set up.
    """
    views = listing(session, tenant_id=tenant_id)
    confirmed = [v for v in views if v.account.rules_confirmed]
    return {
        "accounts": [view.as_dict() for view in views],
        "total": len(views),
        "confirmed": len(confirmed),
        "unconfirmed": len(views) - len(confirmed),
        "trackable": sum(1 for v in views if v.as_dict()["tracking_available"]),
        "note": (
            "confirmation is per account, not per rulebook. Two holders on the "
            "same program can be on different contracts - providers change "
            "terms and honour the old ones for existing accounts"
        ),
    }
