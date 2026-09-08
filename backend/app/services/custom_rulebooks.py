"""Rulebooks the holder writes, and the one-way wall between them and the ten.

`app.brain.rulebooks` is a transcription. Every entry carries the URL it was
read from and the date it was read, and nothing anywhere may edit it - the
provenance is the whole value, and a number somebody can change is no longer
evidence of what a firm published.

A holder still has limits of their own: a discipline they trade to, or the
rehearsal of a programme on a demo where the real thing is not yet at stake.
Before this module the only way to enforce those was to register an account
against somebody else's rulebook and privately mean something different by it,
which produces confident verdicts about the wrong document.

So there are two kinds of rulebook and they never mix:

**Transcribed** - read only, forever. There is no update path to them here or
anywhere, and `PROTECTED` below is asserted by a test rather than trusted.

**Custom** - written, edited and deleted by the holder, keyed `custom:<slug>`
so no custom rulebook can shadow a transcribed one and no log line naming a
key is ambiguous about which kind it meant.

Two rules carry over from the transcribed side unchanged, because relaxing
either on the custom side would make "write your own" the way around them:

**Nobody said is not nothing.** A rule left out blocks rather than passes. To
say a rulebook caps nothing, the holder says so - `"not imposed"` - and that
is a claim they made rather than a field they left alone.

**Authoring is not confirming.** A custom rulebook is born unconfirmed like
every other. Writing a daily loss limit down is not the act of checking it
against the account it will end, and a mistyped limit does not fail loudly -
it passes a trade that ends the account.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.brain import rulebooks as rulebook_module
from app.brain.challenge import (
    NOT_IMPOSED,
    AllowanceBasis,
    ChallengeRules,
    DrawdownBasis,
)
from app.core.errors import NotFoundError, ValidationFailedError
from app.models.challenge_accounts import ChallengeAccount
from app.models.custom_rulebooks import KEY_PREFIX, CustomRulebook

MAX_NAME = 120
MAX_NOTES = 2000

#: The word a caller sends, and the word `_publish` already emits, for "this
#: rulebook deliberately caps nothing". Spelled once so the read and the write
#: path cannot drift into two different spellings of the same claim.
NOT_IMPOSED_WORD = "not imposed"

#: What a custom rulebook says where a transcribed one puts a URL.
SOURCE = "written by the account holder"

#: Percentage rules, held as fractions the way the transcribed ones are.
_PERCENT_RULES = (
    "profit_target_pct",
    "max_daily_drawdown_pct",
    "max_total_drawdown_pct",
    "max_single_day_profit_share",
)
_FLOAT_RULES = (*_PERCENT_RULES, "max_leverage", "automation_max_account_size")
_INT_RULES = ("min_trading_days", "max_trading_days", "max_concurrent_positions")
_FLAG_RULES = (
    "news_trading_allowed",
    "weekend_holding_allowed",
    "automated_trading_allowed",
    # Whether the total floor trails the peak or stays anchored to the
    # starting balance. Left out it is the last thing a verdict reports as
    # unchecked, and the difference between the two readings is the whole
    # account once it is in profit.
    "total_drawdown_trailing",
)

#: Every rule a holder may set. Anything else sent is refused by name rather
#: than ignored: a misspelled key that is quietly dropped is a limit the holder
#: believes they set and the engine never sees.
WRITABLE: tuple[str, ...] = (*_FLOAT_RULES, *_INT_RULES, *_FLAG_RULES)

#: The two rulers, which are not rules and have no "not imposed" state - they
#: say how the drawdown rules above are read, and every rulebook reads them
#: somehow.
_BASES = {
    "drawdown_basis": DrawdownBasis,
    "allowance_basis": AllowanceBasis,
}

#: Keys no custom rulebook may take, because a transcribed rulebook has them.
#: The prefix already makes a collision impossible; this is the belt to that
#: pair of braces, and it is what fails if the prefix is ever dropped.
PROTECTED: frozenset[str] = frozenset(book.key for book in rulebook_module.RULEBOOKS)


def slug(name: str) -> str:
    """`custom:my-demo-discipline` from "My demo discipline"."""
    body = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return f"{KEY_PREFIX}{body}"


def is_custom(key: str | None) -> bool:
    return bool(key) and str(key).startswith(KEY_PREFIX)


def _one_rule(field: str, raw: Any) -> Any:
    """One JSON value back into one of the three states.

    `None` is nobody said, the word is `NOT_IMPOSED`, anything else is a value
    of the right type. A string that is not the word is refused rather than
    coerced: `"5"` and `5` differ by a typo somebody should see.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        if raw.strip().lower() == NOT_IMPOSED_WORD:
            return NOT_IMPOSED
        raise ValidationFailedError(
            f"{field} is {raw!r}. A rule is a number, or {NOT_IMPOSED_WORD!r} to say "
            "this rulebook caps nothing, or left out to say nobody has decided yet."
        )
    if field in _FLAG_RULES:
        if not isinstance(raw, bool):
            raise ValidationFailedError(f"{field} is yes or no, not {raw!r}.")
        return raw
    if isinstance(raw, bool):
        # True is 1 to Python and this would sail through the number checks
        # below as a leverage cap of one.
        raise ValidationFailedError(f"{field} is a number, not {raw!r}.")
    if field in _INT_RULES:
        if not isinstance(raw, int):
            raise ValidationFailedError(f"{field} is a whole number, not {raw!r}.")
        if raw < 0:
            raise ValidationFailedError(f"{field} cannot be negative.")
        return raw
    if not isinstance(raw, int | float):
        raise ValidationFailedError(f"{field} is a number, not {raw!r}.")
    value = float(raw)
    if value <= 0:
        raise ValidationFailedError(
            f"{field} must be more than nothing. To say this rulebook imposes no "
            f"such limit, send {NOT_IMPOSED_WORD!r}."
        )
    if field in _PERCENT_RULES and value >= 1:
        # Fractions, like every transcribed rulebook: 0.05 is five percent. A
        # 5 here is a five hundred percent daily loss limit, which never binds.
        raise ValidationFailedError(
            f"{field} is a fraction, so five percent is 0.05 rather than 5."
        )
    return value


def normalise(rules: dict[str, Any] | None) -> dict[str, Any]:
    """Validate a submitted rule document and return what to store.

    Refuses unknown keys by name. A misspelling that is silently dropped is a
    limit the holder believes they set and the engine never sees, which is the
    worst of the three possible outcomes.
    """
    body = dict(rules or {})

    unknown = sorted(set(body) - set(WRITABLE) - set(_BASES))
    if unknown:
        known = ", ".join(sorted((*WRITABLE, *_BASES)))
        raise ValidationFailedError(
            f"Not rules this engine reads: {', '.join(unknown)}. Known rules: {known}"
        )

    stored: dict[str, Any] = {}
    for field in WRITABLE:
        if field not in body:
            continue
        value = _one_rule(field, body[field])
        stored[field] = NOT_IMPOSED_WORD if value is NOT_IMPOSED else value

    for field, enum in _BASES.items():
        if field not in body or body[field] is None:
            continue
        raw = body[field]
        try:
            stored[field] = enum(raw).value
        except ValueError:
            allowed = ", ".join(member.value for member in enum)
            raise ValidationFailedError(
                f"{field} is one of: {allowed}. Not {raw!r}."
            ) from None

    return stored


def to_rules(stored: dict[str, Any]) -> ChallengeRules:
    """The stored document as the engine's own dataclass."""
    built: dict[str, Any] = {}
    for field in WRITABLE:
        if field in stored:
            built[field] = _one_rule(field, stored[field])
    if "drawdown_basis" in stored:
        built["drawdown_basis"] = DrawdownBasis(stored["drawdown_basis"])
    if "allowance_basis" in stored:
        built["allowance_basis"] = AllowanceBasis(stored["allowance_basis"])
    return ChallengeRules(**built)


def to_rulebook(row: CustomRulebook) -> rulebook_module.Rulebook:
    """A custom row in the same shape every caller already handles.

    `confirmed_by_holder` stays False for the same reason it does on a
    transcribed rulebook: the account carries its own confirmation, and
    authoring a limit is not the act of checking it against the account it
    will end.
    """
    retrieved = row.updated_at or row.created_at
    return rulebook_module.Rulebook(
        key=row.key,
        provider=row.name,
        program=row.name,
        phase="written by the holder",
        rules=to_rules(row.rules or {}),
        source=SOURCE,
        retrieved=(retrieved.date() if isinstance(retrieved, datetime) else date.today()),
        confirmed_by_holder=False,
        notes=((row.notes,) if row.notes else ()),
    )


def _existing(session: Session, *, tenant_id: uuid.UUID, key: str) -> CustomRulebook | None:
    return session.execute(
        select(CustomRulebook).where(
            CustomRulebook.tenant_id == tenant_id, CustomRulebook.key == key
        )
    ).scalar_one_or_none()


def create(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    name: str,
    rules: dict[str, Any] | None = None,
    notes: str = "",
    changed_by: str = "",
    now: datetime | None = None,
) -> CustomRulebook:
    name = name.strip()
    if not name or len(name) > MAX_NAME:
        raise ValidationFailedError(f"A name is required, up to {MAX_NAME} characters.")
    if len(notes) > MAX_NOTES:
        raise ValidationFailedError(f"Notes are limited to {MAX_NOTES} characters.")

    key = slug(name)
    if key == KEY_PREFIX:
        raise ValidationFailedError(
            "A name needs at least one letter or digit to make a key from."
        )
    if key in PROTECTED:
        raise ValidationFailedError(f"{key!r} is a transcribed rulebook and is read only.")
    if _existing(session, tenant_id=tenant_id, key=key) is not None:
        raise ValidationFailedError(f"A rulebook called {name!r} already exists.")

    row = CustomRulebook(
        tenant_id=tenant_id,
        key=key,
        name=name,
        rules=normalise(rules),
        notes=notes,
        changed_by=changed_by,
    )
    stamp = now or datetime.now(UTC)
    row.created_at = stamp
    row.updated_at = stamp
    session.add(row)
    session.flush()
    return row


def update(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    key: str,
    rules: dict[str, Any] | None = None,
    notes: str | None = None,
    changed_by: str = "",
    now: datetime | None = None,
) -> CustomRulebook:
    """Edit a custom rulebook. The transcribed ones have no path here at all.

    `rules` replaces the document rather than merging into it. A merge cannot
    express "I have decided this rule no longer applies", because the only way
    to say that would be to send a key with `null` - which is also how a caller
    that never knew about the rule looks.
    """
    if not is_custom(key):
        raise ValidationFailedError(
            f"{key!r} is a transcribed rulebook. Those record what a firm published "
            "on a stated date and are read only; write your own instead."
        )

    row = _existing(session, tenant_id=tenant_id, key=key)
    if row is None:
        raise NotFoundError(f"No rulebook here has the key {key!r}.")

    if rules is not None:
        row.rules = normalise(rules)
    if notes is not None:
        if len(notes) > MAX_NOTES:
            raise ValidationFailedError(f"Notes are limited to {MAX_NOTES} characters.")
        row.notes = notes
    if changed_by:
        row.changed_by = changed_by
    row.updated_at = now or datetime.now(UTC)
    session.flush()
    return row


def remove(session: Session, *, tenant_id: uuid.UUID, key: str) -> None:
    """Delete a custom rulebook, unless an account is being measured by it.

    Refused rather than cascaded. An account whose rulebook vanished resolves
    to nothing, and an account that resolves to nothing is one the challenge
    gate waves through - deleting a rulebook would silently remove the limits
    from every account using it.
    """
    row = _existing(session, tenant_id=tenant_id, key=key)
    if row is None:
        raise NotFoundError(f"No rulebook here has the key {key!r}.")

    users = session.execute(
        select(ChallengeAccount.label).where(
            ChallengeAccount.tenant_id == tenant_id,
            ChallengeAccount.rulebook_key == key,
        )
    ).scalars().all()
    if users:
        raise ValidationFailedError(
            f"{', '.join(sorted(users))} still measured against {key!r}. Move those "
            "accounts to another rulebook first - deleting this one would leave them "
            "with no limits rather than with different ones."
        )

    session.delete(row)
    session.flush()


def listing(session: Session, *, tenant_id: uuid.UUID) -> list[CustomRulebook]:
    return list(
        session.execute(
            select(CustomRulebook)
            .where(CustomRulebook.tenant_id == tenant_id)
            .order_by(CustomRulebook.name)
        ).scalars()
    )


def resolve(
    session: Session, *, tenant_id: uuid.UUID, key: str | None
) -> rulebook_module.Rulebook | None:
    """The custom rulebook with this key, in the shared shape, or None."""
    if not is_custom(key):
        return None
    row = _existing(session, tenant_id=tenant_id, key=str(key))
    return None if row is None else to_rulebook(row)
