"""Read what MetaTrader publishes, through the file bridge (spec §4, §26).

The terminal runs under Wine and its Python package cannot be imported from
Linux, so an expert inside the terminal writes account, symbols, positions and
closed bars to a shared folder every twenty seconds and this reads them. That
detour is not elegance; it is the only transport Wine carries reliably, and it
was chosen after the in-process one returned IPC timeout every way it was
called.

The important property of this provider is that it can tell three states apart,
and refuses to blur them:

  the bridge is not running       - no heartbeat, or one that has gone stale
  the bridge runs but has no data - heartbeat present, no account logged in
  the bridge has data             - an account, a login, and bars

The middle one is the state this deployment sat in for hours looking healthy:
the terminal was up, Market Watch showed prices, and every one of them was a
cached quote from a session that had ended. `connected: true` alone did not
catch it; a login of zero did.

Broker prices are not the same series as a public feed. Spreads differ, session
boundaries differ, and the same instrument has a different name at every
broker. Nothing here merges the two - MetaTrader bars arrive under their own
provider, so a comparison between them is a measurement rather than an
accident, and the conflict detector already knows what to do with a
disagreement.
"""

from __future__ import annotations

import csv
import json
import pathlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.enums import Timeframe
from app.core.errors import ProviderError
from app.providers.base import RawBar

#: The terminal writes here, this reads here. Overridable so a test can point
#: it somewhere harmless and so a second terminal can be added later.
DEFAULT_BRIDGE_DIR = pathlib.Path(
    "/home/ubuntu/.mt5/drive_c/users/ubuntu/AppData/Roaming/MetaQuotes/Terminal/Common/Files"
)

#: A heartbeat older than this means the expert stopped, whatever the other
#: files still say. Three publish cycles: one missed beat is a slow disk, three
#: is a stopped process.
STALE_AFTER = timedelta(seconds=90)

#: MetaTrader writes `2026.08.14 07:53:24` in the terminal's own timezone,
#: which this deployment runs as GMT+0. Parsed explicitly rather than by a
#: general parser: a format guessed right most of the time is a format that
#: silently shifts an hour somewhere.
STAMP_FORMAT = "%Y.%m.%d %H:%M:%S"


def _parse_stamp(value: str) -> datetime:
    return datetime.strptime(value.strip(), STAMP_FORMAT).replace(tzinfo=UTC)


@dataclass(frozen=True)
class BridgeState:
    """Whether the bridge is publishing, and whether anything is behind it."""

    running: bool
    connected: bool
    login: int
    published_at: datetime | None
    age_seconds: float | None
    reason: str | None

    @property
    def usable(self) -> bool:
        """Both halves. A terminal with no account publishes cached quotes from
        a session that ended, which reads as a working feed until somebody
        checks the login."""
        return self.running and self.connected and self.login > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "connected": self.connected,
            "login": self.login or None,
            "usable": self.usable,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "age_seconds": round(self.age_seconds, 1) if self.age_seconds is not None else None,
            "reason": self.reason,
            "note": (
                "a terminal with no account still publishes the last session's "
                "cached quotes. `connected` alone does not catch that; a login "
                "of zero does"
            ),
        }


class MetaTraderBridge:
    """Reads the files an expert inside the terminal writes."""

    name = "metatrader"

    def __init__(self, directory: pathlib.Path | str | None = None) -> None:
        self.directory = pathlib.Path(directory or DEFAULT_BRIDGE_DIR)

    # ---------------------------------------------------------------- state
    def state(self, *, now: datetime | None = None) -> BridgeState:
        moment = now or datetime.now(UTC)
        heartbeat = self.directory / "molido_heartbeat.json"

        if not heartbeat.exists():
            return BridgeState(
                running=False,
                connected=False,
                login=0,
                published_at=None,
                age_seconds=None,
                reason=(
                    "no heartbeat file - the expert is not attached, or the "
                    "terminal is not running"
                ),
            )

        try:
            beat = json.loads(heartbeat.read_text(encoding="utf-8"))
            published = _parse_stamp(beat["published_at"])
        except (OSError, ValueError, KeyError) as exc:
            return BridgeState(
                running=False,
                connected=False,
                login=0,
                published_at=None,
                age_seconds=None,
                reason=f"heartbeat unreadable: {exc}",
            )

        age = (moment - published).total_seconds()
        if age > STALE_AFTER.total_seconds():
            return BridgeState(
                running=False,
                connected=False,
                login=0,
                published_at=published,
                age_seconds=age,
                # Named as stale rather than absent, and with the cause rather
                # than only the symptom. An expert needs a chart, a chart needs
                # a symbol, and a symbol needs a logged-in account - so a
                # failed login stops the bridge entirely instead of leaving it
                # running with nothing behind it. "The expert stopped" alone
                # reads as a fault in the expert.
                reason=(
                    f"heartbeat is {age:.0f}s old. The usual cause is that no "
                    "account is logged in: an expert runs on a chart, a chart "
                    "needs a symbol, and a symbol needs a connected account - "
                    "so a failed login stops the bridge rather than leaving it "
                    "publishing empty data"
                ),
            )

        account = self._account_payload()
        login = int(account.get("login") or 0)
        connected = bool(account.get("connected"))

        return BridgeState(
            running=True,
            connected=connected,
            login=login,
            published_at=published,
            age_seconds=age,
            reason=(
                None
                if (connected and login > 0)
                else "the terminal is running but no account is logged in, so "
                "every price it shows is cached from a session that ended"
            ),
        )

    def _account_payload(self) -> dict[str, Any]:
        path = self.directory / "molido_account.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    # -------------------------------------------------------------- account
    def account(self, *, now: datetime | None = None) -> dict[str, Any]:
        """The account as the broker's server sees it, or why it is unavailable.

        Balance and equity are both reported. The difference between them is
        the open book, and a challenge is failed on equity - publishing only
        balance would hide the drawdown that ends the account.
        """
        state = self.state(now=now)
        if not state.usable:
            return {"available": False, "reason": state.reason, "state": state.as_dict()}

        payload = self._account_payload()
        return {
            "available": True,
            "login": int(payload.get("login") or 0),
            "server": payload.get("server") or None,
            "company": payload.get("company") or None,
            "currency": payload.get("currency") or None,
            "balance": float(payload.get("balance") or 0.0),
            "equity": float(payload.get("equity") or 0.0),
            "margin": float(payload.get("margin") or 0.0),
            "free_margin": float(payload.get("free_margin") or 0.0),
            "leverage": int(payload.get("leverage") or 0),
            "trade_allowed": bool(payload.get("trade_allowed")),
            "state": state.as_dict(),
        }

    # -------------------------------------------------------------- symbols
    def symbols(self, *, now: datetime | None = None) -> dict[str, Any]:
        """Broker symbol specifications.

        Contract size and tick value are the two numbers that turn a risk in R
        into a position size. Taking them from the broker rather than the
        textbook is the difference between a 1% risk and a 10% one on anything
        that is not a standard lot - and a tick value of zero means the broker
        has not supplied it, which is refused rather than defaulted.
        """
        state = self.state(now=now)
        if not state.usable:
            return {"available": False, "reason": state.reason, "symbols": []}

        path = self.directory / "molido_symbols.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return {"available": False, "reason": f"unreadable: {exc}", "symbols": []}

        symbols = []
        for entry in payload.get("symbols", []):
            tick_value = float(entry.get("tick_value") or 0.0)
            symbols.append(
                {
                    "name": entry.get("name"),
                    "description": entry.get("description") or "",
                    "digits": int(entry.get("digits") or 0),
                    "contract_size": float(entry.get("contract_size") or 0.0),
                    "tick_size": float(entry.get("tick_size") or 0.0),
                    "tick_value": tick_value or None,
                    "volume_min": float(entry.get("volume_min") or 0.0),
                    "volume_step": float(entry.get("volume_step") or 0.0),
                    "bid": float(entry.get("bid") or 0.0),
                    "ask": float(entry.get("ask") or 0.0),
                    # Stated rather than silently zeroed. Sizing without it is
                    # the mistake this field exists to prevent.
                    "sizable": tick_value > 0,
                }
            )
        return {"available": True, "count": len(symbols), "symbols": symbols}

    # ------------------------------------------------------------ positions
    def positions(self, *, now: datetime | None = None) -> dict[str, Any]:
        state = self.state(now=now)
        if not state.usable:
            return {"available": False, "reason": state.reason, "positions": []}

        path = self.directory / "molido_positions.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return {"available": False, "reason": f"unreadable: {exc}", "positions": []}
        return {"available": True, "positions": payload.get("positions", [])}

    # ----------------------------------------------------------------- bars
    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime | None = None,
        end: datetime | None = None,
        *,
        now: datetime | None = None,
    ) -> list[RawBar]:
        """Closed bars for one symbol, oldest first.

        The expert already drops the forming bar, so everything here has
        settled. `start` and `end` filter what was published rather than
        requesting a range: this is a file the terminal wrote, not a query, and
        pretending otherwise would invite a caller to ask for history the
        bridge never had.
        """
        state = self.state(now=now)
        if not state.usable:
            raise ProviderError(state.reason or "the MetaTrader bridge has no data")

        path = self.directory / f"molido_bars_{symbol}_{timeframe.value}.csv"
        if not path.exists():
            raise ProviderError(
                f"the bridge publishes no {timeframe.value} bars for {symbol}. "
                "Only what is in the terminal's Market Watch is written"
            )

        bars: list[RawBar] = []
        try:
            with path.open(newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    stamp = _parse_stamp(row["event_time"])
                    if start and stamp < start:
                        continue
                    if end and stamp > end:
                        continue
                    bars.append(
                        RawBar(
                            event_time=stamp,
                            open=float(row["open"]),
                            high=float(row["high"]),
                            low=float(row["low"]),
                            close=float(row["close"]),
                            volume=float(row["volume"]),
                        )
                    )
        except (OSError, ValueError, KeyError) as exc:
            raise ProviderError(f"unreadable bar file for {symbol}: {exc}") from exc

        bars.sort(key=lambda bar: bar.event_time)
        return bars

    def list_symbols(self, *, now: datetime | None = None) -> list[str]:
        published = self.symbols(now=now)
        return [s["name"] for s in published.get("symbols", []) if s.get("name")]
