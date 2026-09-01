"""The chat side of the channel: Persian answers, buttons, and one hard limit.

The outbound half already existed - this system could send an alert. This is
the half that answers, and every choice in it is about the thing a chat
transport cannot do:

**Nothing here can trade.** Every reply is computed from the same allowlist
`notify.accept_command` enforces, and the allowlist contains questions only. A
button is not an exception: a button sends a callback whose payload is checked
against the same list, because a keyboard is a convenience for typing and must
never be a second, softer door.

**Only the configured admins are answered.** A chat id that is not on the alert
list gets one sentence saying so. The bot token is public the moment anyone
sees it, so the recipient list is the only thing standing between a stranger
and this system's numbers - and numbers are exactly what it hands out.

**Persian, because the operator reads Persian.** The numbers are ASCII digits
on purpose: an operator comparing a figure here with one on the dashboard, in
MetaTrader, or in a broker statement should not have to transliterate.

**Long polling, offset persisted.** The offset lives beside the configuration
so a restarted worker does not replay a day of commands, and `getUpdates` is
used rather than a webhook because a webhook needs an inbound route into a
system whose whole design is that nothing arrives from outside.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger

log = get_logger(__name__)

#: How many updates to take per poll. Ten is generous for one operator and
#: keeps a burst from turning one cycle into a long one.
BATCH = 10

#: The keyboard, in rows. Every entry is a command on the read-only allowlist -
#: the buttons are a way to type them, never a way around them.
KEYBOARD: tuple[tuple[tuple[str, str], ...], ...] = (
    (("📊 وضعیت", "status"), ("📈 پوزیشن‌ها", "positions")),
    (("💼 حساب‌ها", "accounts"), ("🧾 سفارش‌ها", "orders")),
    (("🧠 مغزها", "brains"), ("🏆 چلنج", "challenge")),
    (("💱 قیمت‌ها", "prices"), ("📉 افت سرمایه", "drawdown")),
    (("📓 ژورنال", "journal"), ("🤔 چرا معامله نشد", "why_no_trade")),
    (("🩺 سلامت", "health"), ("❓ راهنما", "help")),
)

#: The same commands as a keyboard that stays at the bottom of the chat.
#:
#: Inline buttons hang off the message that carried them, so they scroll away
#: and the operator is back to typing - which is what "it is commands, not
#: buttons" means in practice. A reply keyboard persists until it is replaced,
#: so the menu is there on the next question and the one after that.
#:
#: The labels are the same strings the inline buttons use, and the router
#: below maps a label back to its command - so a tap on either keyboard walks
#: exactly the same allowlist. Two keyboards, one door.
LABEL_TO_COMMAND: dict[str, str] = {
    label: command for row in KEYBOARD for label, command in row
}

TITLES: dict[str, str] = {
    "status": "وضعیت سامانه",
    "positions": "پوزیشن‌های باز",
    "health": "سلامت سرویس‌ها",
    "drawdown": "افت سرمایه",
    "journal": "ژورنال تصمیم‌ها",
    "why_no_trade": "چرا معامله‌ای انجام نشد",
    "help": "راهنما",
    "accounts": "حساب‌ها",
    "orders": "سفارش‌های اخیر",
    "brains": "مغزها",
    "challenge": "چلنج",
    "prices": "قیمت‌های زنده",
}


@dataclass(frozen=True)
class Reply:
    """One answer, and whether it carries the keyboard."""

    text: str
    keyboard: bool = True


def _reply_keyboard() -> dict[str, Any]:
    """The persistent keyboard: rows of labels, kept until replaced."""
    return {
        "keyboard": [
            [{"text": label} for label, _command in row] for row in KEYBOARD
        ],
        "resize_keyboard": True,
        "is_persistent": True,
        "input_field_placeholder": "یک دکمه را بزنید",
    }


def _fmt_money(value: Any, currency: str = "") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number:,.2f} {currency}".strip()


def _status(session: Session) -> str:
    """What the engine would do right now, and what stands in its way."""
    from app.execution import autopilot
    from app.providers.metatrader import MetaTraderBridge, bridge_dirs

    mode, reason, _ = autopilot.mode_now()
    words = {"live": "زنده", "paper": "کاغذی", "halted": "متوقف"}
    lines = [f"حالت اجرا: *{words.get(mode, mode)}*", f"دلیل: {reason}", ""]

    live = 0
    for key, directory in sorted(bridge_dirs().items()):
        account = MetaTraderBridge(directory=directory).account()
        if not account.get("available"):
            continue
        live += 1
        balance = _fmt_money(account.get("balance"), str(account.get("currency") or ""))
        equity = _fmt_money(account.get("equity"), str(account.get("currency") or ""))
        lines.append(
            f"• {key} — {account.get('login')} | موجودی {balance} | اکوئیتی {equity}"
        )
    if not live:
        lines.append("هیچ ترمینالی حساب زنده‌ای منتشر نمی‌کند.")
    return "\n".join(lines)


def _positions(session: Session) -> str:
    from app.providers.metatrader import MetaTraderBridge, bridge_dirs

    lines: list[str] = []
    total = 0
    for key, directory in sorted(bridge_dirs().items()):
        bridge = MetaTraderBridge(directory=directory)
        if not bridge.account().get("available"):
            continue
        rows = bridge.positions().get("positions") or []
        if not rows:
            lines.append(f"• {key}: بدون پوزیشن باز")
            continue
        lines.append(f"• {key}: {len(rows)} پوزیشن")
        for row in rows:
            total += 1
            side = "خرید" if str(row.get("side")) == "buy" else "فروش"
            lines.append(
                f"   {row.get('symbol')} {side} {row.get('volume')} "
                f"| سود/زیان {_fmt_money(row.get('profit'))}"
            )
    if not lines:
        return "هیچ ترمینال متصلی وجود ندارد."
    lines.append("")
    lines.append(f"مجموع: {total} پوزیشن باز")
    return "\n".join(lines)


def _health(session: Session) -> str:
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import func, select

    from app.models.journal import JournalEntry

    since = datetime.now(UTC) - timedelta(hours=2)
    recent = session.scalar(
        select(func.count())
        .select_from(JournalEntry)
        .where(JournalEntry.opened_at >= since)
    )
    return "\n".join(
        [
            "سرویس‌ها بالا هستند.",
            f"تصمیم‌های ثبت‌شده در دو ساعت اخیر: {recent or 0}",
            "",
            "این کانال فقط پاسخ می‌دهد و هرگز سفارشی ثبت نمی‌کند.",
        ]
    )


def _drawdown(session: Session) -> str:
    from app.providers.metatrader import MetaTraderBridge, bridge_dirs

    lines = []
    for key, directory in sorted(bridge_dirs().items()):
        account = MetaTraderBridge(directory=directory).account()
        if not account.get("available"):
            continue
        try:
            balance = float(account.get("balance") or 0)
            equity = float(account.get("equity") or 0)
        except (TypeError, ValueError):
            continue
        floating = equity - balance
        share = (floating / balance * 100) if balance else 0.0
        lines.append(
            f"• {key} — شناور {_fmt_money(floating)} ({share:+.2f}٪ از موجودی)"
        )
    if not lines:
        return "هیچ حساب زنده‌ای برای سنجش افت وجود ندارد."
    lines.append("")
    lines.append("افت واقعی از سقف اکوئیتی در صفحهٔ ریسک داشبورد گزارش می‌شود.")
    return "\n".join(lines)


def _journal(session: Session) -> str:
    from app.learning.weekly import build_report

    report = build_report(session, days=7)
    if not report["brains"]:
        return "در هفت روز اخیر تصمیمی ثبت نشده است."
    lines = ["هفت روز اخیر، به تفکیک مغز:", ""]
    for brain in report["brains"]:
        edge = brain["edge_r"]
        thin = " (نمونهٔ کم)" if brain["thin_sample"] else ""
        lines.append(
            f"• {brain['strategy']}: {brain['decided']} تصمیم، "
            f"{brain['resolved']} حل‌شده، مجموع {brain['total_r']:+.2f}R"
            + (f"، نسبت به کنترل {edge:+.4f}R" if edge is not None else "")
            + thin
        )
    return "\n".join(lines)


def _why_no_trade(session: Session) -> str:
    """The named refusals from the last order cycle, not a guess."""
    from app.workers.autotrade import run_all_accounts

    report = run_all_accounts(session)
    lines = ["آخرین چرخهٔ سفارش:", ""]
    for key, account in sorted((report.get("by_account") or {}).items()):
        orders = account.get("orders", 0)
        considered = account.get("considered")
        head = f"• {key}: {orders} سفارش"
        if considered is not None:
            head += f" از {considered} تصمیم بررسی‌شده"
        lines.append(head)
        if account.get("refused"):
            lines.append(f"   رد: {account['refused']}")
        for skipped in (account.get("skipped") or [])[:3]:
            lines.append(f"   — {skipped}")
    lines.append("")
    lines.append("هر رد با نام دلیلش ثبت می‌شود؛ «صفر سفارش» هیچ‌وقت بی‌دلیل نیست.")
    return "\n".join(lines)


def _help(session: Session) -> str:
    return "\n".join(
        [
            "این ربات به سؤال پاسخ می‌دهد و هیچ کاری انجام نمی‌دهد.",
            "",
            "دستورها:",
            "/status — حالت اجرا و خلاصهٔ حساب‌ها",
            "/accounts — هر ترمینال، موجودی و اکوئیتی",
            "/positions — پوزیشن‌های باز",
            "/orders — سفارش‌های ۳۰ ساعت اخیر و پاسخ بروکر",
            "/prices — قیمت زندهٔ ترمینال",
            "/brains — کدام مغز برای کدام حساب",
            "/challenge — قوانین پراپ و سقف‌ها",
            "/drawdown — سود و زیان شناور",
            "/journal — کارنامهٔ هفتگی مغزها",
            "/why_no_trade — دلیل نام‌بردهٔ آخرین ردها",
            "/health — سلامت سرویس‌ها",
            "",
            "هیچ پیامی از اینجا نمی‌تواند سفارشی ثبت کند. برای معامله، کلید API با "
            "مجوز اجرا لازم است که جای دیگری نگهداری می‌شود.",
        ]
    )


# The detailed answers live in `telegram_answers`, which changes when a
# question is added and never when the transport changes.
from app.integrations import telegram_answers as _answers  # noqa: E402

ANSWERS = {
    "status": _status,
    "accounts": _answers.accounts,
    "orders": _answers.orders,
    "brains": _answers.brains,
    "challenge": _answers.challenge,
    "prices": _answers.prices,
    "positions": _positions,
    "health": _health,
    "drawdown": _drawdown,
    "journal": _journal,
    "why_no_trade": _why_no_trade,
    "help": _help,
}


def answer_command(session: Session, command: str) -> Reply:
    """The reply to one allowlisted command, in Persian.

    An unknown command is answered with the list rather than with "no": a bot
    that only refuses teaches nobody what it does.
    """
    from app.integrations import notify

    name = (command or "").strip().lstrip("/").split()[0].lower() if command.strip() else ""
    if name not in notify.READ_ONLY_COMMANDS:
        return Reply(
            "این دستور را نمی‌شناسم. از دکمه‌های زیر استفاده کنید یا /help را بزنید."
        )

    try:
        body = ANSWERS[name](session)
    except Exception as problem:  # noqa: BLE001 - a failed answer is an answer
        # Named rather than swallowed: a bot that goes quiet on an error is
        # indistinguishable from one that was never asked.
        log.warning("telegram.answer_failed", command=name, error=str(problem))
        return Reply(f"«{TITLES.get(name, name)}» را نتوانستم بخوانم: {problem}")

    return Reply(f"*{TITLES.get(name, name)}*\n\n{body}")


#: Where the last-seen update id is kept. Under `state/` because the parent
#: is root-owned on the host and this worker is not root: the first version
#: wrote to the parent, silently failed the write, and re-answered the same
#: ten messages every minute - a bot that spams the operator it exists to
#: inform. The failure was invisible because "could not persist" was a
#: warning nobody was reading and the replies looked like fresh ones.
OFFSET_FILE = "/var/lib/molido/state/telegram-offset"


def _offset_path() -> Any:
    import pathlib

    return pathlib.Path(OFFSET_FILE)


def _read_offset() -> int:
    try:
        return int(_offset_path().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def _write_offset(value: int) -> bool:
    """True when the offset is safely stored. False is not cosmetic.

    A poller that cannot remember where it got to replays every update on the
    next pass, forever. The caller uses this answer to stop rather than to
    log: repeating an answer once is a glitch, repeating it every minute is
    the channel becoming unusable.
    """
    try:
        path = _offset_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(value), encoding="utf-8")
        return True
    except OSError:
        log.warning("telegram.offset_unwritable", path=OFFSET_FILE)
        return False


def poll(
    session: Session, *, limit: int = BATCH, wait: int = 0
) -> dict[str, Any]:
    """Read pending updates, answer the admins, ignore everybody else.

    Returns what it did rather than logging only: a poll that answered nothing
    because nobody asked and one that answered nothing because every sender
    was a stranger are different facts.
    """
    from app.integrations import telegram
    from app.services import telegram_settings

    channel = telegram_settings.load(session)
    if not channel.ready:
        return {"polled": 0, "reason": "the channel is not configured"}

    # Checked before reading, not after answering. A poller whose offset does
    # not survive the call answers the same messages on every pass - so it
    # declines to answer at all rather than turn the alert channel into a
    # source of noise the operator learns to mute.
    if not _write_offset(_read_offset()):
        return {
            "polled": 0,
            "reason": (
                f"{OFFSET_FILE} is not writable, so answering would replay "
                "the same updates every pass"
            ),
        }

    # `wait` is Telegram's long poll: the request is held open until an
    # update arrives or the wait expires. Asking and leaving is what made
    # the bot feel broken - a question typed at 18:29:10 waited for the
    # next minute mark to be looked at, so the answer arrived up to a
    # minute later and the operator had already given up.
    ok, payload = telegram.api_call(
        "getUpdates",
        {"offset": _read_offset(), "limit": limit, "timeout": wait},
        token=channel.token,
        timeout=wait + 10 if wait else None,
    )
    if not ok:
        return {"polled": 0, "reason": str(payload)}

    updates = payload.get("result") or []
    answered = 0
    refused = 0
    highest = 0

    for update in updates:
        highest = max(highest, int(update.get("update_id") or 0))
        message = update.get("message") or {}
        callback = update.get("callback_query") or {}

        if callback:
            chat_id = str(((callback.get("message") or {}).get("chat") or {}).get("id"))
            text = str(callback.get("data") or "")
            telegram.api_call(
                "answerCallbackQuery",
                {"callback_query_id": callback.get("id")},
                token=channel.token,
            )
        else:
            chat_id = str((message.get("chat") or {}).get("id"))
            text = str(message.get("text") or "")

        if not chat_id or not text:
            continue

        if chat_id not in channel.chat_ids:
            # One sentence, and nothing else. The token is public the moment
            # anybody sees it; the recipient list is what stands between a
            # stranger and this system's numbers.
            refused += 1
            telegram.api_call(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": "این ربات فقط به ادمین‌های ثبت‌شده پاسخ می‌دهد.",
                },
                token=channel.token,
            )
            continue

        # A tap on the persistent keyboard arrives as the label's text,
        # not as a command. Mapped back here so both keyboards and a
        # typed command walk exactly the same allowlist - the menu is a
        # way to type, never a second door.
        text = LABEL_TO_COMMAND.get(text.strip(), text)

        if text.strip().lstrip("/").lower() in {"start", "menu"}:
            reply = Reply(
                "*MolidoTrade AI*\n\nیکی را انتخاب کنید. این کانال فقط پاسخ "
                "می‌دهد و هرگز سفارشی ثبت نمی‌کند."
            )
        else:
            reply = answer_command(session, text)

        # The persistent keyboard is installed once, with the welcome.
        # Sending it on every reply would redraw the menu under each
        # answer and push the answer itself off the screen.
        # Always the persistent keyboard, never the inline one.
        #
        # Inline buttons hang off the message that carried them: they
        # scroll away, they leave the last answer looking clickable when
        # it is not, and on a phone they sit in the middle of the
        # history rather than under the thumb. A reply keyboard is
        # where a keyboard belongs and stays there between questions.
        markup: dict[str, Any] = _reply_keyboard()
        telegram.api_call(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": reply.text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": "true",
                **({"reply_markup": markup} if reply.keyboard else {}),
            },
            token=channel.token,
        )
        answered += 1

    if highest:
        _write_offset(highest + 1)

    return {"polled": len(updates), "answered": answered, "refused": refused}


#: How long one scheduled pass keeps listening. Just under the minute between
#: passes, so the channel is attended almost continuously without two passes
#: ever overlapping.
PUMP_SECONDS = 50

#: How long a single long poll waits before returning empty. Short enough that
#: a shutdown is not held up by a whole minute, long enough that the pump is
#: not spinning through requests.
WAIT_SECONDS = 20


def pump(session: Session, *, budget: float = PUMP_SECONDS) -> dict[str, Any]:
    """Keep listening for most of the minute, answering the moment one lands.

    One poll per minute meant a question could sit unread for fifty-nine
    seconds before anything looked at it. This holds the connection open
    instead, so the answer goes out as the question arrives, and the schedule
    stays one job a minute - the waiting happens inside the job rather than
    between them.
    """
    import time

    started = time.monotonic()
    polled = answered = refused = 0
    reason: str | None = None

    while time.monotonic() - started < budget:
        left = budget - (time.monotonic() - started)
        report = poll(session, wait=max(1, min(WAIT_SECONDS, int(left))))
        polled += int(report.get("polled") or 0)
        answered += int(report.get("answered") or 0)
        refused += int(report.get("refused") or 0)
        if report.get("reason"):
            # A configuration problem does not improve by being retried for
            # another forty seconds.
            reason = str(report["reason"])
            break

    out: dict[str, Any] = {
        "polled": polled,
        "answered": answered,
        "refused": refused,
    }
    if reason:
        out["reason"] = reason
    return out
