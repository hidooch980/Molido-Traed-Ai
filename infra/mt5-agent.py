"""Apply broker logins that the API cannot apply itself.

The API runs in a container. MetaTrader runs on the host, under Wine, owned by
a different user, driven by systemd units the container cannot see. So the
container cannot write MetaTrader's config and cannot restart it, and giving it
the Docker socket or the host's systemd to fix that would hand a web-facing
process root on the machine.

Instead the container writes a request file into a shared directory and this
agent, which runs on the host as ubuntu, picks it up. The container needs no
privileges it did not already have, and the agent needs no network at all.

The password is deliberately not stored anywhere on this system. It arrives in
the request, goes into MetaTrader's own config - which is where MetaTrader
would put it regardless - and the request file is deleted. Keeping a second
copy in the application database would add an attack surface and a key to
manage in exchange for nothing: the terminal has to hold it either way.

    ./infra/mt5-agent.py --once     # process any pending request, then exit
    ./infra/mt5-agent.py            # watch, applying requests as they appear
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time
# timezone.utc rather than datetime.UTC: the host this runs on carries
# Python 3.10, and UTC-the-name arrived in 3.11. The agent crashed on
# import and systemd restarted it forever - 108 times before anybody
# read the journal.
from datetime import datetime, timezone

UTC = timezone.utc

#: Written by the API container, read here. A directory rather than a socket so
#: the permission model is the filesystem's, which both sides already agree on.
QUEUE = pathlib.Path(os.environ.get("MOLIDO_MT5_QUEUE", "/opt/molidotrade/var/mt5-queue"))
PREFIX = pathlib.Path(os.environ.get("WINEPREFIX", str(pathlib.Path.home() / ".mt5")))
#: Which systemd unit this agent restarts. Env-driven so one agent binary
#: serves any number of terminals, each instance pointed at its own prefix,
#: queue and unit.
UNIT = os.environ.get("MOLIDO_MT5_UNIT", "molido-mt5")

def _terminal_dir(prefix: pathlib.Path | None = None) -> pathlib.Path:
    """Whichever MetaTrader install this prefix actually runs.

    A prop firm's account lives on that firm's server, and a terminal only
    knows the servers its own installer shipped: the generic MetaQuotes build
    logged no authorization attempt at all against `FundedNext-Server3` - not
    a wrong password, not a network failure, a server name it had never heard
    of. So a prefix can hold the broker's build instead, under the broker's
    own directory name.

    This agent used to hardcode "MetaTrader 5". Against a prefix running a
    branded build it then wrote a valid, correctly permissioned startup file
    into a directory nothing reads, restarted the terminal, and reported that
    the login did not connect - which was true, and about a file the terminal
    never saw.

    A branded build wins when both exist, and that ordering is the whole
    point: a prefix acquires one only because somebody installed it there on
    purpose, while the generic build is simply what every prefix starts with
    and is left behind by the conversion. Preferring the generic would send
    the login back to the terminal that could not use it.
    """
    root = (prefix or PREFIX) / "drive_c/Program Files"
    generic = root / "MetaTrader 5"
    try:
        for candidate in sorted(root.iterdir()):
            if candidate == generic:
                continue
            if (candidate / "terminal64.exe").is_file():
                return candidate
    except OSError:
        pass
    return generic


_TERMINAL = _terminal_dir()


def _config_dir() -> pathlib.Path:
    """The terminal's own config directory, whichever case it was created with.

    The installer writes `Config`; this agent used to write `config`. On a
    Windows filesystem those are one directory; on the Linux filesystem the
    prefix actually lives on they are two, and the terminal reads its startup
    file out of the one this agent did not write to. The login then fails with
    no error anywhere - the config was valid, permissioned, and in a directory
    nothing reads.
    """
    for name in ("Config", "config"):
        candidate = _TERMINAL / name
        if candidate.is_dir():
            return candidate
    return _TERMINAL / "Config"


CONFIG = _config_dir() / "molido-startup.ini"


def log(message: str) -> None:
    print(f"{datetime.now(UTC).isoformat(timespec='seconds')} {message}", flush=True)


def write_config(login: str, server: str, password: str, config: pathlib.Path | None = None) -> None:
    """Rewrite MetaTrader's startup config with these credentials.

    UTF-16LE with a BOM, because that is what MetaTrader writes and what it can
    read back. A UTF-8 file is accepted, ignored, and produces a terminal that
    starts perfectly and logs into nothing - which reads as wrong credentials
    rather than an unread file.
    """
    body = (
        "[Common]\n"
        f"Login={login}\n"
        f"Password={password}\n"
        f"Server={server}\n"
        "KeepPrivate=1\n"
        "NewsEnable=0\n"
        "\n"
        "[Experts]\n"
        "AllowLiveTrading=1\n"
        "Enabled=1\n"
        "Account=0\n"
        "Profile=0\n"
        "\n"
        "[StartUp]\n"
        "Expert=MolidoBridge\n"
        "Symbol=EURUSD\n"
        "Period=H1\n"
        "ExpertParameters=\n"
    )
    config = config or CONFIG
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_bytes(b"\xff\xfe" + body.replace("\n", "\r\n").encode("utf-16-le"))
    # Readable by this user and nobody else. The terminal will hold the same
    # secret in its own files, but that is not a reason to publish it twice.
    config.chmod(0o600)


def restart_terminal(unit: str = UNIT) -> tuple[bool, str]:
    result = subprocess.run(
        ["sudo", "systemctl", "restart", unit],
        capture_output=True,
        text=True,
        timeout=120,
    )
    ok = result.returncode == 0
    return ok, (result.stderr or result.stdout).strip()



def _bridge_files() -> pathlib.Path:
    """Where the in-terminal bridge publishes what it can see.

    The Wine user directory is found by looking, not by reading `$USER`: under
    a systemd unit that variable is frequently unset, and the fallback then
    named a user this prefix has never had. The agent would watch a directory
    Wine never writes to and report every login as "restarted and did not
    connect" - about logins that had connected.
    """
    users = PREFIX / "drive_c/users"
    tail = "AppData/Roaming/MetaQuotes/Terminal/Common/Files"
    named = users / os.environ.get("USER", "") / tail
    if named.is_dir():
        return named
    for candidate in sorted(users.glob(f"*/{tail}")):
        # parents[5] is the Wine user the path hangs off:
        # Files < Common < Terminal < MetaQuotes < Roaming < AppData < user.
        if candidate.parents[5].name.lower() != "public":
            return candidate
    return named


#: Read rather than guessed: the terminal is the only thing that knows whether
#: a login worked.
BRIDGE_FILES = _bridge_files()


def wait_for_connection(timeout: float = 90.0, interval: float = 3.0, bridge: pathlib.Path | None = None) -> dict:
    """Watch the bridge until the terminal reports a live account, or give up.

    Ninety seconds covers a restart, a handshake and the first publish cycle.
    Past that, saying so is more useful than waiting longer: the failure is
    almost always a server name, and no amount of patience fixes one.
    """
    account_file = (bridge or BRIDGE_FILES) / "molido_account.json"
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        try:
            payload = json.loads(account_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            time.sleep(interval)
            continue

        # `login` is the honest signal. `connected` can be true against a cached
        # session with no account behind it, which is exactly the state this
        # deployment sat in for hours looking healthy.
        if payload.get("connected") and int(payload.get("login") or 0) > 0:
            return {
                "connected": True,
                "account_visible": True,
                "balance": payload.get("balance"),
                "currency": payload.get("currency"),
            }
        time.sleep(interval)

    return {"connected": False, "account_visible": False}


#: Where the terminal writes its own account of what happened. Read rather than
#: guessed: the first version of this agent reported "the usual cause is a
#: server name that does not exist" for every failure, and the first real test
#: had a correct server and a wrong password. A guess dressed as a diagnosis
#: sends somebody to check the one thing that was right.
TERMINAL_LOGS = PREFIX / "drive_c/Program Files/MetaTrader 5/logs"


class Target:
    """One terminal: its prefix, its unit, and the paths derived from them."""

    def __init__(self, key: str, prefix: pathlib.Path, unit: str) -> None:
        self.key = key
        self.prefix = prefix
        self.unit = unit
        # The install this prefix actually runs, which is not always the
        # generic one: a prop account needs its firm's own build, because a
        # terminal only knows the servers its installer shipped.
        terminal = _terminal_dir(prefix)
        cfg_dir = next(
            (terminal / n for n in ("Config", "config") if (terminal / n).is_dir()),
            terminal / "Config",
        )
        self.config = cfg_dir / "molido-startup.ini"
        self.logs = terminal / "logs"
        users = prefix / "drive_c/users"
        tail = "AppData/Roaming/MetaQuotes/Terminal/Common/Files"
        candidates = [
            c
            for c in sorted(users.glob(f"*/{tail}"))
            if c.parents[4].name.lower() != "public"
        ]
        self.bridge = (
            candidates[0]
            if candidates
            else users / os.environ.get("USER", "root") / tail
        )

    @property
    def taken(self) -> bool:
        return self.config.exists()


def targets() -> "list[Target]":
    """The terminals this agent serves, in preference order.

    `MOLIDO_MT5_TARGETS` is `key=prefix=unit,key=prefix=unit,...`. Unset means
    the single terminal this agent always had, under the key `main`.
    """
    spec = os.environ.get("MOLIDO_MT5_TARGETS", "").strip()
    if not spec:
        return [Target("main", PREFIX, UNIT)]
    out = []
    for part in spec.split(","):
        pieces = part.strip().split("=")
        if len(pieces) == 3 and all(pieces):
            out.append(Target(pieces[0], pathlib.Path(pieces[1]), pieces[2]))
    return out or [Target("main", PREFIX, UNIT)]


def resolve_target(requested: "str | None") -> "Target | None":
    """The terminal a request goes to.

    Named explicitly, the name has to exist - a login applied to a fallback
    terminal because of a typo would connect the right account in a place
    nobody is looking. Unnamed, the first terminal never given an account
    wins; when every one is taken, the *last* entry does, because the env
    var's order is a deliberate ranking and its tail is the deliberate
    overwrite choice.
    """
    known = targets()
    if requested:
        return next((x for x in known if x.key == requested), None)
    return next((x for x in known if not x.taken), known[-1])

#: What MetaTrader says, and what it means to somebody who has to fix it.
LOGIN_FAILURES = (
    ("invalid account", "the account number or password was not accepted by the broker"),
    ("account disabled", "the broker has disabled this account"),
    ("invalid password", "the password was not accepted"),
    ("no connection", "the terminal could not reach the broker's server"),
    ("authorization failed", "the broker refused the login"),
)


def terminal_verdict(login: str, logs_dir: pathlib.Path | None = None) -> str | None:
    """What the terminal logged about this login, in plain words.

    Returns None when it said nothing, which is itself an answer - a terminal
    that logged no authorization attempt did not reach the broker at all, and
    that is a different problem from being turned away by one.
    """
    try:
        logs = sorted((logs_dir or TERMINAL_LOGS).glob("*.log"), key=lambda p: p.stat().st_mtime)
    except OSError:
        return None
    if not logs:
        return None

    try:
        # The terminal writes UTF-16LE. Decoded wrongly this is a wall of NULs
        # and every match silently fails.
        text = logs[-1].read_bytes().decode("utf-16-le", errors="replace")
    except OSError:
        return None

    lines = [
        line.strip()
        for line in text.splitlines()
        if login in line and "authoriz" in line.lower()
    ]
    if not lines:
        return None

    last = lines[-1]
    lowered = last.lower()
    for needle, meaning in LOGIN_FAILURES:
        if needle in lowered:
            return meaning
    if "ok" in lowered or "success" in lowered:
        return None
    return last.split("	")[-1].strip()

def apply(request: pathlib.Path) -> dict:
    """Apply one request and return what happened.

    The password is read, used and never echoed. Every other field is safe to
    report, and the result file exists so the API can tell "applied" from
    "nobody was listening" - which are the two states a queue directory cannot
    otherwise distinguish.
    """
    payload = json.loads(request.read_text(encoding="utf-8"))
    login = str(payload.get("login", "")).strip()
    server = str(payload.get("server", "")).strip()
    password = str(payload.get("password", ""))
    action = str(payload.get("action", "login")).strip() or "login"
    requested = str(payload.get("terminal", "")).strip() or None

    target = resolve_target(requested)
    if target is None:
        known = ", ".join(x.key for x in targets())
        return {
            "applied": False,
            "terminal": requested,
            "reason": (
                f"no terminal is called {requested!r}. Known: {known}. A login "
                "applied to a fallback because of a typo would connect the "
                "right account where nobody is looking"
            ),
        }

    if action == "clear":
        # Log the terminal out by removing the startup config and restarting.
        # The saved session inside the prefix goes too, or the terminal would
        # quietly log back in with remembered credentials and report itself
        # cleared while trading the same account.
        target.config.unlink(missing_ok=True)
        for stale in target.bridge.glob("molido_*.json"):
            stale.unlink(missing_ok=True)
        restarted, detail = restart_terminal(target.unit)
        return {
            "applied": restarted,
            "cleared": restarted,
            "terminal": target.key,
            "reason": None if restarted else f"terminal restart failed: {detail}",
            "applied_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }

    if action != "login":
        return {
            "applied": False,
            "terminal": target.key,
            "reason": f"{action!r} is not an action this agent knows. "
            "Known: login, clear",
        }

    if not login or not server or not password:
        return {
            "applied": False,
            "terminal": target.key,
            "reason": "login, server and password are all required",
            "login": login or None,
            "server": server or None,
        }

    write_config(login, server, password, config=target.config)
    restarted, detail = restart_terminal(target.unit)
    connection = (
        wait_for_connection(bridge=target.bridge) if restarted else {"connected": False}
    )

    return {
        "applied": restarted,
        # Applied and connected are different facts. A wrong server name
        # applies perfectly and connects to nothing, and reporting the first as
        # though it were the second sends somebody looking for a bug in the
        # form. This is also the only way a mistyped server surfaces in
        # seconds rather than through a search of everything else.
        "connected": connection.get("connected", False),
        "account_visible": connection.get("account_visible", False),
        "reason": (
            None
            if restarted and connection.get("connected")
            else f"terminal restart failed: {detail}"
            if not restarted
            else (
                terminal_verdict(login, logs_dir=target.logs)
                or "the terminal restarted and did not connect, and logged no "
                "authorization attempt - which usually means the server name "
                "does not exist, so it never reached a broker to be refused by"
            )
        ),
        "login": login,
        "server": server,
        "config_written": str(target.config),
        "terminal": target.key,
        "applied_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def process_once() -> int:
    QUEUE.mkdir(parents=True, exist_ok=True)
    pending = sorted(QUEUE.glob("*.request.json"))
    for request in pending:
        log(f"applying {request.name}")
        try:
            result = apply(request)
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            result = {"applied": False, "reason": f"{type(exc).__name__}: {exc}"}
        # Written before the request is removed, so a crash between the two
        # leaves a request to retry rather than a silent loss.
        # Built from the request id rather than with_suffix: the file is named
        # `<id>.request.json`, and with_suffix replaces only the final `.json`,
        # producing `<id>.request.result.json` - which the API then looks for
        # under a different name and reports as "no such request".
        request_id = request.name.removesuffix(".request.json")
        result_path = request.parent / f"{request_id}.result.json"
        result_path.write_text(json.dumps(result, indent=1), encoding="utf-8")
        result_path.chmod(0o660)
        request.unlink(missing_ok=True)
        log(f"result: {result.get('applied')} {result.get('reason') or ''}")
    return len(pending)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="process and exit")
    parser.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args()

    if args.once:
        count = process_once()
        log(f"processed {count} request(s)")
        return

    log(f"watching {QUEUE}")
    while True:
        try:
            process_once()
        except Exception as exc:  # noqa: BLE001
            log(f"cycle failed: {type(exc).__name__}: {exc}")
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
