"""Update the server from Telegram: a request written down, never an action taken.

The owner cannot always reach a shell, and every fix in September waited on
somebody typing `./infra/deploy.sh`. This lets an admin ask for that from the
chat - and nothing more:

  * **The bot runs nothing.** It writes one small file under the shared state
    directory. A timer on the host (`infra/host/molido-update.sh`) picks it
    up and runs the same `deploy.sh` a person would, which only ever
    fast-forwards to `origin/main`. No argument from the chat reaches a
    shell, so the worst a stolen admin chat can do is redeploy reviewed code.
  * **Two steps.** `/update` answers with a six-digit code, valid for five
    minutes and only in the chat that asked; `/update_confirm <code>` writes
    the request. A stray tap or a replayed message does not redeploy.
  * **Nothing here can trade.** This module is not in `READ_ONLY_COMMANDS`
    and imports nothing from the order path; the allowlist is untouched.

The host sends the result (started, finished with the commit, or failed)
through `app.ops.host_alert`, so the answer arrives in the same chat.
"""

from __future__ import annotations

import hmac
import json
import os
import pathlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.logging import get_logger

log = get_logger(__name__)

#: How long a confirmation code is good for.
CODE_TTL = timedelta(minutes=5)

DEFAULT_STATE_DIR = "/var/lib/molido/state"


def _state_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get("MOLIDO_UPDATE_STATE_DIR") or DEFAULT_STATE_DIR)


def _code_file() -> pathlib.Path:
    return _state_dir() / "update-code.json"


def request_file() -> pathlib.Path:
    """Where the host timer looks. Its name is part of the host script's contract."""
    return _state_dir() / "update-request.json"


def _write(path: pathlib.Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(path)


def start(chat_id: str, *, now: datetime | None = None) -> str:
    """Issue a one-time code for this chat."""
    moment = now or datetime.now(UTC)
    code = f"{secrets.randbelow(1_000_000):06d}"
    try:
        _write(
            _code_file(),
            {
                "code": code,
                "chat_id": str(chat_id),
                "expires": (moment + CODE_TTL).isoformat(),
            },
        )
    except OSError as exc:
        return f"درخواست ثبت نشد: پوشهٔ وضعیت سرور نوشتنی نیست ({exc})."
    return "\n".join(
        [
            "به‌روزرسانی سرور به آخرین نسخهٔ تأییدشده (شاخهٔ main در گیت‌هاب).",
            "",
            "در این مدت چند دقیقه سایت و ربات در دسترس نیستند. معامله‌های باز "
            "دست نمی‌خورند.",
            "",
            "برای تأیید، ظرف ۵ دقیقه همین را بفرستید (لمس کنید تا کپی شود):",
            # In a code span: the reply is sent as Markdown, where the lone
            # underscore would start an italic that never closes and Telegram
            # would refuse the whole message.
            f"`/update_confirm {code}`",
        ]
    )


def confirm(chat_id: str, text: str, *, now: datetime | None = None) -> str:
    """Write the request if the code matches, is fresh and came from the same chat."""
    moment = now or datetime.now(UTC)
    parts = (text or "").split()
    given = parts[1] if len(parts) > 1 else ""

    try:
        issued = json.loads(_code_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "کدی صادر نشده است. اول /update را بفرستید."

    expires = datetime.fromisoformat(str(issued.get("expires") or "1970-01-01T00:00:00+00:00"))
    same_chat = str(issued.get("chat_id")) == str(chat_id)
    matches = hmac.compare_digest(str(issued.get("code") or ""), given)
    if not (same_chat and matches):
        # One try per code: a wrong answer spends it, so six digits cannot be
        # walked by repetition.
        _code_file().unlink(missing_ok=True)
        return "کد درست نیست. دوباره /update را بفرستید."
    if moment > expires:
        _code_file().unlink(missing_ok=True)
        return "کد منقضی شده است. دوباره /update را بفرستید."

    # One use. Removed before the request is written, so a second confirm
    # with the same code finds nothing even if the write below fails.
    _code_file().unlink(missing_ok=True)
    try:
        _write(request_file(), {"requested_by": str(chat_id), "at": moment.isoformat()})
    except OSError as exc:
        return f"درخواست ثبت نشد: پوشهٔ وضعیت سرور نوشتنی نیست ({exc})."
    log.warning("telegram.update_requested", chat_id=str(chat_id))
    return "\n".join(
        [
            "✅ درخواست به‌روزرسانی ثبت شد.",
            "",
            "سرور ظرف یک دقیقه شروع می‌کند و کار ۵ تا ۱۰ دقیقه طول می‌کشد.",
            "شروع و نتیجه را همین‌جا در تلگرام می‌فرستد.",
        ]
    )


def handle(chat_id: str, text: str) -> str | None:
    """The reply for an update command, or None when `text` is not one."""
    name = (text or "").strip().lstrip("/").split()[0].lower() if (text or "").strip() else ""
    if name == "update":
        return start(chat_id)
    if name == "update_confirm":
        return confirm(chat_id, text)
    return None
