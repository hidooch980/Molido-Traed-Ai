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
    #: Which view this is, so its own button can be left out of the inline
    #: menu attached to it.
    view: str = ""


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


#: Views answered with the persistent keyboard rather than the inline menu.
#:
#: `help` is where somebody lands when they are lost and where `/start`
#: resolves to, so installing the keyboard there means it is under the thumb
#: for every answer after it - a reply keyboard survives until replaced.
KEYBOARD_VIEWS: frozenset[str] = frozenset({"help", ""})


def _inline_keyboard(current: str = "") -> dict[str, Any]:
    """The same twelve doors, attached to the answer itself.

    The reply keyboard below the chat never scrolls away, which is why it is
    there. Its cost is distance: reading an answer and wanting the next view
    means leaving the message, finding the keyboard, tapping. Attaching the
    menu to the answer removes that, and keeping both means neither failure -
    the answer carries the menu, and the menu is still there once the answer
    has scrolled off.

    The view being shown is left out of its own menu. A button for the screen
    somebody is already looking at does nothing, and a menu with a dead key
    in it reads as broken.
    """
    rows: list[list[dict[str, str]]] = []
    for row in KEYBOARD:
        buttons = [
            {"text": label, "callback_data": command}
            for label, command in row
            if command != current
        ]
        if buttons:
            rows.append(buttons)
    return {"inline_keyboard": rows}


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
    # The first sentence only. The full reason runs to a paragraph of English
    # and pushed the accounts it was meant to sit above off a phone screen.
    short = str(reason).split(". ")[0][:160]
    lines = [f"حالت اجرا: *{words.get(mode, mode)}*", f"دلیل: {short}", ""]

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
    """The same one-command health report an operator runs on the host.

    It used to say "services are up" and count the last two hours of
    decisions - which is zero every weekend and says nothing about which
    cycle stopped, the question this button is pressed to answer.
    """
    from app.workers.health_report import report

    fresh, text = report(session)
    head = "✅ همهٔ چرخه‌ها تازه‌اند." if fresh else "⚠️ دست‌کم یک چرخه عقب افتاده است."
    return f"{head}\n\n```\n{text}\n```"


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
    lines = ["هفت روز اخیر، به تفکیک مغز (هر پوزیشن یک بار):", ""]
    ordered = sorted(
        report["brains"],
        key=lambda b: (b.get("position_mean_r") is None, -(b.get("position_mean_r") or 0)),
    )
    for brain in ordered:
        mean = brain.get("position_mean_r")
        resolved = brain.get("positions_resolved", 0)
        lines.append(
            f"• {brain['strategy']}: {brain.get('positions', 0)} پوزیشن، "
            f"{resolved} بسته‌شده، {brain.get('position_wins', 0)} برد"
            + (f"، میانگین {mean:+.2f}R" if mean is not None else "")
        )
    lines.append("")
    lines.append(
        "زیر ۵۰ پوزیشن بسته‌شده هیچ حکمی گرفته نمی‌شود. ژورنال همان دید را هر "
        "ساعت دوباره ثبت می‌کند؛ این شمارش آن تکرارها را یکی می‌کند."
    )
    return "\n".join(lines)


#: How far back the refusal view reads.
WHY_WINDOW_HOURS = 30


def _why_no_trade(session: Session) -> str:
    """The refusals the collector already wrote down, read - never re-run.

    This used to call `run_all_accounts`, which is the order cycle itself:
    a button in a channel that promises it cannot place an order ran the
    gates, marked decisions as submitting and called the broker. The chat
    container's bridges are mounted read-only, so the send failed - but a
    decision marked before the send is one the collector then leaves alone.
    Every refusal is already recorded per account in `during["refused"]`,
    so this reads that and nothing else.
    """
    from collections import Counter
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.models.journal import ARM_RULE, JournalEntry

    since = datetime.now(UTC) - timedelta(hours=WHY_WINDOW_HOURS)
    rows = session.execute(
        select(JournalEntry.during).where(
            JournalEntry.arm == ARM_RULE, JournalEntry.opened_at >= since
        )
    ).scalars().all()

    reasons: dict[str, Counter[str]] = {}
    sent: Counter[str] = Counter()
    for during in rows:
        during = during or {}
        for login, refusal in (during.get("refused") or {}).items():
            text = str((refusal or {}).get("reason") or "").split(".")[0][:90]
            reasons.setdefault(str(login), Counter())[text] += 1
        for login, order in (during.get("orders") or {}).items():
            sent[f"{login} {(order or {}).get('state') or '?'}"] += 1

    lines = _last_cycle_lines()
    if not reasons and not sent:
        lines.append(
            f"ژورنال {WHY_WINDOW_HOURS} ساعت اخیر: نه سفارشی و نه ردِ سیگنالی. "
            "یعنی یا تصمیم تازه‌ای نبوده (بازار بسته) یا حساب پیش از رسیدن به "
            "سیگنال‌ها رد شده — آخرین چرخهٔ بالا کدام را می‌گوید."
        )
        return "\n".join(lines)

    lines += [f"{WHY_WINDOW_HOURS} ساعت اخیر، از ژورنال:", ""]
    for login in sorted(set(reasons) | {key.split()[0] for key in sent}):
        states = {k.split(" ", 1)[1]: v for k, v in sent.items() if k.split()[0] == login}
        head = f"• {login}: " + (
            "، ".join(f"{n} {state}" for state, n in sorted(states.items()))
            if states
            else "بدون سفارش"
        )
        lines.append(head)
        for text, count in (reasons.get(login) or Counter()).most_common(3):
            lines.append(f"   — {count}× {text}")
    lines.append("")
    lines.append("این پاسخ فقط می‌خواند؛ هیچ چرخهٔ سفارشی اجرا نمی‌کند.")
    return "\n".join(lines)


def _last_cycle_lines() -> list[str]:
    """What the last order cycle said per account, from the collector's record.

    First, because it is the only place a refusal made before any signal was
    looked at - kill switch, order authorization, risk brain - is visible.
    The journal below cannot hold those: no decision was reached to hold them.
    """
    from app.execution import last_cycle

    record, missing = last_cycle.read()
    if record is None:
        return [f"آخرین چرخهٔ سفارش: ثبت نشده ({missing}).", ""]
    head = f"آخرین چرخهٔ سفارش ({str(record.get('at') or '?')[:16]} UTC): "
    head += f"{record.get('orders', 0)} سفارش، {record.get('accounts', 0)} حساب"
    lines = [head]
    if record.get("reason"):
        lines.append(f"   — {str(record['reason'])[:200]}")
    for login, note in sorted((record.get("per_account") or {}).items()):
        if isinstance(note, dict):
            mostly = "؛ ".join(
                f"{count}× {reason}" for reason, count in (note.get("mostly") or {}).items()
            )
            text = f"{note.get('orders', 0)} سفارش، {note.get('skipped', 0)} رد" + (
                f" — {mostly}" if mostly else ""
            )
        else:
            text = str(note)
        lines.append(f"• {login}: {text[:300]}")
    lines.append("")
    return lines


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

    return Reply(f"*{TITLES.get(name, name)}*\n\n{body}", view=name)


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
        # Both keyboards, because they fail in opposite directions.
        #
        # Inline buttons hang off the message that carried them: they scroll
        # away, and an old answer is left looking clickable when its buttons
        # are five screens up. A reply keyboard stays under the thumb but is
        # a journey from the answer somebody is reading.
        #
        # So the answer carries an inline menu for the next hop, and the
        # reply keyboard stays where a keyboard belongs. Two keyboards, one
        # door: both send the same callback through the same allowlist, and
        # the test that pins every label to `READ_ONLY_COMMANDS` covers both.
        #
        # Telegram allows exactly one `reply_markup` per message, so the two
        # cannot ride together and one has to be chosen per answer.
        #
        # `help` carries the persistent one. It is the view somebody opens
        # when they are lost, it is what `/start` resolves to, and a keyboard
        # that installs itself there is a keyboard that is present for every
        # answer afterwards - it survives until something replaces it.
        #
        # Every other answer carries the inline menu, which is the one that
        # matters while reading: the next view is a tap away instead of a
        # journey to the bottom of the chat.
        markup: dict[str, Any] = (
            _reply_keyboard()
            if reply.view in KEYBOARD_VIEWS
            else _inline_keyboard(reply.view)
        )
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
