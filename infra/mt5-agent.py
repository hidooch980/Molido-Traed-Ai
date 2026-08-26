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
from datetime import UTC, datetime

#: Written by the API container, read here. A directory rather than a socket so
#: the permission model is the filesystem's, which both sides already agree on.
QUEUE = pathlib.Path(os.environ.get("MOLIDO_MT5_QUEUE", "/opt/molidotrade/var/mt5-queue"))
PREFIX = pathlib.Path(os.environ.get("WINEPREFIX", str(pathlib.Path.home() / ".mt5")))
UNIT = "molido-mt5"

_TERMINAL = PREFIX / "drive_c/Program Files/MetaTrader 5"


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


def write_config(login: str, server: str, password: str) -> None:
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
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_bytes(b"\xff\xfe" + body.replace("\n", "\r\n").encode("utf-16-le"))
    # Readable by this user and nobody else. The terminal will hold the same
    # secret in its own files, but that is not a reason to publish it twice.
    CONFIG.chmod(0o600)


def restart_terminal() -> tuple[bool, str]:
    result = subprocess.run(
        ["sudo", "systemctl", "restart", UNIT],
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


def wait_for_connection(timeout: float = 90.0, interval: float = 3.0) -> dict:
    """Watch the bridge until the terminal reports a live account, or give up.

    Ninety seconds covers a restart, a handshake and the first publish cycle.
    Past that, saying so is more useful than waiting longer: the failure is
    almost always a server name, and no amount of patience fixes one.
    """
    account_file = BRIDGE_FILES / "molido_account.json"
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

#: What MetaTrader says, and what it means to somebody who has to fix it.
LOGIN_FAILURES = (
    ("invalid account", "the account number or password was not accepted by the broker"),
    ("account disabled", "the broker has disabled this account"),
    ("invalid password", "the password was not accepted"),
    ("no connection", "the terminal could not reach the broker's server"),
    ("authorization failed", "the broker refused the login"),
)


def terminal_verdict(login: str) -> str | None:
    """What the terminal logged about this login, in plain words.

    Returns None when it said nothing, which is itself an answer - a terminal
    that logged no authorization attempt did not reach the broker at all, and
    that is a different problem from being turned away by one.
    """
    try:
        logs = sorted(TERMINAL_LOGS.glob("*.log"), key=lambda p: p.stat().st_mtime)
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

    if not login or not server or not password:
        return {
            "applied": False,
            "reason": "login, server and password are all required",
            "login": login or None,
            "server": server or None,
        }

    write_config(login, server, password)
    restarted, detail = restart_terminal()
    connection = wait_for_connection() if restarted else {"connected": False}

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
                terminal_verdict(login)
                or "the terminal restarted and did not connect, and logged no "
                "authorization attempt - which usually means the server name "
                "does not exist, so it never reached a broker to be refused by"
            )
        ),
        "login": login,
        "server": server,
        "config_written": str(CONFIG),
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
