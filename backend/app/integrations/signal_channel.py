"""Trade signals to a Telegram channel: what the fleet opened, and how it closed.

Only real trades. A brain's decision that a gate refused is not a signal, and
posting those would fill the channel with trades nobody took. So this reads
what the terminals themselves publish - open positions and closed deals - and
posts the difference since it last looked:

  * **A new position** is posted once as a signal: symbol, side, entry, stop,
    target. The fleet runs several accounts, and two of them taking the same
    symbol and side is one idea, not two - so a (symbol, side) posted in the
    last `SAME_SIGNAL_WINDOW` is not posted again.
  * **A posted position that is gone** is posted as closed, with its result
    in R against the stop it was announced with, and the exit price from the
    matching closed deal when the terminal published one.

**The first look posts nothing.** It records what is already open and already
closed, so switching the channel on does not replay a week of trades.

It sends only to the configured channel, never to the admins, and it reads
the bridge files only - nothing here can place, change or close an order.
State lives in one small JSON file beside the chat worker's other state.
"""

from __future__ import annotations

import json
import os
import pathlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.logging import get_logger

log = get_logger(__name__)

#: A second account taking the same symbol and side inside this window is the
#: same signal.
SAME_SIGNAL_WINDOW = timedelta(hours=2)

#: Closed deals remembered as already matched; older ones are forgotten.
KEEP_DEALS = 1000

DEFAULT_STATE_FILE = "/var/lib/molido/state/signal-channel.json"


@dataclass
class Book:
    """One terminal's published view."""

    readable: bool
    positions: list[dict[str, Any]] = field(default_factory=list)
    deals: list[dict[str, Any]] = field(default_factory=list)


def _state_path() -> pathlib.Path:
    return pathlib.Path(os.environ.get("MOLIDO_SIGNAL_STATE_FILE") or DEFAULT_STATE_FILE)


def load_state() -> dict[str, Any] | None:
    try:
        state = json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) else None


def save_state(state: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    tmp.replace(path)


def _price(value: Any) -> str:
    number = float(value or 0.0)
    return f"{number:.5f}".rstrip("0").rstrip(".") if number else "—"


def _side_fa(side: str) -> str:
    return "خرید" if side == "buy" else "فروش"


def open_text(position: dict[str, Any]) -> str:
    side = str(position.get("side") or "")
    icon = "🟢" if side == "buy" else "🔴"
    target = float(position.get("target") or 0.0)
    return "\n".join(
        [
            f"{icon} سیگنال {_side_fa(side)} {position.get('symbol')}",
            "",
            f"ورود: {_price(position.get('price_open'))}",
            f"حد ضرر: {_price(position.get('stop'))}",
            f"حد سود: {_price(target) if target else 'ندارد'}",
        ]
    )


def _result_r(signal: dict[str, Any], exit_price: float) -> float | None:
    entry = float(signal.get("entry") or 0.0)
    stop = float(signal.get("stop") or 0.0)
    risk = abs(entry - stop)
    if not entry or not stop or risk <= 0 or not exit_price:
        return None
    move = exit_price - entry if signal.get("side") == "buy" else entry - exit_price
    return move / risk


def close_text(signal: dict[str, Any], deal: dict[str, Any] | None) -> str:
    exit_price = float((deal or {}).get("price") or 0.0)
    r = _result_r(signal, exit_price)
    net = (deal or {}).get("net")
    won = (r is not None and r > 0) or (r is None and net is not None and float(net) > 0)
    lost = (r is not None and r < 0) or (r is None and net is not None and float(net) < 0)
    icon = "✅" if won else ("❌" if lost else "⚪️")
    lines = [f"{icon} بسته شد: {_side_fa(str(signal.get('side')))} {signal.get('symbol')}", ""]
    if exit_price:
        lines.append(f"ورود {_price(signal.get('entry'))} ← خروج {_price(exit_price)}")
    if r is not None:
        lines.append(f"نتیجه: {'سود' if r > 0 else 'ضرر' if r < 0 else 'سر به سر'} {r:+.2f}R")
    elif not exit_price:
        lines.append("قیمت خروج هنوز منتشر نشده است.")
    return "\n".join(lines)


def _match_deal(
    signal: dict[str, Any], deals: list[dict[str, Any]], used: set[str]
) -> dict[str, Any] | None:
    """The closing deal for a gone position: same symbol, opposite side."""
    closing_side = "sell" if signal.get("side") == "buy" else "buy"
    for deal in reversed(deals):
        ticket = str(deal.get("ticket") or "")
        if not ticket or ticket in used:
            continue
        if deal.get("symbol") == signal.get("symbol") and deal.get("side") == closing_side:
            used.add(ticket)
            return deal
    return None


def step(
    state: dict[str, Any] | None,
    books: dict[str, Book],
    *,
    now: datetime,
    send: Callable[[str], bool],
) -> dict[str, Any]:
    """Post what changed since `state` and return the new state.

    Pure apart from `send`, so the whole behaviour is testable without a
    terminal or a channel. A message whose send fails is retried on the next
    look rather than recorded as posted.
    """
    all_deals = [
        str(d.get("ticket")) for book in books.values() if book.readable for d in book.deals
    ]
    if state is None:
        # First look: learn, post nothing.
        return {
            "known": sorted(
                f"{key}:{p.get('ticket')}"
                for key, book in books.items()
                if book.readable
                for p in book.positions
            ),
            "signals": {},
            "recent": {},
            "used_deals": all_deals[-KEEP_DEALS:],
        }

    known = set(state.get("known") or [])
    signals: dict[str, dict[str, Any]] = dict(state.get("signals") or {})
    recent: dict[str, str] = dict(state.get("recent") or {})
    used = set(state.get("used_deals") or [])

    for key, book in books.items():
        if not book.readable:
            # An unreadable terminal is not an empty one: nothing it held is
            # declared closed on the strength of a file that did not load.
            continue
        present = {f"{key}:{p.get('ticket')}": p for p in book.positions}

        for ident, position in present.items():
            if ident in known or ident in signals:
                continue
            same = f"{position.get('symbol')}|{position.get('side')}"
            last = recent.get(same)
            if last and now - datetime.fromisoformat(last) < SAME_SIGNAL_WINDOW:
                known.add(ident)
                continue
            if send(open_text(position)):
                signals[ident] = {
                    "symbol": position.get("symbol"),
                    "side": position.get("side"),
                    "entry": float(position.get("price_open") or 0.0),
                    "stop": float(position.get("stop") or 0.0),
                    "at": now.isoformat(),
                }
                recent[same] = now.isoformat()

        for ident in [i for i in signals if i.startswith(f"{key}:")]:
            if ident in present:
                continue
            signal = signals[ident]
            deal = _match_deal(signal, book.deals, used)
            if send(close_text(signal, deal)):
                del signals[ident]

        known = {i for i in known if not i.startswith(f"{key}:") or i in present}

    cutoff = now - SAME_SIGNAL_WINDOW
    recent = {k: v for k, v in recent.items() if datetime.fromisoformat(v) >= cutoff}
    return {
        "known": sorted(known),
        "signals": signals,
        "recent": recent,
        "used_deals": sorted(used | set(all_deals))[-KEEP_DEALS:],
    }


def _books(session: Any) -> dict[str, Book]:
    from app.providers.metatrader import MetaTraderBridge, bridge_dirs

    out: dict[str, Book] = {}
    for key, path in bridge_dirs(session=session).items():
        bridge = MetaTraderBridge(directory=path)
        held = bridge.positions()
        closed = bridge.deals()
        out[str(key)] = Book(
            readable=bool(held.get("available")),
            positions=list(held.get("positions") or []),
            deals=list(closed.get("deals") or []),
        )
    return out


def run(session: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """One look: read every terminal, post the changes to the channel."""
    from app.integrations import telegram
    from app.services import telegram_settings

    channel = telegram_settings.load(session)
    if not (channel.token and channel.enabled and channel.signal_channel):
        return {"posted": 0, "reason": "no signal channel is configured"}

    posted = 0

    def send(text: str) -> bool:
        nonlocal posted
        ok, payload = telegram.api_call(
            "sendMessage",
            {"chat_id": channel.signal_channel, "text": text},
            token=channel.token,
        )
        if ok:
            posted += 1
        else:
            log.warning("signal_channel.send_failed", reason=str(payload)[:200])
        return bool(ok)

    state = step(load_state(), _books(session), now=now or datetime.now(UTC), send=send)
    save_state(state)
    return {"posted": posted, "open_signals": len(state["signals"])}
