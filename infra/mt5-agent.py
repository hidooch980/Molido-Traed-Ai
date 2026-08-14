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
CONFIG = PREFIX / "drive_c/Program Files/MetaTrader 5/config/molido-startup.ini"
UNIT = "molido-mt5"


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
    return {
        "applied": restarted,
        "reason": None if restarted else f"terminal restart failed: {detail}",
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
        request.with_suffix(".result.json").write_text(
            json.dumps(result, indent=1), encoding="utf-8"
        )
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
