"""RT01-RT10: Rocket Trade Hunter. PROPOSED signals only - never executed.

R1..R5 grade the *quality of the evidence*, not a probability of profit.
Every signal carries entry zone, stop, target, expected R:R after spread,
supporting and conflicting evidence, invalidation, and
`risk_approval_status = NOT_SUBMITTED`: nothing here talks to the risk brain or
to execution. A signal with no valid stop or a non-positive net R:R is not
produced at all.
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from app.agents.analyzers.bars import AnalysisContext, Candle, atr, ema, swings
from app.agents.analyzers.common import abstain, message
from app.agents.analyzers.smc import sm02_sweep
from app.agents.messages import AgentMessage
from app.agents.messages import Recommendation as Rec


def _base(ctx: AnalysisContext, agent: str, n: int = 30):
    a = atr(ctx.bars[:-1], 20)
    if a is None or len(ctx.bars) < n or a == 0:
        return None, abstain(agent, ctx, f"fewer than {n} closed bars")
    return a, None


def rt01_explosion(ctx: AnalysisContext) -> AgentMessage:
    a, miss = _base(ctx, "RT01")
    if miss:
        return miss
    last = ctx.bars[-1]
    ratio = (last.high - last.low) / a
    if ratio < 2.5:
        return message("RT01", ctx, Rec.WAIT, 0.1, "no range explosion",
                       [f"range {ratio:.1f}x ATR"])
    rec = Rec.BUY if last.close > last.open else Rec.SELL
    return message("RT01", ctx, rec, min(0.8, ratio / 5), "range explosion",
                   [f"last bar range {ratio:.1f}x ATR20"])


def rt02_momentum_surge(ctx: AnalysisContext) -> AgentMessage:
    a, miss = _base(ctx, "RT02")
    if miss:
        return miss
    c = ctx.closes
    now, before = (c[-1] - c[-4]) / a, (c[-4] - c[-7]) / a
    accel = now - before
    if abs(now) < 1.5 or (now > 0) != (accel > 0):
        return message("RT02", ctx, Rec.WAIT, 0.1, "no momentum surge",
                       [f"3-bar move {now:+.2f} ATR, accel {accel:+.2f}"])
    return message("RT02", ctx, Rec.BUY if now > 0 else Rec.SELL, min(0.8, abs(now) / 4),
                   "accelerating momentum", [f"3-bar move {now:+.2f} ATR, accel {accel:+.2f}"])


def rt03_breakout(ctx: AnalysisContext, n: int = 20) -> AgentMessage:
    a, miss = _base(ctx, "RT03", n + 2)
    if miss:
        return miss
    window = ctx.bars[-n - 1:-1]
    top, bottom = max(b.high for b in window), min(b.low for b in window)
    last, prev = ctx.bars[-1], ctx.bars[-2]
    prior = ctx.bars[-n - 2:-2]
    p_top, p_bot = max(b.high for b in prior), min(b.low for b in prior)
    fake = (prev.high > p_top and prev.close < p_top) or (prev.low < p_bot and prev.close > p_bot)
    if last.close > top + 0.2 * a:
        return message("RT03", ctx, Rec.BUY, 0.5, "breakout above range",
                       [f"close {last.close:.5f} > {n}-bar high {top:.5f}"] +
                       (["previous bar was a failed breakout"] if fake else []),
                       risk="FAKE_RISK" if fake else "normal")
    if last.close < bottom - 0.2 * a:
        return message("RT03", ctx, Rec.SELL, 0.5, "breakdown below range",
                       [f"close {last.close:.5f} < {n}-bar low {bottom:.5f}"] +
                       (["previous bar was a failed breakout"] if fake else []),
                       risk="FAKE_RISK" if fake else "normal")
    return message("RT03", ctx, Rec.WAIT, 0.1, "inside range",
                   ["previous bar failed a breakout"] if fake else [],
                   risk="FAKE_RISK" if fake else "normal")


def _widths(closes: list[float], n: int = 20) -> list[float]:
    out = []
    for i in range(n, len(closes) + 1):
        w = closes[i - n:i]
        m = statistics.fmean(w)
        out.append(statistics.pstdev(w) / m if m else 0.0)
    return out


def rt04_compression(ctx: AnalysisContext) -> AgentMessage:
    if len(ctx.bars) < 120:
        return abstain("RT04", ctx, "fewer than 120 closed bars")
    widths = _widths(ctx.closes[:-1])[-100:]
    current = widths[-1]
    rank = sum(1 for w in widths if w <= current) / len(widths)
    if rank > 0.2:
        return message("RT04", ctx, Rec.WAIT, 0.1, "not compressed",
                       [f"width percentile {rank:.0%}"])
    box = ctx.bars[-21:-1]
    top, bottom = max(b.high for b in box), min(b.low for b in box)
    last = ctx.bars[-1].close
    ev = [f"width percentile {rank:.0%}", f"box {bottom:.5f}-{top:.5f}"]
    if last > top:
        return message("RT04", ctx, Rec.BUY, 0.5, "compression released upward", ev)
    if last < bottom:
        return message("RT04", ctx, Rec.SELL, 0.5, "compression released downward", ev)
    return message("RT04", ctx, Rec.WAIT, 0.3, "compressed, waiting for release", ev)


def rt05_abnormal_volume(ctx: AnalysisContext) -> AgentMessage:
    if len(ctx.bars) < 50:
        return abstain("RT05", ctx, "fewer than 50 closed bars")
    last = ctx.bars[-1]
    same_hour = [b.volume for b in ctx.bars[:-1] if b.open_time.hour == last.open_time.hour
                 and b.volume > 0]
    if len(same_hour) < 5 or last.volume <= 0:
        return abstain("RT05", ctx, "no tick-volume baseline for this session hour")
    base = statistics.median(same_hour)
    ratio = last.volume / base
    if ratio < 2.5:
        return message("RT05", ctx, Rec.WAIT, 0.1, "volume normal",
                       [f"{ratio:.1f}x same-hour median"])
    rec = Rec.BUY if last.close > last.open else Rec.SELL
    return message("RT05", ctx, rec, min(0.7, ratio / 6), "abnormal tick volume",
                   [f"tick volume {ratio:.1f}x median of {len(same_hour)} same-hour bars"])


def rt06_news(ctx: AnalysisContext) -> AgentMessage:
    events = ctx.extras.get("events")
    if not isinstance(events, list):
        return abstain("RT06", ctx, "no economic calendar given")
    ccys = {ctx.symbol[:3], ctx.symbol[3:6]}
    near = []
    for e in events:
        if not isinstance(e, dict) or e.get("impact") != "high" or e.get("currency") not in ccys:
            continue
        t = e.get("time")
        if isinstance(t, datetime) and t.tzinfo is not None:
            minutes = (t - ctx.as_of).total_seconds() / 60
            if -30 <= minutes <= 60:
                near.append(f"{e.get('currency')} {e.get('title', 'event')} {minutes:+.0f} min")
    if near:
        return message("RT06", ctx, Rec.WAIT, 0.8, "high-impact catalyst window", near,
                       risk="NEWS_WINDOW")
    return message("RT06", ctx, Rec.WAIT, 0.3, "no high-impact event near", [])


def rt07_liquidity_burst(ctx: AnalysisContext) -> AgentMessage:
    a, miss = _base(ctx, "RT07")
    if miss:
        return miss
    sweep = sm02_sweep(ctx)
    last = ctx.bars[-1]
    expanded = (last.high - last.low) >= 1.5 * a
    if sweep.recommendation in (Rec.BUY, Rec.SELL) and expanded:
        return message("RT07", ctx, sweep.recommendation, 0.5, "sweep with range expansion",
                       [*sweep.evidence, f"range {(last.high - last.low) / a:.1f}x ATR"])
    return message("RT07", ctx, Rec.WAIT, 0.1, "no explosive liquidity event", [])


def rt08_scenarios(ctx: AnalysisContext) -> AgentMessage:
    a, miss = _base(ctx, "RT08")
    if miss:
        return miss
    hi, lo = swings(ctx.bars[:-1], 2)
    c = ctx.bars[-1].close
    inv_bull = ctx.bars[lo[-1]].low if lo else c - 1.5 * a
    inv_bear = ctx.bars[hi[-1]].high if hi else c + 1.5 * a
    ev = [f"bull: target {c + 1.5 * a:.5f}, invalid below {inv_bull:.5f}",
          f"bear: target {c - 1.5 * a:.5f}, invalid above {inv_bear:.5f}"]
    return message("RT08", ctx, Rec.WAIT, 0.2, "two-sided scenarios (no probability claimed)", ev)


def rt09_exit_plan(ctx: AnalysisContext) -> AgentMessage:
    pos = ctx.extras.get("position")
    a = atr(ctx.bars, 14)
    if not isinstance(pos, dict) or a is None or pos.get("side") not in ("BUY", "SELL"):
        return abstain("RT09", ctx, "no rocket position described")
    entry, stop = float(pos["entry"]), float(pos["stop"])
    risk = abs(entry - stop)
    if risk == 0:
        return abstain("RT09", ctx, "position has no stop distance")
    price = ctx.bars[-1].close
    r = (price - entry) / risk if pos["side"] == "BUY" else (entry - price) / risk
    bars_open = int(pos.get("bars_open", 0))
    if bars_open >= 12 and r < 0.5:
        plan = "time stop: close (move did not develop)"
    elif r >= 1.5:
        trail = price - a if pos["side"] == "BUY" else price + a
        plan = f"trail stop to {trail:.5f} (1 ATR)"
    elif r >= 1.0:
        plan = "take partial 50%, stop to break-even"
    else:
        plan = "hold with original stop"
    return message("RT09", ctx, Rec.WAIT, 0.5, f"PROPOSED exit plan: {plan}",
                   [f"open {r:+.2f}R", f"bars open {bars_open}"])


@dataclass
class RocketSignal:
    symbol: str
    direction: str
    timeframe: str
    signal_timestamp: str
    market_regime: str
    rocket_rank: str
    entry_zone: tuple[float, float]
    stop_loss: float
    take_profit: float
    expected_rr: float
    spread: float | None
    slippage_estimate: float
    volatility_atr: float
    supporting_evidence: list[str]
    conflicting_evidence: list[str]
    confidence_calibration: str
    invalidation: str
    risk_approval_status: str = "NOT_SUBMITTED"
    status: str = "PROPOSED"
    score: float = 0.0
    contributors: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


RANKS = ((4.5, "R5"), (3.5, "R4"), (2.5, "R3"), (1.5, "R2"), (0.0, "R1"))


def rank(score: float) -> str:
    return next(label for floor, label in RANKS if score >= floor)


def rt10_evaluate(ctx: AnalysisContext, *, slippage_atr: float = 0.05,
                  ) -> tuple[AgentMessage, RocketSignal | None]:
    a = atr(ctx.bars[:-1], 20)
    if a is None or len(ctx.bars) < 120:
        return abstain("RT10", ctx, "fewer than 120 closed bars"), None
    parts = {f.__name__.split("_")[0].upper(): f(ctx) for f in
             (rt01_explosion, rt02_momentum_surge, rt03_breakout, rt04_compression,
              rt05_abnormal_volume, rt07_liquidity_burst)}
    news = rt06_news(ctx)
    buys = [k for k, m in parts.items() if m.recommendation is Rec.BUY]
    sells = [k for k, m in parts.items() if m.recommendation is Rec.SELL]
    if not buys and not sells:
        return message("RT10", ctx, Rec.WAIT, 0.1, "no rocket conditions", []), None
    side = "BUY" if len(buys) >= len(sells) else "SELL"
    support, against = (buys, sells) if side == "BUY" else (sells, buys)
    score = float(len(support)) - 1.0 * len(against)
    conflicts = [f"{k} says the other way" for k in against]
    if parts["RT03"].risk_assessment == "FAKE_RISK":
        score -= 1.0
        conflicts.append("recent failed breakout")
    last = ctx.bars[-1]
    e20 = ema(ctx.closes, 20) or last.close
    stretch = abs(last.close - e20) / a
    if stretch > 3:
        score -= 1.5
        conflicts.append(f"over-extended {stretch:.1f} ATR from EMA20 (chasing risk)")
    if news.risk_assessment == "NEWS_WINDOW":
        score -= 1.0
        conflicts.extend(news.evidence)
    hi, lo = swings(ctx.bars[:-1], 2)
    if side == "BUY":
        stop = min(ctx.bars[lo[-1]].low if lo else last.close - 1.5 * a, last.close - a)
    else:
        stop = max(ctx.bars[hi[-1]].high if hi else last.close + 1.5 * a, last.close + a)
    risk = abs(last.close - stop)
    if risk <= 0:
        return message("RT10", ctx, Rec.WAIT, 0.1, "no valid stop", []), None
    target = last.close + 2 * risk if side == "BUY" else last.close - 2 * risk
    cost = (ctx.spread or 0.0) + slippage_atr * a
    rr = (2 * risk - cost) / (risk + cost)
    if rr <= 0:
        return message("RT10", ctx, Rec.WAIT, 0.1, "costs consume the reward", []), None
    if rr < 1.2:
        score -= 1.0
        conflicts.append(f"net R:R {rr:.2f} after costs")
    score = max(0.0, score)
    regime = ctx.extras.get("regime") or "unknown"
    signal = RocketSignal(
        symbol=ctx.symbol, direction=side, timeframe=ctx.timeframe,
        signal_timestamp=ctx.as_of.isoformat(), market_regime=str(regime),
        rocket_rank=rank(score),
        entry_zone=(round(last.close - 0.1 * a, 6), round(last.close + 0.1 * a, 6)),
        stop_loss=round(stop, 6), take_profit=round(target, 6), expected_rr=round(rr, 3),
        spread=ctx.spread, slippage_estimate=round(slippage_atr * a, 6),
        volatility_atr=round(a, 6),
        supporting_evidence=[e for k in support for e in parts[k].evidence],
        conflicting_evidence=conflicts,
        confidence_calibration="uncalibrated: rank grades evidence, not win probability",
        invalidation=f"close beyond {stop:.5f}", score=round(score, 2),
        contributors={k: m.recommendation.value for k, m in parts.items()},
    )
    rec = Rec.BUY if side == "BUY" else Rec.SELL
    msg = message("RT10", ctx, rec if score >= 1.5 else Rec.WAIT, min(0.6, score / 8),
                  f"rocket {signal.rocket_rank} {side} (PROPOSED, not submitted)",
                  [f"score {score:.1f}", *signal.supporting_evidence[:5]],
                  risk=f"net R:R {rr:.2f}; stop {stop:.5f}")
    return msg, signal


def evaluate_outcome(signal: RocketSignal, later: list[Candle]) -> dict[str, float | str]:
    """After the fact, for learning: MFE/MAE in R and which level was hit first."""
    entry = (signal.entry_zone[0] + signal.entry_zone[1]) / 2
    risk = abs(entry - signal.stop_loss)
    if risk == 0 or not later:
        return {"result": "unresolved"}
    sign = 1 if signal.direction == "BUY" else -1
    mfe = mae = 0.0
    for b in later:
        fav = (b.high - entry) * sign if sign > 0 else (entry - b.low)
        adv = (entry - b.low) if sign > 0 else (b.high - entry)
        mfe, mae = max(mfe, fav / risk), max(mae, adv / risk)
        hit_stop = b.low <= signal.stop_loss if sign > 0 else b.high >= signal.stop_loss
        hit_tp = b.high >= signal.take_profit if sign > 0 else b.low <= signal.take_profit
        if hit_stop:  # conservative: a bar touching both counts as a loss
            return {"result": "stop", "r": -1.0, "mfe_r": mfe, "mae_r": mae}
        if hit_tp:
            return {"result": "target", "r": abs(signal.take_profit - entry) / risk,
                    "mfe_r": mfe, "mae_r": mae}
    return {"result": "open", "mfe_r": mfe, "mae_r": mae}


ANALYZERS = {
    "RT01": rt01_explosion, "RT02": rt02_momentum_surge, "RT03": rt03_breakout,
    "RT04": rt04_compression, "RT05": rt05_abnormal_volume, "RT06": rt06_news,
    "RT07": rt07_liquidity_burst, "RT08": rt08_scenarios, "RT09": rt09_exit_plan,
    "RT10": lambda ctx: rt10_evaluate(ctx)[0],
}
