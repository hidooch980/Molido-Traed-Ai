"""Prop and live accounts from Telegram: the challenge-accounts table the site edits.

`/prop` lists them; `/prop add`, `/prop del`, `/prop on`, `/prop off` do what
the site's challenge-accounts page does, through the same service
(`challenge_accounts`) and so the same validation. An account is named by its
label, which is unique per tenant.

Deleting removes the account's history and switching one on puts it back under
the risk layer's measurement, so both need the command repeated with
`confirm`. Adding records the account unconfirmed, exactly as the site's form
does by default; confirming its rules stays on the site, where the rulebook
can be read. Nothing here places an order.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.enums import AccountKind
from app.core.errors import MolidoError
from app.core.logging import get_logger
from app.integrations.telegram_account import CONFIRM_WORD, Answer, _md, confirm_answer

log = get_logger(__name__)

KINDS = {k.value for k in AccountKind}

HELP = "\n".join(
    [
        "حساب‌های پراپ و عادی (جدول حساب‌های چالش در سایت):",
        "`/prop` — فهرست حساب‌ها",
        "`/prop add challenge 100000 کلیدقانون نام حساب` — ثبت حساب پراپ (چالش)",
        "`/prop add funded 100000 کلیدقانون نام حساب` — ثبت حساب پراپ فاندد",
        "`/prop add live 5000 نام حساب` — ثبت حساب عادی (بدون قانون‌نامه)",
        "`/prop off نام حساب` — غیرفعال (فوری)",
        "`/prop on نام حساب confirm` — فعال‌سازی",
        "`/prop del نام حساب confirm` — حذف کامل با تاریخچه",
        "",
        "تأیید قوانین حساب پراپ در سایت انجام می‌شود.",
    ]
)


def is_command(text: str) -> bool:
    words = (text or "").strip().split(maxsplit=1)
    return bool(words) and words[0].lstrip("/").lower().split("@")[0] == "prop"


def handle(session: Any, chat_id: str, text: str) -> str | Answer | None:
    """Answer a `/prop` message, or None when it is not one."""
    if not is_command(text):
        return None
    args = (text or "").strip().split()[1:]
    action = args[0].lower() if args else "list"
    rest = args[1:]
    try:
        if action == "list":
            return _listing(session)
        if action == "add":
            return _add(session, chat_id, rest)
        if action in {"del", "on", "off"}:
            confirmed = bool(rest) and rest[-1].lower() == CONFIRM_WORD
            label = " ".join(rest[:-1] if confirmed else rest).strip()
            if not label:
                return HELP
            if action == "del":
                return _delete(session, chat_id, label, confirmed)
            return _switch(session, chat_id, label, action == "on", confirmed)
    except MolidoError as exc:
        return f"انجام نشد: {_md(exc)}"
    return HELP


def _tenant(session: Any):
    from app.services import challenge_accounts

    return challenge_accounts.default_tenant(session)


def _listing(session: Any) -> str | Answer:
    from app.services import challenge_accounts

    views = challenge_accounts.listing(session, tenant_id=_tenant(session))
    if not views:
        return "هیچ حسابی ثبت نشده.\n\n" + HELP
    lines = ["حساب‌ها:"]
    buttons: list[list[tuple[str, str]]] = []
    for view in views:
        account = view.account
        state = "🟢" if account.is_active else "⏸"
        kind = "عادی" if account.kind == AccountKind.LIVE else f"پراپ/{account.kind}"
        lines.append(
            f"{state} {_md(account.label)} — {kind}، "
            f"{float(account.starting_balance):,.0f} {_md(account.currency)}"
        )
        # By id: a label can be 120 characters and a button's data only 64 bytes.
        ref = f"{ID_PREFIX}{account.id.hex}"
        short = account.label[:20]
        toggle = (
            (f"⏸ {short}", f"prop off {ref}")
            if account.is_active
            else (f"▶️ {short}", f"prop on {ref}")
        )
        buttons.append([toggle, (f"🗑 {short}", f"prop del {ref}")])
    buttons.append([("⬅️ منو", "manage")])
    return Answer("\n".join(lines), buttons)


#: A button names its account by id, since a label may not fit.
ID_PREFIX = "id:"


def _find(session: Any, label: str):
    import uuid

    from sqlalchemy import select

    from app.models.challenge_accounts import ChallengeAccount

    match = ChallengeAccount.label == label
    if label.startswith(ID_PREFIX):
        try:
            match = ChallengeAccount.id == uuid.UUID(label[len(ID_PREFIX):])
        except ValueError:
            return None
    return session.scalar(
        select(ChallengeAccount).where(ChallengeAccount.tenant_id == _tenant(session), match)
    )


def _add(session: Any, chat_id: str, args: list[str]) -> str:
    from app.services import challenge_accounts

    if len(args) < 3:
        return "کامل نیست.\n\n" + HELP
    kind = args[0].lower()
    if kind not in KINDS:
        return f"نوع {_md(kind)} شناخته نیست. یکی از: {', '.join(sorted(KINDS))}"
    try:
        balance = Decimal(args[1].replace(",", ""))
    except InvalidOperation:
        return f"موجودی {_md(args[1])} عدد نیست."
    if not balance.is_finite() or balance <= 0:
        return "موجودی باید بزرگ‌تر از صفر باشد."
    rulebook_key: str | None = None
    rest = args[2:]
    if kind != AccountKind.LIVE.value:
        rulebook_key, rest = rest[0], rest[1:]
    label = " ".join(rest).strip()
    if not label:
        return "نام حساب لازم است.\n\n" + HELP

    with session.begin_nested():
        account = challenge_accounts.create(
            session,
            tenant_id=_tenant(session),
            label=label,
            kind=kind,
            rulebook_key=rulebook_key,
            starting_balance=balance,
        )
    log.info("telegram.prop_created", label=account.label, kind=kind, chat_id=str(chat_id))
    note = (
        ""
        if kind == AccountKind.LIVE.value
        else "\nقوانین آن را در سایت تأیید کنید تا پایش شروع شود."
    )
    return f"✅ حساب {_md(account.label)} ثبت شد.{note}"


def _delete(session: Any, chat_id: str, label: str, confirmed: bool) -> str | Answer:
    from app.services import challenge_accounts

    account = _find(session, label)
    if account is None:
        return f"حسابی به نام {_md(label)} نیست."
    label = account.label
    if not confirmed:
        return confirm_answer(
            f"⚠️ حساب {_md(label)} با همهٔ تاریخچه‌اش پاک می‌شود. برای نگه‌داشتن "
            "تاریخچه، غیرفعالش کنید. حذف شود؟",
            f"prop del {ID_PREFIX}{account.id.hex}",
        )
    with session.begin_nested():
        challenge_accounts.remove(session, tenant_id=_tenant(session), account_id=account.id)
    log.info("telegram.prop_deleted", label=label, chat_id=str(chat_id))
    return f"🗑 حساب {_md(label)} حذف شد."


def _switch(
    session: Any, chat_id: str, label: str, active: bool, confirmed: bool
) -> str | Answer:
    from app.services import challenge_accounts

    account = _find(session, label)
    if account is None:
        return f"حسابی به نام {_md(label)} نیست."
    label = account.label
    if active and not confirmed:
        return confirm_answer(
            f"حساب {_md(label)} دوباره زیر پایش ریسک می‌رود. تأیید می‌کنید؟",
            f"prop on {ID_PREFIX}{account.id.hex}",
        )
    with session.begin_nested():
        challenge_accounts.set_active(
            session, tenant_id=_tenant(session), account_id=account.id, active=active
        )
    log.info("telegram.prop_state", label=label, active=active, chat_id=str(chat_id))
    return f"🟢 حساب {_md(label)} فعال شد." if active else f"⏸ حساب {_md(label)} غیرفعال شد."
