"""Self-healing and shadow learning for the agent analyzers (pure functions).

Detection: analyzer exceptions, non-finite outputs, stale runs, degraded accuracy.
Fixes, all inside the shadow agent layer only:
  * quarantine an analyzer after K consecutive errors, retry it after a cooldown
    ("restart"); its abstention never reaches anything that trades;
  * ensemble weights per agent, refit from resolved forward outcomes and applied
    only when a chronological hold-out says the candidate beats the current
    version; every version is logged and a version that underperforms the one it
    replaced in forward use is rolled back.
Nothing here is read by execution, the collector, or the production brains.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

ERRORS_TO_QUARANTINE = 3
COOLDOWN_RUNS = 4
MIN_TEST_CALLS = 30
MIN_IMPROVEMENT = 0.02
ROLLBACK_MARGIN = 0.05
ENSEMBLE_BAND = 0.2
W_MIN, W_MAX = 0.25, 2.0


@dataclass(frozen=True)
class Sample:
    """One resolved agent run: each agent's BUY/SELL call and the forward move."""

    as_of: datetime
    calls: dict[str, str]
    move: float


def finite_output(confidence: Any) -> bool:
    try:
        c = float(confidence)
    except (TypeError, ValueError):
        return False
    return math.isfinite(c) and 0.0 <= c <= 1.0


def quarantined(history: Sequence[dict[str, dict[str, Any]]], agent_ids: Sequence[str],
                *, k: int = ERRORS_TO_QUARANTINE, cooldown: int = COOLDOWN_RUNS) -> set[str]:
    """history: per-run health dicts, newest first. An agent is quarantined after k
    consecutive errors and released (retried) once it has been skipped `cooldown` runs."""
    out = set()
    for agent in agent_ids:
        rows: list[dict[str, Any]] = [h[agent] for h in history if h.get(agent) is not None]
        skipped = 0
        while skipped < len(rows) and rows[skipped].get("skipped"):
            skipped += 1
        errors = 0
        for row in rows[skipped:]:
            if row.get("skipped") or row.get("ok", True):
                break
            errors += 1
        if errors >= k and skipped < cooldown:
            out.add(agent)
    return out


def ensemble(calls: dict[str, str], weights: dict[str, float]) -> str:
    num = den = 0.0
    for agent, rec in calls.items():
        w = weights.get(agent, 1.0)
        num += w * (1 if rec == "BUY" else -1)
        den += w
    if den == 0 or abs(num / den) < ENSEMBLE_BAND:
        return "WAIT"
    return "BUY" if num > 0 else "SELL"


def hit_rate(samples: Sequence[Sample], weights: dict[str, float]) -> tuple[float | None, int]:
    hits = n = 0
    for s in samples:
        d = ensemble(s.calls, weights)
        if d == "WAIT" or s.move == 0:
            continue
        n += 1
        hits += 1 if (s.move > 0) == (d == "BUY") else 0
    return (hits / n if n else None), n


def fit(samples: Sequence[Sample], prior: float = 10.0) -> dict[str, float]:
    """Weight = shrunk per-agent hit rate relative to a coin flip, clamped."""
    hits: dict[str, int] = {}
    total: dict[str, int] = {}
    for s in samples:
        if s.move == 0:
            continue
        for agent, rec in s.calls.items():
            total[agent] = total.get(agent, 0) + 1
            hits[agent] = hits.get(agent, 0) + (1 if (s.move > 0) == (rec == "BUY") else 0)
    return {a: round(min(W_MAX, max(W_MIN, ((hits[a] + prior / 2) / (n + prior)) / 0.5)), 4)
            for a, n in total.items()}


def validate(samples: Sequence[Sample], current: dict[str, float]) -> dict[str, Any]:
    """Fit on the older 70%, compare on the newer 30%. Accept only a clear win."""
    ordered = sorted(samples, key=lambda s: s.as_of)
    cut = int(len(ordered) * 0.7)
    train, test = ordered[:cut], ordered[cut:]
    candidate = fit(train)
    cur_hit, cur_n = hit_rate(test, current)
    cand_hit, cand_n = hit_rate(test, candidate)
    accept = (cand_hit is not None and cand_n >= MIN_TEST_CALLS
              and (cur_hit is None or cand_hit >= cur_hit + MIN_IMPROVEMENT))
    return {"candidate": fit(ordered) if accept else candidate, "accept": accept,
            "current_hit": cur_hit, "current_n": cur_n, "candidate_hit": cand_hit,
            "candidate_n": cand_n, "train": len(train), "test": len(test)}


def should_roll_back(after: Sequence[Sample], applied: dict[str, float],
                     previous_hit: float | None) -> tuple[bool, float | None, int]:
    hit, n = hit_rate(after, applied)
    if previous_hit is None or hit is None or n < MIN_TEST_CALLS:
        return False, hit, n
    return hit < previous_hit - ROLLBACK_MARGIN, hit, n
