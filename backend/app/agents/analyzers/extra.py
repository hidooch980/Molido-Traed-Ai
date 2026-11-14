"""TA02 multi-timeframe, TA03 price action, RK02 dynamic SL/TP - deterministic, shadow.

Higher timeframes are folded from the context's own closed bars (complete
groups only, epoch-aligned), so nothing here can see a bar that has not closed.
"""

from __future__ import annotations

from datetime import timedelta

from app.agents.analyzers.bars import AnalysisContext, Candle, atr, ema, swings
from app.agents.analyzers.common import abstain, message
from app.agents.messages import AgentMessage
from app.agents.messages import Recommendation as Rec


def fold(bars: tuple[Candle, ...], base: timedelta, k: int) -> list[Candle]:
    """Group k base bars into one, keeping only complete, aligned groups."""
    span = (base * k).total_seconds()
    groups: dict[int, list[Candle]] = {}
    for b in bars:
        groups.setdefault(int(b.open_time.timestamp() // span), []).append(b)
    out = []
    for key in sorted(groups):
        g = groups[key]
        if len(g) != k:
            continue
        out.append(Candle(g[0].open_time, g[0].open, max(x.high for x in g),
                          min(x.low for x in g), g[-1].close,
                          float(sum(x.volume or 0 for x in g))))
    return out


def _trend(bars: list[Candle] | tuple[Candle, ...]) -> int | None:
    closes = [b.close for b in bars]
    if len(closes) < 25:
        return None
    now, before = ema(closes, 20), ema(closes[:-3], 20)
    if now is None or before is None:
        return None
    if closes[-1] > now and now > before:
        return 1
    if closes[-1] < now and now < before:
        return -1
    return 0


def ta02_multi_timeframe(ctx: AnalysisContext) -> AgentMessage:
    frames = {"x1": list(ctx.bars), "x4": fold(ctx.bars, ctx.bar_delta, 4),
              "x16": fold(ctx.bars, ctx.bar_delta, 16)}
    trends = {k: _trend(v) for k, v in frames.items()}
    known = {k: t for k, t in trends.items() if t is not None}
    if len(known) < 2:
        return abstain("TA02", ctx, "not enough closed bars for two higher timeframes")
    ev = [f"{k} ({len(frames[k])} bars): {'up' if t > 0 else 'down' if t < 0 else 'flat'}"
          for k, t in known.items()]
    vals = list(known.values())
    if all(v == 1 for v in vals):
        return message("TA02", ctx, Rec.BUY, 0.5 + 0.1 * len(vals), "timeframes aligned up", ev)
    if all(v == -1 for v in vals):
        return message("TA02", ctx, Rec.SELL, 0.5 + 0.1 * len(vals), "timeframes aligned down",
                       ev)
    return message("TA02", ctx, Rec.WAIT, 0.3, "timeframes disagree", ev)


def candle_pattern(prev: Candle, last: Candle) -> tuple[str, int] | None:
    rng = last.high - last.low
    if rng <= 0:
        return None
    body = abs(last.close - last.open)
    upper = last.high - max(last.open, last.close)
    lower = min(last.open, last.close) - last.low
    if (last.close > last.open and prev.close < prev.open and last.close >= prev.open
            and last.open <= prev.close):
        return "bullish engulfing", 1
    if (last.close < last.open and prev.close > prev.open and last.close <= prev.open
            and last.open >= prev.close):
        return "bearish engulfing", -1
    if lower >= 2 * max(body, rng * 0.05) and upper <= body + rng * 0.1:
        return "bullish pin bar", 1
    if upper >= 2 * max(body, rng * 0.05) and lower <= body + rng * 0.1:
        return "bearish pin bar", -1
    if last.high <= prev.high and last.low >= prev.low:
        return "inside bar", 0
    if body <= rng * 0.1:
        return "doji", 0
    return None


def ta03_price_action(ctx: AnalysisContext) -> AgentMessage:
    if len(ctx.bars) < 25:
        return abstain("TA03", ctx, "fewer than 25 closed bars")
    found = candle_pattern(ctx.bars[-2], ctx.bars[-1])
    if found is None:
        return message("TA03", ctx, Rec.WAIT, 0.2, "no candle pattern on the last bar", [])
    name, side = found
    hi, lo = swings(ctx.bars, 2)
    a = atr(ctx.bars, 14) or 0.0
    last = ctx.bars[-1]
    at_level = False
    if side > 0 and lo:
        at_level = abs(last.low - ctx.bars[lo[-1]].low) <= a
    if side < 0 and hi:
        at_level = abs(last.high - ctx.bars[hi[-1]].high) <= a
    ev = [name] + (["at a confirmed swing level"] if at_level else ["away from swing levels"])
    if side == 0:
        return message("TA03", ctx, Rec.WAIT, 0.3, f"{name}: indecision", ev)
    conf = 0.55 if at_level else 0.35
    return message("TA03", ctx, Rec.BUY if side > 0 else Rec.SELL, conf, name, ev)


def sl_tp(ctx: AnalysisContext, side: str) -> dict[str, float] | None:
    """Stop beyond the last confirmed swing (1-3 ATR), target at the next swing or 2R."""
    a = atr(ctx.bars, 14)
    if a is None or len(ctx.bars) < 20:
        return None
    entry = ctx.bars[-1].close
    hi, lo = swings(ctx.bars, 2)
    sign = 1 if side == "BUY" else -1
    if sign > 0:
        swing = ctx.bars[lo[-1]].low if lo else entry - 1.5 * a
        dist = entry - swing + 0.25 * a
    else:
        swing = ctx.bars[hi[-1]].high if hi else entry + 1.5 * a
        dist = swing - entry + 0.25 * a
    dist = min(max(dist, a), 3 * a)
    stop = entry - sign * dist
    levels = [ctx.bars[i].high for i in hi] if sign > 0 else [ctx.bars[i].low for i in lo]
    ahead = sorted((lv for lv in levels if sign * (lv - entry) > 0),
                   key=lambda lv: abs(lv - entry))
    two_r = entry + sign * 2 * dist
    target = ahead[0] if ahead and abs(ahead[0] - entry) >= 1.5 * dist else two_r
    return {"entry": entry, "stop_loss": stop, "take_profit": target,
            "rr": abs(target - entry) / dist, "atr": a}


def rk02_sl_tp(ctx: AnalysisContext) -> AgentMessage:
    sides = [ctx.extras["side"]] if ctx.extras.get("side") in ("BUY", "SELL") else ["BUY", "SELL"]
    plans = {s: sl_tp(ctx, s) for s in sides}
    if all(p is None for p in plans.values()):
        return abstain("RK02", ctx, "not enough history for ATR and swings")
    ev = [f"{s}: SL {p['stop_loss']:.5f} TP {p['take_profit']:.5f} ({p['rr']:.1f}R)"
          for s, p in plans.items() if p]
    return message("RK02", ctx, Rec.WAIT, 0.5, "structure/ATR stop and target proposal", ev)


ANALYZERS = {"TA02": ta02_multi_timeframe, "TA03": ta03_price_action, "RK02": rk02_sl_tp}
