"""Walk-forward evaluation of RT10: step through history point-in-time, resolve later.

At every step the analyzer sees only bars closed by that step; the outcome is read
from bars after it. Results are reported per chronological fold so a single
lucky stretch is visible as one fold, not as the average. Nothing is fitted here,
so every fold is out-of-sample for the fixed rules.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.agents.analyzers.bars import Candle, make_context
from app.agents.analyzers.rocket import RocketSignal, evaluate_outcome, rt10_evaluate
from app.agents.messages import Market

MIN_HISTORY = 120
WINDOW = 300


def stats(rs: list[float]) -> dict[str, Any]:
    if not rs:
        return {"n": 0, "win_rate": None, "avg_r": None, "total_r": 0.0}
    return {"n": len(rs), "win_rate": round(sum(1 for r in rs if r > 0) / len(rs), 4),
            "avg_r": round(sum(rs) / len(rs), 4), "total_r": round(sum(rs), 4)}


def walk_forward(bars: list[Candle], symbol: str, market: Market, timeframe: str,
                 delta: timedelta, *, folds: int = 4, horizon: int = 48,
                 spread: float | None = None) -> dict[str, Any]:
    bars = sorted(bars, key=lambda b: b.open_time)
    trades: list[dict[str, Any]] = []
    i = MIN_HISTORY
    while i < len(bars) - 1:
        as_of = bars[i - 1].open_time + delta
        ctx = make_context(symbol, market, timeframe, delta, bars[max(0, i - WINDOW):i], as_of,
                           spread=spread)
        _, sig = rt10_evaluate(ctx)
        if sig is None:
            i += 1
            continue
        later = bars[i:i + horizon]
        out = evaluate_outcome(sig, later)
        r = float(out["r"]) if "r" in out else None
        trades.append({"idx": i, "at": as_of.isoformat(), "rank": sig.rocket_rank, "direction":
                       sig.direction, "result": out["result"], "r": r})
        i += 1 + (len(later) if r is None else _bars_to_exit(sig, later))
    resolved = [t for t in trades if t["r"] is not None]
    size = max(1, -(-len(bars) // folds))
    fold_rows = []
    for k in range(folds):
        lo, hi = k * size, min(len(bars), (k + 1) * size)
        if lo >= hi:
            break
        rs = [t["r"] for t in resolved if lo <= t["idx"] < hi]
        fold_rows.append({"fold": k + 1, "from": bars[lo].open_time.isoformat(),
                          "to": bars[hi - 1].open_time.isoformat(), **stats(rs)})
    by_rank = {rank: stats([t["r"] for t in resolved if t["rank"] == rank])
               for rank in ("R1", "R2", "R3", "R4", "R5")}
    return {
        "symbol": symbol, "timeframe": timeframe, "bars": len(bars),
        "signals": len(trades), "unresolved": len(trades) - len(resolved),
        "overall": stats([t["r"] for t in resolved]), "folds": fold_rows, "by_rank": by_rank,
        "costs": "spread included" if spread else "no spread/slippage included",
        "note": "Rules are fixed (nothing fitted), one position at a time, stop-first on "
                "ambiguous bars. Not evidence of an edge without many signals per fold.",
    }


def _bars_to_exit(sig: RocketSignal, later: list[Candle]) -> int:
    for n in range(1, len(later) + 1):
        if evaluate_outcome(sig, later[:n])["result"] in ("stop", "target"):
            return n
    return len(later)
