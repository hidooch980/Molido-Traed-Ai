"""Performance-weighted agent votes, regime gates, and underperformer flags.

Shadow/advisory only. A weighted vote is a confirmation signal, never an
approval, and a Risk Brain or control BLOCK always withholds a directional
vote. Missing or thin data is WAIT, never a guessed BUY or SELL.

Weights come from a decaying rolling hit rate. An agent with fewer than
`MIN_SAMPLES` decaying observations keeps a neutral weight of 1.0 rather than
being rewarded or punished on noise. Weights are clamped to [W_MIN, W_MAX].

The monthly underperformer report only *proposes* disable or retrain. It never
deletes a role, never quarantines, and never changes weights by itself.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.agents.analyzers.bars import Candle, atr
from app.agents.analyzers.extra import _trend
from app.agents.selfheal import Sample

MIN_SAMPLES = 20
W_MIN, W_MAX = 0.25, 2.0
HALF_LIFE_DAYS = 14.0
ENSEMBLE_BAND = 0.2
UNDERPERFORM_HIT = 0.45
DISABLE_HIT = 0.40
MONTH = timedelta(days=30)

REGIMES = ("trend", "range", "volatile", "unknown")

# Directional roles allowed to vote in each known regime. When the regime is
# unknown, every directional recommendation is counted. Control roles (RK/EX)
# are never used as a BUY/SELL vote; a BLOCK from them withholds the result.
TREND_VOTERS = frozenset({
    "SC01", "SC03", "SC07", "SC09",
    "TA01", "TA02", "TA04", "TA06",
    "AI01", "AI02",
    "RT01", "RT02", "RT03", "RT08", "RT09", "RT10",
})
RANGE_VOTERS = frozenset({
    "SC04", "SC08", "SC10",
    "TA03", "TA05",
    "SM01", "SM02", "SM03", "SM04", "SM05", "SM06", "SM07", "SM08", "SM09", "SM10",
    "AI01",
})
VOLATILE_VOTERS = frozenset({
    "SC02", "SC05", "SC06",
    "RT01", "RT04", "RT05", "RT06", "RT07",
    "AI01", "AI04",
})
CONTROL_BLOCKERS = frozenset({
    "RK01", "RK03", "RK04", "RK05", "EX02", "EX05",
})
VOTERS_FOR = {"trend": TREND_VOTERS, "range": RANGE_VOTERS, "volatile": VOLATILE_VOTERS}


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def detect_regime(bars: Sequence[Candle]) -> dict[str, Any]:
    """trend / range / volatile / unknown from closed bars only."""
    visible = list(bars)
    if len(visible) < 40:
        return {"regime": "unknown", "reason": "fewer than 40 closed bars", "atr": None}
    a = atr(visible, 14)
    ranges = [b.high - b.low for b in visible[-40:]]
    if a is None or not ranges:
        return {"regime": "unknown", "reason": "ATR undefined", "atr": None}
    mid = sorted(ranges)[len(ranges) // 2]
    trend = _trend(visible)
    ev = {"atr": round(a, 8), "median_range": round(mid, 8), "trend": trend}
    if mid <= 0:
        return {"regime": "unknown", "reason": "median range is zero", **ev}
    if a > 1.3 * mid and trend in (1, -1):
        return {"regime": "trend", "reason": "expanded range with a directional EMA trend", **ev}
    if a > 1.3 * mid:
        return {"regime": "volatile", "reason": "expanded range without a clear trend", **ev}
    if a < 0.7 * mid:
        return {"regime": "range", "reason": "compressed range", **ev}
    return {"regime": "unknown", "reason": "regime mixed or transitional", **ev}


def decay_weight(as_of: datetime, now: datetime, *, half_life: float = HALF_LIFE_DAYS) -> float:
    if half_life <= 0:
        return 1.0
    age = (_aware(now) - _aware(as_of)).total_seconds() / 86400.0
    if age <= 0:
        return 1.0
    return 0.5 ** (age / half_life)


def rolling_weights(
    samples: Sequence[Sample],
    *,
    now: datetime | None = None,
    half_life: float = HALF_LIFE_DAYS,
    min_samples: int = MIN_SAMPLES,
    w_min: float = W_MIN,
    w_max: float = W_MAX,
) -> dict[str, float]:
    """Per-agent weight from decaying hit rate. Thin history stays neutral (1.0)."""
    now = now or datetime.now(UTC)
    hits: dict[str, float] = {}
    total: dict[str, float] = {}
    counts: dict[str, int] = {}
    for sample in samples:
        if sample.move == 0:
            continue
        dw = decay_weight(sample.as_of, now, half_life=half_life)
        if dw <= 0:
            continue
        for agent, rec in sample.calls.items():
            if rec not in ("BUY", "SELL"):
                continue
            total[agent] = total.get(agent, 0.0) + dw
            counts[agent] = counts.get(agent, 0) + 1
            won = (sample.move > 0) == (rec == "BUY")
            hits[agent] = hits.get(agent, 0.0) + (dw if won else 0.0)
    out: dict[str, float] = {}
    for agent, n in total.items():
        if counts[agent] < min_samples or n <= 0:
            out[agent] = 1.0
            continue
        rate = hits.get(agent, 0.0) / n
        out[agent] = round(min(w_max, max(w_min, rate / 0.5)), 4)
    return out


@dataclass(frozen=True)
class Vote:
    recommendation: str
    score: float
    regime: str
    n_buy: int = 0
    n_sell: int = 0
    n_held: int = 0
    withheld: bool = False
    reason: str = ""
    used_weights: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "recommendation": self.recommendation,
            "score": round(self.score, 4),
            "regime": self.regime,
            "n_buy": self.n_buy,
            "n_sell": self.n_sell,
            "n_held": self.n_held,
            "withheld": self.withheld,
            "reason": self.reason,
            "used_weights": {k: round(v, 4) for k, v in self.used_weights.items()},
            "note": "advisory confirmation only; Risk Brain remains the authority",
        }


def _eligible(agent_id: str, regime: str) -> bool:
    allowed = VOTERS_FOR.get(regime)
    if allowed is None:
        return True
    return agent_id in allowed


def vote(
    calls: dict[str, str],
    weights: dict[str, float],
    *,
    regime: str = "unknown",
) -> Vote:
    """Weighted BUY/SELL confirmation. BLOCK from a control role withholds it."""
    blockers = [a for a, rec in calls.items()
                if rec == "BLOCK" and a in CONTROL_BLOCKERS]
    if blockers:
        return Vote("WAIT", 0.0, regime, withheld=True,
                    reason=f"withheld: {', '.join(sorted(blockers))} blocked")
    num = den = 0.0
    n_buy = n_sell = n_held = 0
    used: dict[str, float] = {}
    for agent, rec in calls.items():
        if rec not in ("BUY", "SELL"):
            continue
        if not _eligible(agent, regime):
            n_held += 1
            continue
        w = weights.get(agent, 1.0)
        if not math.isfinite(w) or w <= 0:
            w = 1.0
        used[agent] = w
        num += w * (1 if rec == "BUY" else -1)
        den += w
        if rec == "BUY":
            n_buy += 1
        else:
            n_sell += 1
    if den == 0:
        return Vote("WAIT", 0.0, regime, n_buy, n_sell, n_held,
                    reason="no eligible directional votes")
    score = num / den
    if abs(score) < ENSEMBLE_BAND:
        rec = "WAIT"
        why = f"weighted score {score:+.2f} inside the {ENSEMBLE_BAND} band"
    else:
        rec = "BUY" if score > 0 else "SELL"
        why = f"weighted score {score:+.2f} in {regime} regime"
    return Vote(rec, score, regime, n_buy, n_sell, n_held, False, why, used)


def scorecard(
    samples: Sequence[Sample],
    weights: dict[str, float],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Per-agent accuracy, hypothetical P&L (signed close-to-close, before costs), votes."""
    now = now or datetime.now(UTC)
    rows: dict[str, dict[str, Any]] = {}
    for sample in samples:
        dw = decay_weight(sample.as_of, now)
        for agent, rec in sample.calls.items():
            row = rows.setdefault(agent, {
                "id": agent, "calls": 0, "hits": 0, "buy": 0, "sell": 0,
                "wait_or_other": 0, "hyp_pnl_pct": 0.0, "decaying_n": 0.0,
                "decaying_hits": 0.0,
            })
            if rec == "BUY":
                row["buy"] += 1
            elif rec == "SELL":
                row["sell"] += 1
            else:
                row["wait_or_other"] += 1
                continue
            if sample.move == 0:
                continue
            row["calls"] += 1
            signed = sample.move if rec == "BUY" else -sample.move
            row["hyp_pnl_pct"] += 100.0 * signed
            row["decaying_n"] += dw
            if signed > 0:
                row["hits"] += 1
                row["decaying_hits"] += dw
    out = []
    for agent, row in sorted(rows.items()):
        n = row["calls"]
        out.append({
            "id": agent,
            "calls": n,
            "buy": row["buy"],
            "sell": row["sell"],
            "wait_or_other": row["wait_or_other"],
            "accuracy": round(row["hits"] / n, 4) if n else None,
            "hyp_pnl_pct": round(row["hyp_pnl_pct"], 4),
            "weight": weights.get(agent, 1.0),
            "enough_data": n >= MIN_SAMPLES,
            "note": "hypothetical P&L is close-to-close before spread and costs",
        })
    return out


def underperformers(
    samples: Sequence[Sample],
    *,
    now: datetime | None = None,
    window: timedelta = MONTH,
) -> list[dict[str, Any]]:
    """Agents that added no value in the window. Proposals only; nothing is removed."""
    now = now or datetime.now(UTC)
    start = now - window
    recent = [s for s in samples if _aware(s.as_of) >= start]
    cards = scorecard(recent, rolling_weights(recent, now=now), now=now)
    flagged = []
    for row in cards:
        if not row["enough_data"] or row["accuracy"] is None:
            continue
        acc, pnl = row["accuracy"], row["hyp_pnl_pct"]
        if acc > UNDERPERFORM_HIT and pnl > 0:
            continue
        action = "disable" if acc < DISABLE_HIT else "retrain"
        flagged.append({
            "id": row["id"],
            "accuracy": acc,
            "hyp_pnl_pct": pnl,
            "calls": row["calls"],
            "proposal": action,
            "reason": (
                f"accuracy {acc:.0%} and hypothetical P&L {pnl:+.2f}% over {row['calls']} calls"
            ),
        })
    return flagged
