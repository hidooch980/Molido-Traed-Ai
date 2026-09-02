"""Say when a position opened, on the channel somebody actually reads.

The bot could answer questions and could not tell anybody anything. So the
only way to learn that an order had filled was to think of asking, and the
report you got back was a list of every open position at once - which answers
"what do I hold" and never answers "what just happened". An account holder
watching a system trade wants the second question, and wants it without
asking.

**Not `notify.format_alert`.** That sorts its facts alphabetically, which is
right for an alert whose fields vary and wrong here: fill, lots, side, symbol
is not how anybody reads a trade. The order below is the order the eye wants
- who, what, how big, at what price, and what it risks - and it is fixed
because it is the same every time.

**Every number is the one the broker returned, not the one that was asked
for.** The fill price, the stop and the target come from what the account
actually holds. A notice quoting the intended price would be right almost
always and wrong exactly when somebody most needs to look.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.integrations import notify

#: What one pip is, per instrument shape. Only two cases exist on this
#: watchlist and both are conventions rather than facts the broker publishes,
#: so they live here rather than pretending to be measurements.
JPY_PIP = 0.01
DEFAULT_PIP = 0.0001

#: Metals priced against a currency. Six letters like a pair and not a pair:
#: XAUUSD moves in dollars an ounce, so a 20.85 stop is 20.85 dollars and
#: dividing it by a pip gives 208,500 - a number nobody can act on, which is
#: what this constant exists to prevent. The same shape of mistake as reading
#: COPPER as COP and PER.
METALS = frozenset({"XAU", "XAG", "XPT", "XPD"})

#: Direction, in the language the channel speaks.
SIDES = {"long": "خرید", "buy": "خرید", "short": "فروش", "sell": "فروش"}


def is_currency_pair(symbol: str) -> bool:
    """Whether pips are the honest unit for this instrument.

    Six alphabetic characters is the shape of a pair, and it is not enough:
    the metals wear the same shape and quote in their own units.
    """
    name = str(symbol or "").upper()
    if len(name) != 6 or not name.isalpha():
        return False
    return name[:3] not in METALS and name[3:] not in METALS


def pip_size(symbol: str) -> float:
    """One pip for this instrument.

    Metals and indices are quoted in points that are not pips at all, so the
    distance is reported in price units for them rather than in a unit that
    would be wrong - a gold stop of 20.85 is 20.85 dollars an ounce, and
    calling it 2085 pips would be a number nobody could act on.
    """
    return JPY_PIP if symbol.upper().endswith("JPY") else DEFAULT_PIP


def _distance(symbol: str, a: float | None, b: float | None) -> str:
    """How far apart two prices are, in whichever unit reads honestly."""
    if a is None or b is None:
        return "—"
    gap = abs(float(a) - float(b))
    if is_currency_pair(symbol):
        return f"{gap / pip_size(symbol):.1f} پیپ"
    return f"{gap:g}"


def _price(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return "—"


def position_opened(
    *,
    terminal: str,
    login: str | int | None,
    symbol: str,
    side: str,
    lots: float,
    fill: float | None,
    stop: float | None,
    target: float | None,
    risk_money: float | None = None,
    currency: str = "",
    risk_percent: float | None = None,
    strategy: str | None = None,
    ticket: Any = None,
    at: datetime | None = None,
) -> notify.Message:
    """One filled order, as a message a person can read in three seconds.

    The account is first because it is the question the previous version of
    this channel could not answer at all: eight terminals, and a notice that
    did not say which one had traded was a notice that started a hunt.
    """
    direction = SIDES.get(str(side).lower(), str(side))
    account = f"{terminal} · {login}" if login else terminal

    lines = [
        f"حساب   {account}",
        f"نماد   {symbol} · {direction}",
        f"حجم    {lots:g} لات",
        f"ورود   {_price(fill)}",
        f"حد ضرر {_price(stop)}  ·  {_distance(symbol, fill, stop)}",
        f"هدف    {_price(target)}  ·  {_distance(symbol, fill, target)}",
    ]
    if risk_money is not None:
        percent = f"  ({risk_percent:g}٪)" if risk_percent is not None else ""
        lines.append(f"ریسک   {risk_money:.2f} {currency}{percent}".rstrip())
    if strategy:
        lines.append(f"مغز    {strategy}")
    if ticket:
        lines.append(f"تیکت   {ticket}")

    return notify.Message(
        # Informational: a filled order is the system working, and sending it
        # at a higher urgency would train whoever reads this to ignore the
        # urgencies that mean something.
        urgency=notify.Urgency.INFO,
        title="✅ پوزیشن باز شد",
        body="\n".join(lines),
        at=at or datetime.now(UTC),
        context={
            "terminal": terminal,
            "login": str(login) if login else None,
            "symbol": symbol,
            "side": direction,
            "lots": lots,
            "fill": fill,
            "stop": stop,
            "target": target,
            "strategy": strategy,
            "ticket": str(ticket) if ticket else None,
        },
    )


def announce(session: Any, message: notify.Message) -> dict[str, Any]:
    """Send it, and never let the channel break the cycle that produced it.

    An order has already reached the broker by the time this runs. A telegram
    outage, a revoked token or a rate limit must not raise into the trading
    loop and roll back the record of a position that genuinely exists - the
    account would hold something the journal had forgotten.

    No fingerprint, so nothing is deduplicated: two fills on one symbol are
    two events even when every visible field matches, and collapsing them
    would hide the second position from the only place it was announced.
    """
    from app.integrations import telegram

    try:
        delivery = telegram.send(message, session=session)
        return {"sent": delivery.sent, "reason": delivery.reason}
    except Exception as problem:  # noqa: BLE001 - reported, never fatal
        return {
            "sent": False,
            "reason": f"{type(problem).__name__} while announcing the fill",
        }


__all__ = ["announce", "is_currency_pair", "pip_size", "position_opened"]
