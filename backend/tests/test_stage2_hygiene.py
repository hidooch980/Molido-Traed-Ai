"""Stage 2: the expert refuses real money itself, and docs carry no infra ids."""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
EXPERT = (REPO / "infra" / "mql5" / "MolidoBridge.mq5").read_text(encoding="utf-8")


def test_real_account_switch_defaults_off():
    assert re.search(r"input bool\s+AllowRealAccount\s*=\s*false;", EXPERT)


def test_guard_reads_the_terminal_trade_mode():
    body = EXPERT[EXPERT.index("bool RealAccountRefused(string id)") :]
    body = body[: body.index("\n  }")]
    assert "ACCOUNT_TRADE_MODE_REAL" in body
    assert "AccountInfoInteger(ACCOUNT_TRADE_MODE)" in body


def test_every_trade_request_path_checks_the_guard():
    """Open, close and amend each pass AllowTrading, then the real guard."""
    assert EXPERT.count('"AllowTrading is off on the expert"') == 3
    assert EXPERT.count("if(RealAccountRefused(id))") == 3


def test_docs_carry_no_production_ip_or_mt5_login():
    pattern = re.compile(
        r"178\.33\.150\.51|185\.204\.169\.240|\b6720948[0-9]\b|\b6720947[0-9]\b"
        r"|\b1514533027\b|\b34911052\b"
    )
    offenders = [
        str(p.relative_to(REPO))
        for p in [*(REPO / "docs").rglob("*"), REPO / "README.md"]
        if p.is_file() and pattern.search(p.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert offenders == []
