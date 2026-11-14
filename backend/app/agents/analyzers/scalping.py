"""SC01-SC10: short-horizon (scalping) analyzers on closed M1/M5 bars.

SC02 works on bars and the quoted spread, not ticks: tick data is not in the
decision path, so this is microstructure as far as bars can show it.
"""

from __future__ import annotations

import statistics

from app.agents.analyzers.bars import AnalysisContext, atr, ema
from app.agents.analyzers.common import abstain, direction, message
from app.agents.messages import AgentMessage
from app.agents.messages import Recommendation as Rec

COSTLY_SPREAD_TO_ATR = 0.15


def _close_location(c) -> float:
    rng = c.high - c.low
    return 0.0 if rng <= 0 else 2 * (c.close - c.low) / rng - 1


def sc02_microstructure(ctx: AnalysisContext) -> AgentMessage:
    if len(ctx.bars) < 5:
        return abstain("SC02", ctx, "fewer than 5 closed bars")
    last = ctx.bars[-3:]
    score = statistics.fmean(_close_location(b) for b in last)
    ev = [f"close location last 3 bars {score:+.2f} (-1 lows, +1 highs)"]
    return message("SC02", ctx, direction(score, 0.4), min(0.6, abs(score)),
                   "bar-level pressure from where bars close in their range", ev)


def sc03_momentum(ctx: AnalysisContext) -> AgentMessage:
    a = atr(ctx.bars, 14)
    if a is None or len(ctx.bars) < 20:
        return abstain("SC03", ctx, "not enough history for ATR/ROC")
    roc = (ctx.bars[-1].close - ctx.bars[-6].close) / a
    score = max(-1.0, min(1.0, roc / 3))
    return message("SC03", ctx, direction(score, 0.3), min(0.7, abs(score)),
                   "5-bar momentum in ATR units", [f"5-bar move {roc:+.2f} ATR"])


def sc04_liquidity(ctx: AnalysisContext) -> AgentMessage:
    from app.agents.analyzers.smc import equal_levels

    a = atr(ctx.bars, 14)
    if a is None:
        return abstain("SC04", ctx, "not enough history")
    highs, lows = equal_levels(ctx.bars, a)
    if not highs and not lows:
        return message("SC04", ctx, Rec.WAIT, 0.2, "no equal highs/lows (liquidity pools)", [])
    ev = [f"equal highs at {h:.5f}" for h in highs[-2:]] + \
        [f"equal lows at {lo:.5f}" for lo in lows[-2:]]
    return message("SC04", ctx, Rec.WAIT, 0.4, "liquidity pools located (directionless)", ev)


def sc05_spread(ctx: AnalysisContext) -> AgentMessage:
    a = atr(ctx.bars, 14)
    if ctx.spread is None or a is None:
        return abstain("SC05", ctx, "no live spread or ATR")
    ratio = ctx.spread / a
    costly = ratio > COSTLY_SPREAD_TO_ATR
    return message("SC05", ctx, Rec.WAIT, 0.8,
                   "entry cost " + ("too high" if costly else "acceptable"),
                   [f"spread {ratio:.0%} of ATR14"],
                   risk="COSTLY" if costly else "spread acceptable")


def sc06_volatility(ctx: AnalysisContext) -> AgentMessage:
    fast, slow = atr(ctx.bars, 5), atr(ctx.bars, 50)
    if fast is None or slow is None or slow == 0:
        return abstain("SC06", ctx, "not enough history for ATR5/ATR50")
    ratio = fast / slow
    state = "expanding" if ratio > 1.5 else "contracting" if ratio < 0.6 else "normal"
    return message("SC06", ctx, Rec.WAIT, 0.6, f"volatility {state}",
                   [f"ATR5/ATR50 = {ratio:.2f}"],
                   risk="EXTREME" if ratio > 3 else state)


def sc07_entry(ctx: AnalysisContext) -> AgentMessage:
    closes = ctx.closes
    e20, e50, a = ema(closes, 20), ema(closes, 50), atr(ctx.bars, 14)
    if e20 is None or e50 is None or a is None:
        return abstain("SC07", ctx, "not enough history for EMA20/50")
    last = ctx.bars[-1]
    near = abs(last.close - e20) <= 0.5 * a
    if e20 > e50 and near and last.close > last.open:
        return message("SC07", ctx, Rec.BUY, 0.5, "pullback to EMA20 in uptrend, bullish close",
                       [f"EMA20 {e20:.5f} > EMA50 {e50:.5f}",
                        f"entry zone {e20 - 0.25 * a:.5f}-{e20 + 0.25 * a:.5f}"])
    if e20 < e50 and near and last.close < last.open:
        return message("SC07", ctx, Rec.SELL, 0.5, "pullback to EMA20 in downtrend, bearish close",
                       [f"EMA20 {e20:.5f} < EMA50 {e50:.5f}",
                        f"entry zone {e20 - 0.25 * a:.5f}-{e20 + 0.25 * a:.5f}"])
    return message("SC07", ctx, Rec.WAIT, 0.3, "no valid pullback entry", [])


def _position(ctx: AnalysisContext) -> dict | None:
    pos = ctx.extras.get("position")
    if not isinstance(pos, dict) or pos.get("side") not in ("BUY", "SELL"):
        return None
    if not all(isinstance(pos.get(k), int | float) for k in ("entry", "stop")):
        return None
    if pos["entry"] == pos["stop"]:
        return None
    return pos


def _r_multiple(pos: dict, price: float) -> float:
    risk = abs(pos["entry"] - pos["stop"])
    move = price - pos["entry"] if pos["side"] == "BUY" else pos["entry"] - price
    return move / risk


def sc08_fast_exit(ctx: AnalysisContext) -> AgentMessage:
    pos = _position(ctx)
    if pos is None or not ctx.bars:
        return abstain("SC08", ctx, "no open position described")
    r = _r_multiple(pos, ctx.bars[-1].close)
    mom = sc03_momentum(ctx)
    against = (pos["side"] == "BUY" and mom.recommendation is Rec.SELL) or \
        (pos["side"] == "SELL" and mom.recommendation is Rec.BUY)
    if against:
        return message("SC08", ctx, Rec.WAIT, 0.6, "EXIT proposed: momentum turned against",
                       [f"open {r:+.2f}R", *mom.evidence])
    return message("SC08", ctx, Rec.WAIT, 0.3, "hold: no exit condition", [f"open {r:+.2f}R"])


def sc09_position_manager(ctx: AnalysisContext) -> AgentMessage:
    pos = _position(ctx)
    if pos is None or not ctx.bars:
        return abstain("SC09", ctx, "no open position described")
    r = _r_multiple(pos, ctx.bars[-1].close)
    risk = abs(pos["entry"] - pos["stop"])
    if r >= 2:
        trail = pos["entry"] + risk if pos["side"] == "BUY" else pos["entry"] - risk
        return message("SC09", ctx, Rec.WAIT, 0.6, "STOP MOVE proposed: trail to +1R",
                       [f"open {r:+.2f}R", f"proposed stop {trail:.5f}"])
    if r >= 1:
        return message("SC09", ctx, Rec.WAIT, 0.6, "STOP MOVE proposed: break-even",
                       [f"open {r:+.2f}R", f"proposed stop {pos['entry']:.5f}"])
    return message("SC09", ctx, Rec.WAIT, 0.3, "no stop change", [f"open {r:+.2f}R"])


def performance(outcomes: list[float]) -> dict[str, float]:
    wins = [x for x in outcomes if x > 0]
    losses = [-x for x in outcomes if x < 0]
    return {
        "n": len(outcomes),
        "win_rate": len(wins) / len(outcomes) if outcomes else 0.0,
        "expectancy_r": statistics.fmean(outcomes) if outcomes else 0.0,
        "profit_factor": (sum(wins) / sum(losses)) if losses else float("inf") if wins else 0.0,
    }


def sc10_performance(ctx: AnalysisContext) -> AgentMessage:
    outcomes = [float(x) for x in ctx.extras.get("outcomes_r", []) if isinstance(x, int | float)]
    if len(outcomes) < 10:
        return abstain("SC10", ctx, "fewer than 10 resolved trades")
    p = performance(outcomes)
    return message("SC10", ctx, Rec.WAIT, 0.5, "scalping performance after costs (as given)",
                   [f"n={p['n']}", f"win rate {p['win_rate']:.0%}",
                    f"expectancy {p['expectancy_r']:+.2f}R", f"PF {p['profit_factor']:.2f}"])


def sc01_commander(ctx: AnalysisContext) -> AgentMessage:
    entry, mom, cost, vol = sc07_entry(ctx), sc03_momentum(ctx), sc05_spread(ctx), \
        sc06_volatility(ctx)
    ev = [f"SC07 {entry.recommendation.value}", f"SC03 {mom.recommendation.value}",
          f"SC05 {cost.risk_assessment}", f"SC06 {vol.risk_assessment}"]
    if cost.recommendation is Rec.ABSTAIN:
        return message("SC01", ctx, Rec.WAIT, 0.3, "no spread data - scalping needs it", ev)
    blocked = cost.risk_assessment == "COSTLY" or vol.risk_assessment == "EXTREME"
    agree = entry.recommendation in (Rec.BUY, Rec.SELL) and \
        entry.recommendation == mom.recommendation
    if agree and not blocked:
        return message("SC01", ctx, entry.recommendation, 0.5,
                       "entry and momentum agree, cost and volatility acceptable", ev)
    return message("SC01", ctx, Rec.WAIT, 0.4, "no scalping consensus", ev)


ANALYZERS = {
    "SC01": sc01_commander, "SC02": sc02_microstructure, "SC03": sc03_momentum,
    "SC04": sc04_liquidity, "SC05": sc05_spread, "SC06": sc06_volatility,
    "SC07": sc07_entry, "SC08": sc08_fast_exit, "SC09": sc09_position_manager,
    "SC10": sc10_performance,
}
