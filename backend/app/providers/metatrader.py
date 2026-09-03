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
import os
import pathlib
import re
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

#: One bridge directory per account, read from the environment as
#: `MOLIDO_MT5_BRIDGE_DIRS="main=/path/one,challenge=/path/two"`. Unset means
#: the single terminal this deployment has always had, under the key `main`.
#:
#: Each terminal owns exactly one account and writes to its own directory. The
#: files carry no account identity - `molido_positions.json` is just positions -
#: so the directory *is* the account, and picking the wrong one sends an order
#: to the wrong money.
BRIDGE_DIRS_VAR = "MOLIDO_MT5_BRIDGE_DIRS"

DEFAULT_ACCOUNT_KEY = "main"


def bridge_dirs(
    raw: str | None = None, session: Any | None = None
) -> dict[str, pathlib.Path]:
    """Parse the account-to-directory map, or return the single default.

    Malformed entries raise rather than being skipped. A silently dropped
    account reads downstream as "that terminal is not publishing", which is a
    real and different condition this codebase already reports honestly - and
    it would be reported about an account that is running fine.

    **Registered terminals are merged in when a session is given.** The
    environment variable is the right shape for the one terminal this platform
    was built around and the wrong shape for eleven: every account meant an
    edit, a rebuild, and somebody with a shell. Terminals registered through
    the interface resolve to a directory derived from their key.

    The environment wins on a collision, and deliberately: it is the one an
    operator set by hand on the machine, and a row in a table quietly
    overriding it would move a terminal's directory without anyone touching
    the configuration they believe is in force.
    """
    registered: dict[str, pathlib.Path] = {}
    if session is not None:
        from app.services import terminals as terminal_service

        registered = terminal_service.registered_dirs(session)

    if raw is None:
        raw = os.environ.get(BRIDGE_DIRS_VAR) or ""
    raw = raw.strip()
    if not raw:
        # The built-in default only when nothing else is known. A deployment
        # with registered terminals and no environment variable should not
        # also carry a phantom `main` pointing at a directory nobody writes.
        return registered or {DEFAULT_ACCOUNT_KEY: DEFAULT_BRIDGE_DIR}

    found: dict[str, pathlib.Path] = {}
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        key, sep, where = chunk.partition("=")
        key, where = key.strip(), where.strip()
        if not sep or not key or not where:
            raise ProviderError(
                f"{BRIDGE_DIRS_VAR} entry {chunk!r} is not `key=/path`. "
                "Refusing to guess which account it meant"
            )
        if key in found:
            raise ProviderError(
                f"{BRIDGE_DIRS_VAR} names {key!r} twice. One account cannot "
                "have two terminals, and the later one would silently win"
            )
        found[key] = pathlib.Path(where)

    if not found:
        return registered or {DEFAULT_ACCOUNT_KEY: DEFAULT_BRIDGE_DIR}
    return {**registered, **found}


def bridge_dir_for(account_key: str | None = None, raw: str | None = None) -> pathlib.Path:
    """The directory for one account. Raises on an account it does not know.

    **Never falls back.** A default here would route one account's orders to
    another account's terminal, and every file involved would look correct
    while it happened. An exception stops a wrong trade; a fallback places one.
    """
    known = bridge_dirs(raw)
    if account_key is None:
        if len(known) == 1:
            return next(iter(known.values()))
        raise ProviderError(
            f"{len(known)} accounts are configured, so an account key is "
            "required. Guessing which terminal to use would guess whose money"
        )
    try:
        return known[account_key]
    except KeyError:
        raise ProviderError(
            f"no bridge directory is configured for account {account_key!r}. "
            f"Known: {', '.join(sorted(known)) or '(none)'}. Refusing to fall "
            "back to another account's terminal"
        ) from None


#: Where the terminal writes its own log. Mounted read-only, and read only to
#: answer one question: when a login fails, MetaTrader already knows exactly
#: why, and guessing at the cause instead of reading it produced two wrong
#: diagnoses in a row here - "the expert stopped" (it had not) and "a failed
#: login stops the bridge" (it does not; it publishes with no account).
DEFAULT_LOG_DIR = pathlib.Path("/home/ubuntu/.mt5/drive_c/Program Files/MetaTrader 5/logs")

#: A heartbeat older than this means the expert stopped, whatever the other
#: files still say. Three publish cycles: one missed beat is a slow disk, three
#: is a stopped process.
STALE_AFTER = timedelta(seconds=90)

#: `CD	2	09:25:03.172	Network	'111099517': authorization on MetaQuotes-Demo
#: failed (Invalid account)`. The parenthesised part is the useful half: an
#: invalid account and a wrong password need completely different actions, and
#: "login failed" covers both while helping with neither.
_AUTH_LINE = re.compile(
    r"(?P<time>\d{2}:\d{2}:\d{2})\.\d+\s+Network\s+"
    r"'(?P<login>\d+)':\s*(?P<detail>.*?authoriz\w*\s+on\s+\S+.*)$"
)

#: MetaTrader's account types, as the terminal reports them.
#:
#: Read rather than inferred from the server name: "RoboForex-Pro" is a demo
#: server and "…-Demo" is not a naming rule any broker is obliged to follow.
#: Guessing from the name is how a funded account gets treated as practice.
TRADE_MODE_DEMO = 0
TRADE_MODE_CONTEST = 1
TRADE_MODE_REAL = 2

TRADE_MODE_NAMES = {
    TRADE_MODE_DEMO: "demo",
    TRADE_MODE_CONTEST: "contest",
    TRADE_MODE_REAL: "real money",
}

#: MetaTrader writes `2026.08.14 07:53:24` in the terminal's own timezone,
#: which this deployment runs as GMT+0. Parsed explicitly rather than by a
#: general parser: a format guessed right most of the time is a format that
#: silently shifts an hour somewhere.
STAMP_FORMAT = "%Y.%m.%d %H:%M:%S"


def _trade_mode(payload: dict[str, Any]) -> int:
    """Demo, contest or real, from the terminal.

    An absent field returns REAL, not DEMO. If the bridge cannot say what kind
    of account this is, the safe assumption is the one that refuses to trade -
    treating an unknown account as practice is the mistake that costs money,
    and treating a practice account as real costs a confirmation click.
    """
    raw = payload.get("trade_mode")
    if raw is None:
        return TRADE_MODE_REAL
    try:
        return int(raw)
    except (TypeError, ValueError):
        return TRADE_MODE_REAL


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


def _with_authorization(reason: str, authorization: str | None) -> str:
    """Append what the terminal said, when it said anything.

    Kept separate so the two callers cannot drift apart, and so the absence of
    a log line changes nothing about the message that was already true.
    """
    return f"{reason}. {authorization}" if authorization else reason


class MetaTraderBridge:
    """Reads the files an expert inside the terminal writes."""

    name = "metatrader"

    def __init__(
        self,
        directory: pathlib.Path | str | None = None,
        *,
        log_directory: pathlib.Path | str | None = None,
    ) -> None:
        self.directory = pathlib.Path(directory or DEFAULT_BRIDGE_DIR)
        self.log_directory = pathlib.Path(log_directory or DEFAULT_LOG_DIR)

    # ------------------------------------------------------------ the reason
    def last_authorization(self) -> str | None:
        """What MetaTrader itself said about the most recent login attempt.

        Read rather than inferred. The terminal writes the exact refusal -
        `(Invalid account)` is a login that does not exist and no password will
        fix, `(Invalid password)` is one that does - and those need opposite
        actions from whoever is reading the screen.

        Returns None when there is nothing to report: no log directory, no log,
        or no authorization line in it. None means "MetaTrader has not said",
        never "everything is fine".
        """
        try:
            # Dated logs only. The directory also holds `metaeditor.log`, which
            # sorts last alphabetically and contains no login lines at all -
            # picking it produced a correct-looking None on a server whose
            # terminal had written the failure two files earlier.
            logs = sorted(
                path
                for path in self.log_directory.glob("*.log")
                if path.stem.isdigit() and len(path.stem) == 8
            )
        except OSError:
            return None
        if not logs:
            return None

        try:
            # UTF-16LE with a BOM, and errors are replaced rather than raised:
            # one unreadable byte in a log must not cost the diagnosis.
            text = logs[-1].read_text(encoding="utf-16", errors="replace")
        except (OSError, ValueError, UnicodeError):
            return None

        found: str | None = None
        for line in text.splitlines():
            match = _AUTH_LINE.search(line)
            if match:
                # The last one wins: an earlier failure followed by a success
                # must not be reported as the current state.
                found = (
                    f"MetaTrader at {match['time']} for account "
                    f"{match['login']}: {match['detail'].strip()}"
                )
        return found

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
                # Named as stale rather than absent, and followed by what the
                # terminal itself said rather than a guess at why. Two guesses
                # were wrong here before this line read the log.
                reason=_with_authorization(
                    f"heartbeat is {age:.0f}s old - the expert has stopped "
                    "publishing, or is publishing far slower than its timer",
                    self.last_authorization(),
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
                else _with_authorization(
                    "the terminal is running but no account is logged in, so "
                    "every price it shows is cached from a session that ended",
                    self.last_authorization(),
                )
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
            # MetaTrader's own answer: 0 demo, 1 contest, 2 real. The expert has
            # published it since the bridge was built and nothing read it, which
            # meant one deployment-wide switch would have sent live orders to a
            # funded account the same way it sends them to a practice one.
            "trade_mode": _trade_mode(payload),
            "is_real_money": _trade_mode(payload) == TRADE_MODE_REAL,
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

    def deals(self, *, now: datetime | None = None) -> dict[str, Any]:
        """Closed trades, as the terminal recorded them.

        The one place a result is final. Everything else on this bridge is a
        position that may still move; a deal has settled, carries its swap and
        commission, and is what the account was actually paid - which is why
        the gold loss read here to the cent while the floating figure was
        still an opinion.
        """
        state = self.state(now=now)
        if not state.usable:
            return {"available": False, "reason": state.reason, "deals": []}

        path = self.directory / "molido_deals.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            # A terminal that has closed nothing yet has no file, and that is
            # not an error - but it is also not a deal, so it reads as empty
            # with the reason kept.
            return {"available": False, "reason": f"unreadable: {exc}", "deals": []}
        return {"available": True, "deals": payload.get("deals", [])}

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


def tradeable_symbols(directories: dict[str, pathlib.Path] | None = None) -> frozenset[str]:
    """Every symbol at least one terminal can actually price and size.

    The fleet decides on whatever has bars in the database, and the database
    is filled from a free data provider that carries instruments this broker
    does not offer: crypto, metal futures, and a dozen thin currencies. A
    brain takes two picks a side, so a cycle where both of one brain's shorts
    are BTCUSD and GCFUT is a brain that contributed nothing - its opinion is
    thrown away at the order gate with "the terminal publishes no contract
    specification", after it has already spent its picks.

    That is the failure this closes. It is not a loosened gate: the same
    rules run, on instruments that exist at the broker rather than on ones
    that cannot be bought at any size.

    A symbol counts as tradeable when some terminal publishes a usable tick
    value and tick size for it. One terminal is enough - accounts differ in
    what they may trade, and that is the account's own filter to apply, not
    this one's.
    """
    found: set[str] = set()
    for path in (directories or bridge_dirs()).values():
        published = MetaTraderBridge(directory=path).symbols()
        for row in published.get("symbols") or []:
            name = str(row.get("name") or "")
            try:
                tick_value = float(row.get("tick_value") or 0.0)
                tick_size = float(row.get("tick_size") or 0.0)
            except (TypeError, ValueError):
                continue
            if name and tick_value > 0 and tick_size > 0:
                found.add(name)
    return frozenset(found)
