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

Three kinds of account pass through here. A challenge and a funded account are
measured against a rulebook somebody else wrote, so both require one and both
require the holder to confirm it. A live account is the holder's own money at a
broker: nothing external ends it, there is no rulebook, and asking somebody to
"confirm" rules that do not exist would collect a meaningless yes. So a live
account carries no rulebook and no confirmation, and says so rather than
sitting permanently unconfirmed as though somebody had failed to finish setup.

Nothing here holds a credential. An account is rules and a balance; the broker
login that trades it lives in MetaTrader's own config.
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
from app.core.enums import AccountKind
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
        live = self.account.kind == AccountKind.LIVE
        off = not self.account.is_active
        return {
            "id": str(self.account.id),
            "label": self.account.label,
            "kind": self.account.kind,
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
            # A live account is never "trackable" in this sense and that is
            # not a gap to be closed. Challenge tracking measures an account
            # against limits somebody else can end it on; the holder's own
            # account has none, so there is nothing to track it against and
            # showing it as pending setup would invite a fix that does not
            # exist.
            "tracking_available": (
                False
                if (live or off)
                else (self.account.rules_confirmed and book is not None)
            ),
            "why_not": (
                # Switched off first: it is the holder's most recent decision
                # about this account, and it outranks every other reason. An
                # account paused mid-challenge would otherwise report the
                # rulebook problem it had before it was paused, and somebody
                # would go and fix a rulebook for an account nobody is trading.
                "this account is switched off, so nothing is measured against "
                "it until it is switched back on"
                if off
                else "nobody outside this deployment sets the limits on a live "
                "account, so there is no rulebook to measure it against"
                if live
                else None
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
    from sqlalchemy import select

    from app.models.tenancy import Tenant

    tenant = session.get(Tenant, DEFAULT_TENANT_ID)
    if tenant is not None:
        return tenant.id

    # By slug before inserting. Looking up only by the fixed id and then
    # inserting produced a 500 on a deployment where a tenant with this slug
    # already existed under a different id: the lookup missed, the insert hit
    # the unique constraint, and every read of this endpoint failed with a
    # database error rather than a list.
    existing = session.scalar(select(Tenant).where(Tenant.slug == "default"))
    if existing is not None:
        return existing.id

    tenant = Tenant(
        id=DEFAULT_TENANT_ID,
        slug="default",
        name="MolidoTrade",
        locale="fa",
    )
    session.add(tenant)
    session.flush()
    return tenant.id


def _resolve(key: str | None):
    """The rulebook with this key, or None.

    None in, None out: a live account has no key, and that is an answer rather
    than a lookup failure.
    """
    if not key:
        return None
    return next((book for book in rulebook_module.RULEBOOKS if book.key == key), None)


def create(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    label: str,
    rulebook_key: str | None = None,
    kind: str = AccountKind.CHALLENGE.value,
    starting_balance: Decimal,
    currency: str = "USD",
    currency_per_r: Decimal | None = None,
    rules_confirmed: bool = False,
    notes: str = "",
    now: datetime | None = None,
) -> ChallengeAccount:
    """Record an account of one of the three kinds.

    An unconfirmed prop account is stored rather than refused. Somebody part-way
    through setup has a real account with rules nobody has checked, and that is
    a state worth recording honestly - the row simply cannot be tracked against
    until the flag flips.

    A live account is a different case, not a lesser one. It carries no
    rulebook because none exists, and its confirmation flag is forced false
    rather than left to the caller: "yes, I checked the rules" is not a
    statement anybody can truthfully make about rules that were never written.
    """
    label = label.strip()
    if not label or len(label) > MAX_LABEL:
        raise ValidationFailedError(f"A label is required, up to {MAX_LABEL} characters.")

    if kind not in {k.value for k in AccountKind}:
        known_kinds = ", ".join(k.value for k in AccountKind)
        raise ValidationFailedError(
            f"{kind!r} is not a kind of account. Known kinds: {known_kinds}"
        )

    live = kind == AccountKind.LIVE.value
    if live:
        # Dropped rather than refused if one arrives. A caller that sends a
        # rulebook with a live account has misunderstood the kind, not made a
        # typo, and storing the key would leave a row claiming a programme the
        # holder is not on.
        rulebook_key = None
        rules_confirmed = False
    else:
        if not rulebook_key:
            raise ValidationFailedError(
                f"A {kind} account is measured against a rulebook, so one has to "
                "be named. Only a live account has none."
            )
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
        kind=kind,
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

    if account.kind == AccountKind.LIVE:
        # Refused rather than quietly ignored. A caller that gets a 200 here
        # will believe the account is confirmed, and the honest answer is that
        # there was never anything to confirm.
        raise ValidationFailedError(
            "A live account has no rulebook, so there are no rules to confirm. "
            "Confirmation exists to check a transcription against a contract, "
            "and this account is not on anybody's programme."
        )

    account.rules_confirmed = True
    account.confirmed_at = now or datetime.now(UTC)
    if notes.strip():
        account.notes = notes.strip()[:MAX_NOTES]
    session.flush()
    return account


def move_to(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    account_id: uuid.UUID,
    rulebook_key: str,
    kind: str | None = None,
    starting_balance: Decimal | None = None,
) -> ChallengeAccount:
    """Point an existing account at a different rulebook.

    This is how a two-phase programme is actually sat. Phase one, phase two and
    the funded account are three different documents with three different
    numbers, and the holder passes through all of them on what is, to them, one
    account. Recording each as a fresh row would scatter one account's history
    across three, and the platform would have no way to say that the funded
    account and the challenge that earned it are the same thing.

    **Confirmation is reset, always.** The holder confirmed the phase one
    rules; phase two is a different document with a different profit target and
    frequently a different time limit. Carrying the tick across would mean the
    platform measuring an account against numbers nobody checked while
    displaying it as checked - which is the single failure this whole
    confirmation mechanism exists to prevent.

    The starting balance is optional and replaces the old one when given.
    Most programmes reset the balance between phases, and a phase two measured
    against phase one's closing balance would compute every drawdown from the
    wrong floor.
    """
    account = session.scalar(
        select(ChallengeAccount).where(
            ChallengeAccount.id == account_id, ChallengeAccount.tenant_id == tenant_id
        )
    )
    if account is None:
        raise NotFoundError("No challenge account with that id.")

    if account.kind == AccountKind.LIVE and kind in (None, AccountKind.LIVE.value):
        raise ValidationFailedError(
            "A live account is on nobody's programme, so there is no phase to "
            "move it to. Record the prop account separately."
        )

    if kind is not None and kind not in {k.value for k in AccountKind}:
        known_kinds = ", ".join(k.value for k in AccountKind)
        raise ValidationFailedError(
            f"{kind!r} is not a kind of account. Known kinds: {known_kinds}"
        )

    if kind == AccountKind.LIVE.value:
        raise ValidationFailedError(
            "Moving a prop account to a live one would keep its programme "
            "history against an account that is on no programme. Record the "
            "live account separately."
        )

    if _resolve(rulebook_key) is None:
        known = ", ".join(book.key for book in rulebook_module.RULEBOOKS)
        raise ValidationFailedError(
            f"No transcribed rulebook has the key {rulebook_key!r}. Known keys: {known}"
        )

    if starting_balance is not None and starting_balance < MIN_BALANCE:
        raise ValidationFailedError(
            f"A starting balance of at least {MIN_BALANCE} is required: below that "
            "a percentage drawdown rounds to nothing and every check blocks."
        )

    account.rulebook_key = rulebook_key
    if kind is not None:
        account.kind = kind
    if starting_balance is not None:
        account.starting_balance = starting_balance

    # Never carried across. See the docstring: this is the one line in the
    # module that the confirmation mechanism depends on.
    account.rules_confirmed = False
    account.confirmed_at = None
    session.flush()
    return account


def set_active(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    account_id: uuid.UUID,
    active: bool,
) -> ChallengeAccount:
    """Switch an account on or off.

    Off rather than deleted, and the distinction is the point. A challenge that
    failed, an account between funding rounds, one the holder has stepped away
    from - all of them are real accounts with real history, and deleting the
    row would take the history with it. Switched off, the account keeps
    everything it knows and is measured against nothing.

    Nothing is recomputed here. Whether an account can be tracked is derived
    from its state every time it is read, so an account switched off stops
    being tracked at the next read rather than at the next sweep - and one
    switched back on resumes with the confirmation it already had, because
    pausing an account was never a statement about its rulebook.
    """
    account = session.scalar(
        select(ChallengeAccount).where(
            ChallengeAccount.id == account_id, ChallengeAccount.tenant_id == tenant_id
        )
    )
    if account is None:
        raise NotFoundError("No challenge account with that id.")

    account.is_active = active
    session.flush()
    return account


def remove(
    session: Session, *, tenant_id: uuid.UUID, account_id: uuid.UUID
) -> str:
    """Delete an account and everything it knows. Returns its label.

    `set_active` exists for the ordinary case and is what almost every
    situation wants: a failed challenge, an account between funding rounds,
    one whose holder stepped away - all real accounts with real history, kept
    and measured against nothing.

    This is the other case, and it is narrower than it looks: an account that
    should never have been written down. A typo, a test row, a program the
    holder abandoned before trading it. For those, "switched off" is clutter
    that outlives its usefulness on a page somebody reads under pressure, and
    a page nobody trusts to be current is a page nobody reads at all.

    It really deletes. The alternative - a hidden flag - produces two kinds
    of invisible account whose difference nobody can see, which is how a
    deleted row comes back after somebody clears a filter.
    """
    account = session.scalar(
        select(ChallengeAccount).where(
            ChallengeAccount.id == account_id, ChallengeAccount.tenant_id == tenant_id
        )
    )
    if account is None:
        raise NotFoundError("No challenge account with that id.")

    label = account.label
    session.delete(account)
    session.flush()
    return label


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
    # Confirmation is counted over prop accounts alone. A live account is
    # permanently unconfirmed by design, and letting it into the denominator
    # would make a fully configured deployment read as half-finished for a
    # reason nobody could act on.
    prop = [v for v in views if v.account.kind != AccountKind.LIVE]
    confirmed = [v for v in prop if v.account.rules_confirmed]
    return {
        "accounts": [view.as_dict() for view in views],
        "total": len(views),
        "active": sum(1 for v in views if v.account.is_active),
        "by_kind": {
            kind.value: sum(1 for v in views if v.account.kind == kind) 
            for kind in AccountKind
        },
        "confirmed": len(confirmed),
        "unconfirmed": len(prop) - len(confirmed),
        "trackable": sum(1 for v in views if v.as_dict()["tracking_available"]),
        "note": (
            "confirmation is per account, not per rulebook. Two holders on the "
            "same program can be on different contracts - providers change "
            "terms and honour the old ones for existing accounts. Live "
            "accounts are counted in the total and left out of the "
            "confirmation figures: they are measured against no rulebook, so "
            "there is nothing about them to confirm"
        ),
    }
