"""A local HTTP bridge to MetaTrader 5, run by a Windows Python under Wine.

MetaTrader's Python package is Windows-only and this host is Linux, so the
package cannot be imported by the application directly. It is imported here
instead, by a Python that lives inside the same Wine prefix as the terminal,
and the application reaches it over loopback HTTP.

Bound to 127.0.0.1 and nothing else. This process can read an account and, if
deliberately enabled, place orders on it - which makes it the most dangerous
listener on the machine. It is not on the firewall, not behind Caddy, and not
reachable from outside the host.

Orders are refused unless MOLIDO_MT5_ALLOW_ORDERS is exactly "yes". That
default is not caution for its own sake: this deployment has no proven edge,
the decision chain currently produces zero intents, and an order path that is
open by default is one environment variable away from automating a loss. Read
endpoints are always available, because reading is how the edge gets measured.

Run inside the prefix:

    WINEPREFIX=~/.mt5 wine python.exe infra/mt5_bridge.py
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

HOST = "127.0.0.1"
PORT = int(os.environ.get("MOLIDO_MT5_PORT", "18812"))
ALLOW_ORDERS = os.environ.get("MOLIDO_MT5_ALLOW_ORDERS", "no").strip().lower() == "yes"

#: MetaTrader timeframe names the application is allowed to ask for. Kept as a
#: table rather than resolved dynamically so an unknown string is refused here
#: instead of arriving at the terminal as something it silently reinterprets.
TIMEFRAMES = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
    "W1": "TIMEFRAME_W1",
    "MN1": "TIMEFRAME_MN1",
}

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover - only reachable outside the prefix
    mt5 = None


def _initialised() -> tuple[bool, str | None]:
    """Whether the terminal is up and an account is logged in.

    Both halves matter and they fail differently. A terminal that is not
    running is an operations problem; a terminal running with no account is a
    person problem, and the password that fixes it belongs in MetaTrader's own
    login box rather than anywhere this process can read.
    """
    if mt5 is None:
        return False, "the MetaTrader5 package is not importable in this interpreter"
    if not mt5.initialize():
        code, message = mt5.last_error()
        return False, f"terminal not reachable: {message} ({code})"
    account = mt5.account_info()
    if account is None:
        return False, "the terminal is running but no account is logged in"
    return True, None


def health() -> dict:
    ready, reason = _initialised()
    payload: dict = {
        "ready": ready,
        "reason": reason,
        "orders_enabled": ALLOW_ORDERS,
        "checked_at": datetime.now(UTC).isoformat(),
    }
    if mt5 is not None:
        info = mt5.terminal_info()
        if info is not None:
            payload["terminal"] = {
                "connected": bool(info.connected),
                "trade_allowed": bool(info.trade_allowed),
                "build": info.build,
            }
    return payload


def account() -> dict:
    ready, reason = _initialised()
    if not ready:
        return {"available": False, "reason": reason}
    info = mt5.account_info()
    return {
        "available": True,
        # Balance and equity are different numbers and the difference is the
        # open book. A challenge is failed on equity, so publishing only
        # balance would hide the drawdown that ends the account.
        "balance": float(info.balance),
        "equity": float(info.equity),
        "margin": float(info.margin),
        "free_margin": float(info.margin_free),
        "currency": info.currency,
        "leverage": int(info.leverage),
        "login": int(info.login),
        "server": info.server,
        # Reported rather than assumed: an account the broker has set to
        # read-only looks identical to a live one until an order is refused.
        "trade_allowed": bool(mt5.terminal_info().trade_allowed),
    }


def symbols(pattern: str | None = None) -> dict:
    ready, reason = _initialised()
    if not ready:
        return {"available": False, "reason": reason}
    found = mt5.symbols_get(pattern) if pattern else mt5.symbols_get()
    return {
        "available": True,
        "count": len(found),
        "symbols": [
            {
                "name": s.name,
                "description": s.description,
                "digits": s.digits,
                "point": s.point,
                "contract_size": s.trade_contract_size,
                "tick_value": s.trade_tick_value,
                "tick_size": s.trade_tick_size,
                "volume_min": s.volume_min,
                "volume_max": s.volume_max,
                "volume_step": s.volume_step,
            }
            for s in found[:500]
        ],
    }


def bars(symbol: str, timeframe: str, count: int) -> dict:
    """Recent bars, newest last.

    The most recent bar is dropped. It has not closed, so its high, low and
    close are provisional, and a provisional bar stored beside settled ones is
    how a backtest reads a value that was never available at that moment.
    """
    ready, reason = _initialised()
    if not ready:
        return {"available": False, "reason": reason}
    if timeframe not in TIMEFRAMES:
        return {"available": False, "reason": f"unknown timeframe {timeframe!r}"}
    if not mt5.symbol_select(symbol, True):
        return {"available": False, "reason": f"symbol {symbol!r} is not selectable"}

    period = getattr(mt5, TIMEFRAMES[timeframe])
    rates = mt5.copy_rates_from_pos(symbol, period, 0, min(count, 5000) + 1)
    if rates is None or len(rates) == 0:
        code, message = mt5.last_error()
        return {"available": False, "reason": f"no bars returned: {message} ({code})"}

    settled = rates[:-1]
    return {
        "available": True,
        "symbol": symbol,
        "timeframe": timeframe,
        "dropped_unclosed": 1,
        "bars": [
            {
                "event_time": datetime.fromtimestamp(int(r["time"]), UTC).isoformat(),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r["tick_volume"]),
            }
            for r in settled
        ],
    }


def positions() -> dict:
    ready, reason = _initialised()
    if not ready:
        return {"available": False, "reason": reason}
    open_positions = mt5.positions_get() or ()
    return {
        "available": True,
        "positions": [
            {
                "ticket": int(p.ticket),
                "symbol": p.symbol,
                "side": "buy" if p.type == mt5.POSITION_TYPE_BUY else "sell",
                "volume": float(p.volume),
                "price_open": float(p.price_open),
                "stop": float(p.sl) or None,
                "target": float(p.tp) or None,
                "profit": float(p.profit),
            }
            for p in open_positions
        ],
    }


ROUTES = {
    "/health": lambda q: health(),
    "/account": lambda q: account(),
    "/positions": lambda q: positions(),
    "/symbols": lambda q: symbols(q.get("pattern", [None])[0]),
    "/bars": lambda q: bars(
        q.get("symbol", [""])[0],
        q.get("timeframe", ["H1"])[0],
        int(q.get("count", ["500"])[0]),
    ),
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _reply(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's spelling
        parsed = urlparse(self.path)
        handler = ROUTES.get(parsed.path)
        if handler is None:
            self._reply(404, {"error": f"no route {parsed.path}"})
            return
        try:
            self._reply(200, handler(parse_qs(parsed.query)))
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            self._reply(
                500,
                {
                    "error": type(exc).__name__,
                    "detail": str(exc),
                    "traceback": traceback.format_exc(limit=3),
                },
            )

    def do_POST(self) -> None:  # noqa: N802
        # Every mutating path lands here, and there is currently no mutating
        # path. Refusing at the method rather than per-route means adding one
        # later cannot accidentally arrive unguarded.
        self._reply(
            403,
            {
                "error": "refused",
                "detail": (
                    "this bridge places no orders. Reading is how an edge gets "
                    "measured; sending is a separate decision with its own gate"
                ),
                "orders_enabled": ALLOW_ORDERS,
            },
        )

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write(f"{self.address_string()} {fmt % args}\n")


def main() -> None:
    print(f"mt5 bridge on http://{HOST}:{PORT}  orders_enabled={ALLOW_ORDERS}", flush=True)
    if mt5 is None:
        print("warning: MetaTrader5 is not importable here", flush=True)
    HTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
