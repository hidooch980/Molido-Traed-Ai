"""FTMO / prop-firm monitor: recorded challenge accounts checked against live bridge data.

Read-only. Uses the existing rulebooks and `app/brain/challenge.check`; the live
side comes from `agent_account` (MT5 file bridge). A challenge account is paired
with the bridge account whose key equals its label, or - when exactly one of
each exists - with that one. Anything unknown is reported as unknown, never 0.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.brain import challenge as challenge_brain
from app.brain import rulebooks
from app.providers.metatrader import bridge_dirs
from app.services import agent_account, challenge_accounts


def _pair(label: str, keys: list[str], n_accounts: int) -> str | None:
    if label in keys:
        return label
    if n_accounts == 1 and len(keys) == 1:
        return keys[0]
    return None


def monitor(session: Session, *, now: datetime | None = None,
            snapshots: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    views = challenge_accounts.listing(session,
                                       tenant_id=challenge_accounts.default_tenant(session))
    active = [v for v in views if v.account.is_active]
    keys = sorted(snapshots) if snapshots is not None else sorted(bridge_dirs(session=session))
    rows: list[dict[str, Any]] = []
    for view in active:
        base = view.as_dict()
        key = _pair(view.account.label, keys, len(active))
        row: dict[str, Any] = {"account": base, "bridge_account_key": key}
        if key is None:
            rows.append({**row, "status": "not_linked",
                         "reason": "no bridge account key matches this label"})
            continue
        snap = (snapshots or {}).get(key) or agent_account.snapshot(key, session=session,
                                                                    now=now)
        book = rulebooks.get(view.account.rulebook_key) if view.account.rulebook_key else None
        if not snap.get("available"):
            rows.append({**row, "status": "no_live_data", "reason": snap.get("reason")})
            continue
        if book is None:
            rows.append({**row, "status": "no_rulebook", "live": snap,
                         "reason": "no rulebook resolved for this account"})
            continue
        equity, daily = float(snap["equity"]), snap.get("daily_pnl_pct")
        if daily is None:
            rows.append({**row, "status": "unknown_daily", "live": snap,
                         "reason": "today's P&L cannot be read, so the daily limit cannot "
                                   "be checked"})
            continue
        start = float(view.account.starting_balance)
        state = challenge_brain.ChallengeState(
            starting_balance=start,
            current_equity=equity,
            peak_equity=max(start, equity),
            daily_starting_equity=equity / (1 + daily / 100),
            days_traded=int(snap.get("days_traded") or 0),
            open_positions=len(snap.get("open_symbols") or []),
            current_date=now.date(),
            current_balance=float(snap["balance"]),
            rules_confirmed_by_holder=bool(view.account.rules_confirmed),
            currency_per_r=float(view.account.currency_per_r)
            if view.account.currency_per_r is not None else None,
        )
        verdict = challenge_brain.check(book.rules, state).as_dict()
        rows.append({**row, "status": "monitored", "live": snap, "verdict": verdict,
                     "peak_equity_basis": "max(starting balance, current equity): the bridge "
                                          "does not publish an equity history"})
    return {
        "as_of": now.isoformat(),
        "mode": "read_only",
        "bridge_accounts": keys,
        "accounts": rows,
        "note": "Monitoring only. Rules are the recorded rulebook; confirm them against your "
                "own contract. Nothing here opens, closes or blocks a trade.",
    }
