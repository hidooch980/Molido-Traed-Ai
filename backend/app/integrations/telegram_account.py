"""Connect a broker account from Telegram, through the same queue the site uses.

`/addaccount <login> <server> <password>` - or with a terminal first,
`/addaccount <terminal> <login> <server> <password>` - validates exactly as
the site's form does (`mt5_link.validate`) and writes the same request for
the host agent. Nothing new reaches MetaTrader; only the door is new.

**The password is a chat message, so the message is deleted.** The bot asks
Telegram to delete it the moment it is read, never echoes it, never logs it,
and keeps it nowhere - it goes into the queue file the agent consumes, as it
does from the site. It still crossed Telegram's servers, and the help says so.

`/delaccount <terminal>` logs a terminal out and forgets its login (the
site's unlink), and `/activate` / `/deactivate <account>` write the same
per-account pause switch the site does. Deleting and activating are the
risky directions, so each needs the same command repeated with `confirm`;
pausing is the safe direction and takes effect at once. None of the three
carries a secret or places an order: activating only lets every other gate
be asked again.

The agent's answer takes up to seven minutes. `pending` remembers which chat
asked, and `check_pending` - called by the chat worker once a minute - sends
the result there when it arrives, or says so if the agent never answers.
"""

from __future__ import annotations

import json
import os
import pathlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.errors import ValidationFailedError
from app.core.logging import get_logger

log = get_logger(__name__)

#: After this the agent is reported as not answering, and the request forgotten.
GIVE_UP_AFTER = timedelta(minutes=20)

DEFAULT_STATE_FILE = "/var/lib/molido/state/telegram-accounts.json"

HELP = "\n".join(
    [
        "افزودن حساب از تلگرام، در یک پیام:",
        "`/addaccount شماره سرور رمز`",
        "مثال: `/addaccount 1520012345 FTMO-Demo2 رمزاصلی`",
        "",
        "برای جایگزینی روی یک ترمینال مشخص، نام ترمینال را اول بنویسید:",
        "`/addaccount term-j 1520012345 FTMO-Demo2 رمزاصلی`",
        "",
        "رمز اصلی (Master) لازم است، نه رمز فقط‌دیدنی. پیام شما بلافاصله پاک "
        "می‌شود و رمز هیچ‌جا نگه داشته نمی‌شود؛ ولی از سرورهای تلگرام گذشته است.",
    ]
)


def _state_path() -> pathlib.Path:
    return pathlib.Path(os.environ.get("MOLIDO_TELEGRAM_ACCOUNTS_FILE") or DEFAULT_STATE_FILE)


def _load() -> dict[str, dict[str, str]]:
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(pending: dict[str, dict[str, str]]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(pending), encoding="utf-8")
    tmp.replace(path)


def _md(text: object) -> str:
    """Escaped for Telegram's Markdown: the reply is sent with it, and one
    stray underscore in a server name would make Telegram refuse the lot."""
    out = str(text)
    for ch in ("\\", "_", "*", "`", "["):
        out = out.replace(ch, "\\" + ch)
    return out


def is_command(text: str) -> bool:
    words = (text or "").strip().split(maxsplit=1)
    return bool(words) and words[0].lstrip("/").lower().split("@")[0] == "addaccount"


@dataclass(frozen=True)
class Answer:
    """A reply with inline buttons: rows of (label, callback data).

    Every button's data is one of these same commands, so a tap walks the
    same path as typing it - after the same admin check.
    """

    text: str
    buttons: list[list[tuple[str, str]]] = field(default_factory=list)


#: Back to the account menu, under every confirmation.
CANCEL = ("❌ انصراف", "manage")


def confirm_answer(text: str, command: str) -> Answer:
    """A confirmation that can be tapped instead of typed."""
    return Answer(text, [[("✅ تأیید", f"{command} {CONFIRM_WORD}"), CANCEL]])


def menu() -> Answer:
    """The account menu the "⚙️ مدیریت حساب‌ها" key opens."""
    return Answer(
        "\n".join(
            [
                "*مدیریت حساب‌ها*",
                "",
                "➕ برای افزودن، دکمهٔ افزودن را بزنید؛ ربات مرحله‌به‌مرحله می‌پرسد.",
                "🖥 / 🏆 برای حذف، فعال یا غیرفعال کردن، یکی از فهرست‌ها را بزنید.",
                "",
                "یا با تایپ: `/addaccount شماره سرور رمز` — `/prop add live 5000 نام`",
            ]
        ),
        [
            [("🖥 حساب‌های ترمینال", "activate")],
            [("🏆 حساب‌های پراپ و عادی", "prop")],
            [("➕ افزودن حساب بروکر", "wiz broker")],
            [("➕ افزودن حساب پراپ/عادی", "wiz prop")],
        ],
    )


MANAGE_COMMANDS = frozenset({"delaccount", "activate", "deactivate"})
CONFIRM_WORD = "confirm"

MANAGE_HELP = "\n".join(
    [
        "مدیریت حساب‌ها از تلگرام:",
        "`/delaccount ترمینال` — خروج حساب از ترمینال و فراموش کردن لاگین",
        "`/activate حساب` — اجازهٔ معامله روی حساب",
        "`/deactivate حساب` — توقف معامله روی حساب (فوری)",
        "",
        "حذف و فعال‌سازی با تکرار دستور و کلمهٔ `confirm` انجام می‌شود.",
    ]
)


def _command(text: str) -> tuple[str, list[str]]:
    words = (text or "").strip().split()
    if not words:
        return "", []
    return words[0].lstrip("/").lower().split("@")[0], words[1:]


def handle_manage(
    chat_id: str,
    text: str,
    *,
    now: datetime | None = None,
    known_accounts: Callable[[], list[str]] | None = None,
) -> str | Answer | None:
    """`/delaccount`, `/activate`, `/deactivate`, or None when it is none of them."""
    name, args = _command(text)
    if name not in MANAGE_COMMANDS:
        return None
    confirmed = len(args) >= 2 and args[1].lower() == CONFIRM_WORD
    if name == "delaccount":
        return _delete(chat_id, args, confirmed, now or datetime.now(UTC))
    return _switch(chat_id, name == "activate", args, confirmed, known_accounts)


def _delete(
    chat_id: str, args: list[str], confirmed: bool, moment: datetime
) -> str | Answer:
    from app.services import mt5_link

    if not args:
        return MANAGE_HELP
    try:
        request = mt5_link.validate_clear(args[0])
    except ValidationFailedError as exc:
        return f"حذف نشد: {_md(exc)}"
    if not confirmed:
        return confirm_answer(
            f"⚠️ حساب ترمینال {_md(request.terminal)} خارج و لاگین آن فراموش می‌شود؛ "
            "اگر معامله‌ای باز است، ترمینال وسط کار بسته می‌شود. تأیید می‌کنید؟",
            f"delaccount {request.terminal}",
        )
    result = mt5_link.submit(request, now=moment)
    if not result.queued:
        return f"حذف نشد: {_md(result.reason)}"
    pending = _load()
    pending[result.request_id] = {
        "chat_id": str(chat_id),
        "login": request.terminal,
        "kind": "remove",
        "at": moment.isoformat(),
    }
    _save(pending)
    log.info(
        "telegram.account_remove_requested",
        request_id=result.request_id,
        terminal=request.terminal,
    )
    return (
        f"🗑 درخواست حذف حساب از ترمینال {_md(request.terminal)} ثبت شد. "
        "نتیجه را همین‌جا می‌فرستم."
    )


def _switch(
    chat_id: str,
    active: bool,
    args: list[str],
    confirmed: bool,
    known_accounts: Callable[[], list[str]] | None,
) -> str | Answer:
    from app.execution import account_switch

    if known_accounts is None:
        from app.providers.metatrader import bridge_dirs

        def known_accounts() -> list[str]:
            return list(bridge_dirs())

    try:
        known = sorted(known_accounts())
    except ValueError as exc:
        return f"فهرست حساب‌ها خوانده نشد: {_md(exc)}"

    if not args:
        lines = ["وضعیت حساب‌ها:"]
        buttons: list[list[tuple[str, str]]] = []
        for row in account_switch.listing(known):
            key = row["account"]
            mark = "🟢 فعال" if row["active"] else "⏸ متوقف"
            lines.append(f"{_md(key)} — {mark}")
            toggle = (
                (f"⏸ توقف {key}", f"deactivate {key}")
                if row["active"]
                else (f"▶️ فعال {key}", f"activate {key}")
            )
            buttons.append([toggle, (f"🗑 حذف {key}", f"delaccount {key}")])
        verb = "activate" if active else "deactivate"
        lines += ["", f"`/{verb} نام‌حساب` یا دکمه‌ها:"]
        buttons.append([("⬅️ منو", "manage")])
        return Answer("\n".join(lines), buttons)

    account = args[0]
    if account not in known:
        return (
            f"حسابی به نام {_md(account)} تعریف نشده. "
            f"موجود: {_md(', '.join(known) or '(هیچ)')}"
        )
    if active and not confirmed:
        return confirm_answer(
            f"فعال‌سازی {_md(account)} اجازه می‌دهد بقیهٔ گیت‌ها (کلید قطع کلی، "
            "ریسک، قوانین) دوباره بررسی شوند؛ خودش سفارشی ثبت نمی‌کند. تأیید می‌کنید؟",
            f"activate {account}",
        )
    account_switch.write(
        account,
        active=active,
        by=f"telegram:{chat_id}",
        reason="from Telegram",
    )
    log.info("telegram.account_state", account=account, active=active, chat_id=str(chat_id))
    allowed, why = account_switch.state(account)
    if active:
        return f"🟢 حساب {_md(account)} فعال شد." if allowed else f"فعال نشد: {_md(why)}"
    return f"⏸ معامله روی حساب {_md(account)} متوقف شد."


def handle(chat_id: str, text: str, *, now: datetime | None = None) -> str:
    """Validate, queue, and remember who asked. Never includes the password."""
    from app.services import mt5_link

    moment = now or datetime.now(UTC)
    parts = (text or "").strip().split()
    args = parts[1:]
    if not args:
        return HELP

    terminal: str | None = None
    if not args[0].isdigit():
        terminal, args = args[0], args[1:]
    if len(args) < 3:
        return "کامل نیست. " + HELP
    login, server, password = args[0], args[1], " ".join(args[2:])

    try:
        request = mt5_link.validate(login, server, password)
        checked = mt5_link.validate_terminal(terminal)
    except ValidationFailedError as exc:
        return f"ثبت نشد: {_md(exc)}"
    if checked is not None:
        request = mt5_link.LinkRequest(
            login=request.login, server=request.server, password=request.password,
            terminal=checked,
        )

    result = mt5_link.submit(request, now=moment)
    if not result.queued:
        return f"ثبت نشد: {_md(result.reason)}"

    pending = _load()
    pending[result.request_id] = {
        "chat_id": str(chat_id),
        "login": result.login,
        "at": moment.isoformat(),
    }
    _save(pending)
    log.info(
        "telegram.account_requested",
        request_id=result.request_id,
        login=result.login,
        server=result.server,
        terminal=checked,
    )
    where = f"ترمینال {_md(checked)}" if checked else "اولین ترمینال خالی"
    return "\n".join(
        [
            f"✅ درخواست اتصال حساب {result.login} ({_md(result.server)}) روی {where} ثبت شد.",
            "",
            "اتصال تا ۷ دقیقه طول می‌کشد؛ نتیجه را همین‌جا می‌فرستم.",
            "پیام رمز شما پاک شد.",
        ]
    )


def check_pending(
    send: Callable[[str, str], Any],
    *,
    now: datetime | None = None,
    result_for: Callable[[str], dict[str, Any]] | None = None,
) -> int:
    """Send each finished request's result to the chat that asked. Returns how many."""
    if result_for is None:
        from app.services import mt5_link

        result_for = mt5_link.result_for
    moment = now or datetime.now(UTC)
    pending = _load()
    if not pending:
        return 0

    reported = 0
    for request_id, asked in list(pending.items()):
        answer = result_for(request_id)
        login = asked.get("login", "")
        if answer.get("known") and asked.get("kind") == "remove":
            ok = bool(answer.get("cleared"))
            reason = str(answer.get("reason") or "")
            send(
                asked["chat_id"],
                f"✅ حساب ترمینال {login} حذف شد."
                if ok
                else f"❌ حذف حساب ترمینال {login} انجام نشد: {reason or 'دلیلی گزارش نشد'}",
            )
            del pending[request_id]
            reported += 1
        elif answer.get("known"):
            # The agent's own word for success: applied is not connected - a
            # wrong server name applies perfectly and connects to nothing.
            ok = bool(answer.get("connected"))
            reason = str(answer.get("reason") or "")
            text = (
                f"✅ حساب {login} وصل شد. ربات از چرخهٔ بعد رویش کار می‌کند."
                if ok
                else f"❌ حساب {login} وصل نشد: {reason or 'دلیلی گزارش نشد'}"
            )
            send(asked["chat_id"], text)
            del pending[request_id]
            reported += 1
        elif moment - datetime.fromisoformat(asked["at"]) > GIVE_UP_AFTER:
            send(
                asked["chat_id"],
                f"⚠️ برای حساب {login} پس از ۲۰ دقیقه جوابی از سرور نیامد. "
                "صفحهٔ حساب‌ها در سایت را ببینید.",
            )
            del pending[request_id]
            reported += 1
    _save(pending)
    return reported
