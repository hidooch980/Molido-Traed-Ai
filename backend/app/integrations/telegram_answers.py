"""The detailed answers, kept apart from the transport that carries them.

`telegram_bot` owns the loop, the allowlist and the keyboards. This owns what
the replies actually say, and it is a separate file because those two change
for different reasons: a new question is written here and nothing about
polling moves, while a change to how the channel authenticates touches none
of the text below.

Every function reads and returns a string. None of them can place an order,
because none of them can reach anything that does.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session


def _money(value: Any, currency: str = "") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number:,.2f} {currency}".strip()


def accounts(session: Session) -> str:
    """Every terminal, whether it is signed in, and what it holds.

    A terminal that is off and one that is logged out are both "no account"
    downstream and want opposite responses from whoever reads this, so the
    bridge's own reason is quoted rather than collapsed into a dash.
    """
    from app.providers.metatrader import MetaTraderBridge, bridge_dirs

    lines: list[str] = []
    for key, directory in sorted(bridge_dirs().items()):
        account = MetaTraderBridge(directory=directory).account()
        if not account.get("available"):
            reason = str(account.get("reason") or "در دسترس نیست")[:60]
            lines.append(f"⚪️ {key} — {reason}")
            continue
        currency = str(account.get("currency") or "")
        kind = "دمو" if account.get("trade_mode") == 0 else "واقعی"
        allowed = "مجاز" if account.get("trade_allowed") else "غیرمجاز"
        lines.append(
            f"🟢 {key} — {account.get('login')} ({kind})\n"
            f"    سرور: {account.get('server')}\n"
            f"    موجودی: {_money(account.get('balance'), currency)}\n"
            f"    اکوئیتی: {_money(account.get('equity'), currency)}\n"
            f"    مارجین آزاد: {_money(account.get('free_margin'), currency)}\n"
            f"    اهرم: ۱:{account.get('leverage')} | معامله: {allowed}"
        )
    return "\n".join(lines) if lines else "هیچ ترمینالی پیکربندی نشده است."


def orders(session: Session) -> str:
    """What was sent, and what the broker said back - in the broker's words.

    "rejected" alone sends somebody hunting. "10030 unsupported filling mode"
    names the fix, and on this deployment those two readings were four hours
    apart.
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.models.journal import JournalEntry

    since = datetime.now(UTC) - timedelta(hours=30)
    rows = session.scalars(
        select(JournalEntry)
        .where(JournalEntry.opened_at >= since)
        .order_by(JournalEntry.opened_at.desc())
    ).all()

    listed: list[str] = []
    filled = rejected = 0
    for row in rows:
        for login, order in ((row.during or {}).get("orders") or {}).items():
            state = str(order.get("state") or "")
            if "filled" in state:
                filled += 1
                mark = "✅"
            elif "rejected" in state:
                rejected += 1
                mark = "❌"
            else:
                mark = "⏳"
            if len(listed) < 12:
                side = "خرید" if row.decision == "long" else "فروش"
                detail = str(order.get("reason") or "")[:38]
                listed.append(
                    f"{mark} {row.symbol} {side} {order.get('lots')} — {login} {detail}"
                )

    if not listed:
        return "در ۳۰ ساعت گذشته سفارشی ارسال نشده است."
    return (
        f"۳۰ ساعت اخیر: {filled} پرشده، {rejected} ردشده\n\n"
        + "\n".join(listed)
    )


def brains(session: Session) -> str:
    """Which brain decides for which account, and how many must agree."""
    from app.learning import rules as rules_module
    from app.providers.metatrader import MetaTraderBridge, bridge_dirs
    from app.workers.autotrade import _consensus_required, _strategy_for

    lines = [f"مغزهای ثبت‌شده: {len(rules_module.CANDIDATES)}", ""]
    lines += [f"• {name}" for name in sorted(rules_module.CANDIDATES)]
    lines += ["", f"توافق لازم برای سفارش: {_consensus_required()} مغز", ""]

    for key, directory in sorted(bridge_dirs().items()):
        account = MetaTraderBridge(directory=directory).account()
        if not account.get("available"):
            continue
        login = str(account.get("login") or "")
        strategy, refusal = _strategy_for(login)
        lines.append(f"• {key} ({login}) ← {strategy or refusal[:50]}")

    lines += [
        "",
        "هر مغز تصمیمش را ثبت می‌کند، چه معامله کند چه نه — برای همین "
        "می‌شود بعداً پرسید کدام ترکیب بهتر بود.",
    ]
    return "\n".join(lines)


def challenge(session: Session) -> str:
    """The prop rulebook, with every limit stated in money as well as percent.

    A percentage is what the firm publishes; a number of dollars is what the
    account holder can compare against an equity figure without arithmetic.
    """
    from app.services import challenge_accounts

    views = challenge_accounts.listing(
        session, tenant_id=challenge_accounts.default_tenant(session)
    )
    if not views:
        return "هیچ حساب چلنجی ثبت نشده است."

    lines: list[str] = []
    for view in views:
        account = view.account
        book = view.rulebook
        state = "فعال" if account.is_active else "غیرفعال"
        confirmed = "تأییدشده" if account.rules_confirmed else "تأیید نشده ⚠️"
        lines.append(f"• {account.label} — {state} | قوانین: {confirmed}")
        lines.append(
            f"    موجودی اولیه: {account.starting_balance} {account.currency}"
        )
        if book is None:
            lines.append(f"    قانون‌نامهٔ {account.rulebook_key} شناخته نشد")
            continue

        rules = book.rules
        start = float(account.starting_balance)
        lines.append(f"    برنامه: {book.provider} · {book.program} · {book.phase}")
        if rules.profit_target_pct:
            lines.append(
                f"    هدف سود: {rules.profit_target_pct * 100:.0f}٪ = "
                f"{start * rules.profit_target_pct:,.0f} {account.currency}"
            )
        if rules.max_daily_drawdown_pct:
            lines.append(
                f"    سقف ضرر روزانه: {rules.max_daily_drawdown_pct * 100:.0f}٪ = "
                f"{start * rules.max_daily_drawdown_pct:,.0f}"
            )
        if rules.max_total_drawdown_pct:
            lines.append(
                f"    سقف ضرر کل: {rules.max_total_drawdown_pct * 100:.0f}٪ = "
                f"{start * rules.max_total_drawdown_pct:,.0f}"
            )
        if rules.min_trading_days:
            lines.append(f"    حداقل روز معاملاتی: {rules.min_trading_days}")
    return "\n".join(lines)


def prices(session: Session) -> str:
    """The terminal's own quotes - the prices an order would actually meet.

    Read from a signed-in terminal rather than from the public feed, because
    the two differ by a third of a stop distance on the majors and only one
    of them fills an order.
    """
    from app.providers.metatrader import MetaTraderBridge, bridge_dirs

    wanted = ("XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "BTCUSD")
    for _key, directory in sorted(bridge_dirs().items()):
        bridge = MetaTraderBridge(directory=directory)
        if not bridge.account().get("available"):
            continue
        published = {
            str(row.get("name")): row
            for row in (bridge.symbols().get("symbols") or [])
        }
        lines: list[str] = []
        for name in wanted:
            row = published.get(name)
            if not row:
                continue
            bid, ask = row.get("bid"), row.get("ask")
            try:
                spread = float(ask) - float(bid)
            except (TypeError, ValueError):
                spread = 0.0
            lines.append(f"• {name}: {bid} / {ask}  (اسپرد {spread:.5f})")
        if lines:
            return "\n".join(lines)
    return "هیچ ترمینال متصلی قیمتی منتشر نمی‌کند."
