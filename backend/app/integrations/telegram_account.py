"""Connect a broker account from Telegram, through the same queue the site uses.

`/addaccount <login> <server> <password>` - or with a terminal first,
`/addaccount <terminal> <login> <server> <password>` - validates exactly as
the site's form does (`mt5_link.validate`) and writes the same request for
the host agent. Nothing new reaches MetaTrader; only the door is new.

**The password is a chat message, so the message is deleted.** The bot asks
Telegram to delete it the moment it is read, never echoes it, never logs it,
and keeps it nowhere - it goes into the queue file the agent consumes, as it
does from the site. It still crossed Telegram's servers, and the help says so.

The agent's answer takes up to seven minutes. `pending` remembers which chat
asked, and `check_pending` - called by the chat worker once a minute - sends
the result there when it arrives, or says so if the agent never answers.
"""

from __future__ import annotations

import json
import os
import pathlib
from collections.abc import Callable
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
        if answer.get("known"):
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
