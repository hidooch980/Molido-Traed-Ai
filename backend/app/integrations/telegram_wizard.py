"""Adding an account by buttons: the bot asks one field at a time.

`➕ افزودن حساب بروکر` asks for the login, the server and the password in
turn, then hands them to `/addaccount` exactly as if they had been typed in
one message. `➕ افزودن حساب پراپ/عادی` offers the kind and the rulebook as
buttons, asks for the balance and the name, then hands them to `/prop add`.
Validation is theirs; this module only collects.

**The password is never stored.** The state file holds the login and server
between messages; the password arrives in the last message, is used at once
and forgotten, and that message is deleted exactly as `/addaccount`'s is.

A flow ends when it finishes, when `wiz cancel` is tapped, when any command
or keyboard key is sent instead of an answer, or after `EXPIRES_AFTER`.
"""

from __future__ import annotations

import json
import os
import pathlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.integrations.telegram_account import Answer

EXPIRES_AFTER = timedelta(minutes=10)
DEFAULT_STATE_FILE = "/var/lib/molido/state/telegram-wizard.json"

CANCEL = ("❌ انصراف", "wiz cancel")
PREFIX = "wiz"


@dataclass(frozen=True)
class Outcome:
    """What the wizard answered, and whether the message must be deleted."""

    answer: Answer | str
    delete_message: bool = False


def _path() -> pathlib.Path:
    return pathlib.Path(os.environ.get("MOLIDO_TELEGRAM_WIZARD_FILE") or DEFAULT_STATE_FILE)


def _load() -> dict[str, dict[str, str]]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(flows: dict[str, dict[str, str]]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(flows), encoding="utf-8")
    tmp.replace(path)


def _set(chat_id: str, flow: dict[str, str] | None, moment: datetime) -> None:
    flows = _load()
    if flow is None:
        flows.pop(chat_id, None)
    else:
        flows[chat_id] = {**flow, "at": moment.isoformat()}
    _save(flows)


def _get(chat_id: str, moment: datetime) -> dict[str, str] | None:
    flow = _load().get(chat_id)
    if not flow:
        return None
    try:
        started = datetime.fromisoformat(flow["at"])
    except (KeyError, ValueError):
        started = moment - EXPIRES_AFTER * 2
    if moment - started > EXPIRES_AFTER:
        _set(chat_id, None, moment)
        return None
    return flow


def _ask(text: str, *rows: list[tuple[str, str]]) -> Answer:
    return Answer(text, [*rows, [CANCEL]])


def _rulebook_buttons() -> list[list[tuple[str, str]]]:
    from app.brain.rulebooks import RULEBOOKS

    return [[(book.key, f"{PREFIX} book {book.key}")] for book in RULEBOOKS]


def handle(
    session: Any,
    chat_id: str,
    text: str,
    *,
    is_command: bool,
    now: datetime | None = None,
) -> Outcome | None:
    """Advance this chat's flow, or None when the message is not for it.

    `is_command` is true for anything that is a command or a keyboard key
    rather than an answer; it ends a flow in progress and is not consumed.
    """
    moment = now or datetime.now(UTC)
    chat_id = str(chat_id)
    words = (text or "").strip().split()

    if words and words[0].lstrip("/").lower() == PREFIX:
        return _button(chat_id, words[1:], session, moment)

    flow = _get(chat_id, moment)
    if flow is None:
        return None
    if is_command:
        _set(chat_id, None, moment)
        return None
    return _answer(session, chat_id, flow, (text or "").strip(), moment)


def _button(chat_id: str, args: list[str], session: Any, moment: datetime) -> Outcome:
    action = args[0].lower() if args else ""
    if action == "broker":
        _set(chat_id, {"flow": "broker", "step": "login"}, moment)
        return Outcome(_ask("۱/۳ — شمارهٔ حساب (Login) را بفرستید:"))
    if action == "prop":
        _set(chat_id, {"flow": "prop", "step": "kind"}, moment)
        return Outcome(
            _ask(
                "نوع حساب را انتخاب کنید:",
                [("🏆 پراپ چالش", f"{PREFIX} kind challenge"),
                 ("💰 پراپ فاندد", f"{PREFIX} kind funded")],
                [("👤 حساب عادی", f"{PREFIX} kind live")],
            )
        )
    flow = _get(chat_id, moment)
    if action == "cancel":
        _set(chat_id, None, moment)
        return Outcome("لغو شد.")
    if flow and flow.get("flow") == "prop" and action == "kind" and len(args) > 1:
        if args[1] not in {"challenge", "funded", "live"}:
            return Outcome("نوع نامعتبر است.")
        _set(chat_id, {"flow": "prop", "step": "balance", "kind": args[1]}, moment)
        return Outcome(_ask("موجودی شروع را بفرستید (مثلاً 100000):"))
    if flow and flow.get("step") == "book" and action == "book" and len(args) > 1:
        _set(chat_id, {**flow, "step": "label", "book": args[1]}, moment)
        return Outcome(_ask("نام حساب را بفرستید (مثلاً FTMO 100k):"))
    return Outcome("این دکمه منقضی شده. از «⚙️ مدیریت حساب‌ها» دوباره شروع کنید.")


def _answer(
    session: Any, chat_id: str, flow: dict[str, str], text: str, moment: datetime
) -> Outcome:
    from app.integrations import telegram_account, telegram_prop

    step = flow.get("step")
    if flow.get("flow") == "broker":
        if step == "login":
            if not text.isdigit():
                return Outcome(_ask("شماره حساب فقط عدد است. دوباره بفرستید:"))
            _set(chat_id, {**flow, "step": "server", "login": text}, moment)
            return Outcome(_ask("۲/۳ — نام سرور بروکر را بفرستید (مثلاً FTMO-Demo2):"))
        if step == "server":
            if not text or " " in text:
                return Outcome(_ask("نام سرور یک کلمه است. دوباره بفرستید:"))
            _set(chat_id, {**flow, "step": "password", "server": text}, moment)
            return Outcome(
                _ask(
                    "۳/۳ — رمز اصلی (Master) را بفرستید. پیام بلافاصله پاک می‌شود و "
                    "رمز هیچ‌جا نگه داشته نمی‌شود؛ ولی از سرورهای تلگرام می‌گذرد."
                )
            )
        if step == "password":
            _set(chat_id, None, moment)
            reply = telegram_account.handle(
                chat_id, f"/addaccount {flow['login']} {flow['server']} {text}", now=moment
            )
            return Outcome(reply, delete_message=True)

    if flow.get("flow") == "prop":
        if step == "kind":
            return Outcome("نوع حساب را با دکمه‌ها انتخاب کنید.")
        if step == "balance":
            number = text.replace(",", "")
            try:
                ok = float(number) > 0
            except ValueError:
                ok = False
            if not ok:
                return Outcome(_ask("موجودی باید عددی بزرگ‌تر از صفر باشد. دوباره:"))
            if flow.get("kind") == "live":
                _set(chat_id, {**flow, "step": "label", "balance": number}, moment)
                return Outcome(_ask("نام حساب را بفرستید:"))
            _set(chat_id, {**flow, "step": "book", "balance": number}, moment)
            return Outcome(
                _ask("قانون‌نامه را انتخاب کنید (یا کلید آن را تایپ کنید):", *_rulebook_buttons())
            )
        if step == "book":
            if not text or " " in text:
                return Outcome(_ask("کلید قانون‌نامه یک کلمه است:", *_rulebook_buttons()))
            _set(chat_id, {**flow, "step": "label", "book": text}, moment)
            return Outcome(_ask("نام حساب را بفرستید:"))
        if step == "label":
            if not text:
                return Outcome(_ask("نام حساب لازم است:"))
            _set(chat_id, None, moment)
            book = "" if flow.get("kind") == "live" else f" {flow.get('book', '')}"
            added = telegram_prop.handle(
                session, chat_id, f"/prop add {flow['kind']} {flow['balance']}{book} {text}"
            )
            return Outcome(added if added is not None else "انجام نشد.")

    _set(chat_id, None, moment)
    return Outcome("این مرحله شناخته نیست؛ دوباره شروع کنید.")
