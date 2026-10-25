"""Read-only intraday evidence, never an account pass or an income forecast."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from app.models.journal import ARM_CONTROL, ARM_RULE, JournalEntry

TIMEFRAMES = ("M1", "M5", "M10", "M15", "M30")
MAX_ROWS = 50_000


def build_report(
    session: Session, *, days: int = 14, now: datetime | None = None
) -> dict[str, Any]:
    if not 1 <= days <= 90:
        raise ValueError("review window must be between 1 and 90 days")
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        raise ValueError("review timestamp must include a timezone")
    moment = moment.astimezone(UTC)
    since = moment - timedelta(days=days)
    statement = (
        select(JournalEntry)
        .options(load_only(
            JournalEntry.strategy, JournalEntry.price_source, JournalEntry.timeframe,
            JournalEntry.symbol, JournalEntry.opened_at, JournalEntry.arm,
            JournalEntry.outcome, JournalEntry.r_multiple, JournalEntry.after,
        ))
        .where(JournalEntry.opened_at >= since, JournalEntry.opened_at <= moment,
               JournalEntry.timeframe.in_(TIMEFRAMES))
        .order_by(JournalEntry.opened_at.desc(), JournalEntry.id)
        .limit(MAX_ROWS + 1)
    )
    rows = list(session.scalars(statement))
    truncated = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    pairs: dict[tuple, dict[str, float]] = defaultdict(dict)
    excluded = 0
    invalid = 0
    first_observed: datetime | None = None
    for row in rows:
        if row.outcome == "excluded" or (
            isinstance(row.after, dict) and "retracted" in row.after
        ):
            excluded += 1
            continue
        if row.arm not in (ARM_RULE, ARM_CONTROL):
            continue
        opened = row.opened_at
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=UTC)  # database timestamps are UTC
        first_observed = min(first_observed, opened) if first_observed else opened
        key = (row.timeframe, row.strategy, row.price_source)
        group = groups.setdefault(key, {"signals": 0, "resolved": 0, "gross": [],
                                        "unresolved": 0, "instants": set()})
        if row.arm == ARM_RULE:
            group["signals"] += 1
            group["instants"].add(opened)
        value = row.r_multiple
        if value is not None and not math.isfinite(float(value)):
            invalid += 1
            continue
        if row.arm == ARM_RULE:
            if value is None:
                group["unresolved"] += 1
            else:
                group["resolved"] += 1
                group["gross"].append(float(value))
        if value is not None:
            pairs[(*key, opened, row.symbol)][row.arm] = float(value)

    clustered: dict[tuple, dict[datetime, list[float]]] = defaultdict(lambda: defaultdict(list))
    for (timeframe, strategy, source, opened, _symbol), arms in pairs.items():
        if ARM_RULE in arms and ARM_CONTROL in arms:
            clustered[(timeframe, strategy, source)][opened].append(
                arms[ARM_RULE] - arms[ARM_CONTROL]
            )
    periods: list[dict[str, Any]] = []
    for timeframe in TIMEFRAMES:
        measurements = []
        for key, group in sorted(groups.items()):
            if key[0] != timeframe:
                continue
            instants = clustered.get(key, {})
            differences = [sum(v) / len(v) for v in instants.values()]
            gross = group["gross"]
            measurements.append({
                "strategy": key[1], "price_source": key[2],
                "signal_rows": group["signals"], "decision_instants": len(group["instants"]),
                "resolved_signal_rows": group["resolved"],
                "unresolved_signal_rows": group["unresolved"],
                "gross_signal_mean_r": sum(gross) / len(gross) if gross else None,
                "paired_instants": len(differences),
                "mean_difference_from_control_r": (
                    sum(differences) / len(differences) if differences else None
                ),
            })
        periods.append({"timeframe": timeframe, "available": bool(measurements),
                        "groups": measurements})
    return {
        "window": {"from": since.isoformat(), "to": moment.isoformat(), "days": days,
                   "first_observed": first_observed.isoformat() if first_observed else None},
        "scope": "fleet signal journal; not attributed to an FTMO account",
        "rows_read": len(rows), "truncated": truncated,
        "excluded_rows": excluded, "invalid_results": invalid,
        "timeframes": periods,
        "reference_plan": {
            "program": "FTMO 2-Step Free Trial", "plan_only": True,
            "planned_initial_balance_usd": 10_000,
            "profit_target_pct": 0.05, "minimum_trading_days": 2,
            "calendar_duration_days": 14, "review_day": 15,
            "source": "https://ftmo.com/en/ftmo-free-trial/", "verified_on": "2026-10-25",
            "note": "This reference does not identify or reconfigure the connected account.",
        },
        "broker_net_profit": None, "actual_payouts": None,
        "income_assessment": "not_assessed", "live_promotion_authorized": False,
        "limitations": [
            "Signal R is not realized broker profit, fees or a payout.",
            "A rolling journal window is not the broker's trial expiry.",
            "Simultaneous decisions are clustered; overlapping windows can remain dependent.",
            "Compare strategies, feeds and timeframes separately; no winner is auto-selected.",
            "A short trial cannot establish sustainable monthly income.",
            "A truncated report is incomplete and cannot support a readiness decision.",
        ],
    }
