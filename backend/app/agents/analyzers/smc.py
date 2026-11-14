"""SM01-SM10: Smart Money / ICT concepts computed from the broker's own bars.

These are price-pattern definitions (order blocks, fair value gaps, sweeps,
BOS/CHoCH, premium/discount). They say nothing about real institutional
orders, which no retail feed carries. SM10 uses only public CFTC positioning.
"""

from __future__ import annotations

from app.agents.analyzers.bars import AnalysisContext, Candle, atr, session_names, swings
from app.agents.analyzers.common import abstain, direction, message
from app.agents.messages import AgentMessage
from app.agents.messages import Recommendation as Rec

DISCLAIMER = "pattern on broker bars only; not institutional order data"


def equal_levels(bars: tuple[Candle, ...], a: float, k: int = 2,
                 tol: float = 0.1) -> tuple[list[float], list[float]]:
    hi_idx, lo_idx = swings(bars, k)
    highs = [bars[i].high for i in hi_idx]
    lows = [bars[i].low for i in lo_idx]
    eq_h = [h for i, h in enumerate(highs) for h2 in highs[i + 1:] if abs(h - h2) <= tol * a]
    eq_l = [lo for i, lo in enumerate(lows) for l2 in lows[i + 1:] if abs(lo - l2) <= tol * a]
    return sorted(set(eq_h)), sorted(set(eq_l))


def _need(ctx: AnalysisContext, agent: str, n: int = 30):
    a = atr(ctx.bars, 14)
    if a is None or len(ctx.bars) < n:
        return None, abstain(agent, ctx, f"fewer than {n} closed bars")
    return a, None


def sm02_sweep(ctx: AnalysisContext) -> AgentMessage:
    a, miss = _need(ctx, "SM02")
    if miss:
        return miss
    hi, lo = swings(ctx.bars[:-1], 2)
    last = ctx.bars[-1]
    if hi and last.high > ctx.bars[hi[-1]].high and last.close < ctx.bars[hi[-1]].high:
        return message("SM02", ctx, Rec.SELL, 0.5, "buy-side liquidity swept and rejected",
                       [f"wick above swing high {ctx.bars[hi[-1]].high:.5f}, closed back below",
                        DISCLAIMER])
    if lo and last.low < ctx.bars[lo[-1]].low and last.close > ctx.bars[lo[-1]].low:
        return message("SM02", ctx, Rec.BUY, 0.5, "sell-side liquidity swept and rejected",
                       [f"wick below swing low {ctx.bars[lo[-1]].low:.5f}, closed back above",
                        DISCLAIMER])
    return message("SM02", ctx, Rec.WAIT, 0.2, "no sweep on the last bar", [])


def order_blocks(bars: tuple[Candle, ...], a: float) -> list[tuple[str, float, float, int]]:
    """(side, low, high, index): last opposite candle before a >=1.5 ATR displacement."""
    found = []
    for i in range(1, len(bars) - 3):
        move = bars[i + 3].close - bars[i].close
        if move >= 1.5 * a and bars[i].close < bars[i].open:
            found.append(("bull", bars[i].low, bars[i].high, i))
        if move <= -1.5 * a and bars[i].close > bars[i].open:
            found.append(("bear", bars[i].low, bars[i].high, i))
    return found


def sm03_order_block(ctx: AnalysisContext) -> AgentMessage:
    a, miss = _need(ctx, "SM03")
    if miss:
        return miss
    price = ctx.bars[-1].close
    for side, low, high, i in reversed(order_blocks(ctx.bars[:-1], a)):
        if low <= price <= high:
            rec = Rec.BUY if side == "bull" else Rec.SELL
            return message("SM03", ctx, rec, 0.45, f"price back inside a {side}ish order block",
                           [f"OB {low:.5f}-{high:.5f} from bar {i}", DISCLAIMER])
    return message("SM03", ctx, Rec.WAIT, 0.2, "price not in an order block", [])


def fair_value_gaps(bars: tuple[Candle, ...]) -> list[tuple[str, float, float, int]]:
    gaps = []
    for i in range(2, len(bars)):
        if bars[i - 2].high < bars[i].low:
            gaps.append(("bull", bars[i - 2].high, bars[i].low, i))
        if bars[i - 2].low > bars[i].high:
            gaps.append(("bear", bars[i].high, bars[i - 2].low, i))
    return gaps


def sm04_fvg(ctx: AnalysisContext) -> AgentMessage:
    a, miss = _need(ctx, "SM04")
    if miss:
        return miss
    price = ctx.bars[-1].close
    for side, low, high, i in reversed(fair_value_gaps(ctx.bars[:-1])):
        later = ctx.bars[i + 1:-1]
        filled = any(b.low <= low for b in later) if side == "bull" else \
            any(b.high >= high for b in later)
        if not filled and low <= price <= high:
            return message("SM04", ctx, Rec.BUY if side == "bull" else Rec.SELL, 0.4,
                           f"price inside an unfilled {side}ish FVG",
                           [f"FVG {low:.5f}-{high:.5f} from bar {i}", DISCLAIMER])
    return message("SM04", ctx, Rec.WAIT, 0.2, "no unfilled FVG at price", [])


def _trend(ctx: AnalysisContext) -> tuple[str, list[int], list[int]]:
    hi, lo = swings(ctx.bars[:-1], 2)
    if len(hi) < 2 or len(lo) < 2:
        return "unknown", hi, lo
    b = ctx.bars
    if b[hi[-1]].high > b[hi[-2]].high and b[lo[-1]].low > b[lo[-2]].low:
        return "up", hi, lo
    if b[hi[-1]].high < b[hi[-2]].high and b[lo[-1]].low < b[lo[-2]].low:
        return "down", hi, lo
    return "range", hi, lo


def sm05_bos_choch(ctx: AnalysisContext) -> AgentMessage:
    a, miss = _need(ctx, "SM05")
    if miss:
        return miss
    trend, hi, lo = _trend(ctx)
    if not hi or not lo:
        return abstain("SM05", ctx, "no confirmed swings")
    close = ctx.bars[-1].close
    if close > ctx.bars[hi[-1]].high:
        kind = "BOS" if trend == "up" else "CHoCH"
        return message("SM05", ctx, Rec.BUY, 0.5 if kind == "BOS" else 0.4,
                       f"bullish {kind}", [f"close above swing high {ctx.bars[hi[-1]].high:.5f}",
                                           f"prior structure {trend}", DISCLAIMER])
    if close < ctx.bars[lo[-1]].low:
        kind = "BOS" if trend == "down" else "CHoCH"
        return message("SM05", ctx, Rec.SELL, 0.5 if kind == "BOS" else 0.4,
                       f"bearish {kind}", [f"close below swing low {ctx.bars[lo[-1]].low:.5f}",
                                           f"prior structure {trend}", DISCLAIMER])
    return message("SM05", ctx, Rec.WAIT, 0.2, "no structure break", [f"structure {trend}"])


def sm06_structure(ctx: AnalysisContext) -> AgentMessage:
    a, miss = _need(ctx, "SM06")
    if miss:
        return miss
    trend, _, _ = _trend(ctx)
    score = {"up": 0.5, "down": -0.5}.get(trend, 0.0)
    return message("SM06", ctx, direction(score), 0.4, f"market structure {trend}",
                   [f"swing sequence: {trend}"] if trend in ("up", "down") else [])


def sm07_liquidity_sides(ctx: AnalysisContext) -> AgentMessage:
    a, miss = _need(ctx, "SM07")
    if miss:
        return miss
    highs, lows = equal_levels(ctx.bars, a)
    price = ctx.bars[-1].close
    above = [h for h in highs if h > price]
    below = [lo for lo in lows if lo < price]
    ev = []
    if above:
        ev.append(f"buy-side liquidity {min(above):.5f} ({(min(above) - price) / a:.1f} ATR up)")
    if below:
        ev.append(f"sell-side liquidity {max(below):.5f} ({(price - max(below)) / a:.1f} ATR down)")
    return message("SM07", ctx, Rec.WAIT, 0.3 if ev else 0.1,
                   "buy/sell-side liquidity map (directionless)", ev)


def sm08_premium_discount(ctx: AnalysisContext) -> AgentMessage:
    a, miss = _need(ctx, "SM08")
    if miss:
        return miss
    hi, lo = swings(ctx.bars[:-1], 2)
    if not hi or not lo:
        return abstain("SM08", ctx, "no dealing range")
    top, bottom = ctx.bars[hi[-1]].high, ctx.bars[lo[-1]].low
    if top <= bottom:
        return abstain("SM08", ctx, "degenerate dealing range")
    pos = (ctx.bars[-1].close - bottom) / (top - bottom)
    score = max(-0.6, min(0.6, (0.5 - pos)))  # discount -> buy bias, premium -> sell
    zone = "premium" if pos > 0.5 else "discount"
    return message("SM08", ctx, direction(score, 0.2), 0.3, f"price in {zone}",
                   [f"range {bottom:.5f}-{top:.5f}, position {pos:.0%}"])


def sm09_sessions(ctx: AnalysisContext) -> AgentMessage:
    if not ctx.bars:
        return abstain("SM09", ctx, "no bars")
    hour = ctx.as_of.hour
    zone = "london_open" if 7 <= hour < 10 else "new_york_open" if 12 <= hour < 15 else None
    today = [b for b in ctx.bars if b.open_time.date() == ctx.as_of.date()
             and b.open_time.hour < 6]
    ev = [f"sessions {', '.join(session_names(ctx.as_of)) or 'none'}"]
    if today:
        ev.append(f"asian range {min(b.low for b in today):.5f}-{max(b.high for b in today):.5f}")
    if zone:
        ev.append(f"ICT kill zone {zone} (UTC hours, DST-agnostic)")
    return message("SM09", ctx, Rec.WAIT, 0.4, "session context (directionless)", ev)


def sm10_institutional(ctx: AnalysisContext) -> AgentMessage:
    share = ctx.extras.get("cot_speculative_net_long_share")
    if not isinstance(share, int | float) or not 0 <= share <= 1:
        return abstain("SM10", ctx, "no public CFTC positioning given")
    crowd = (share - 0.5) * 2
    rec = Rec.WAIT if abs(crowd) < 0.6 else (Rec.SELL if crowd > 0 else Rec.BUY)
    return message("SM10", ctx, rec, 0.3, "public CFTC speculative positioning (weekly, lagged)",
                   [f"speculators {share:.0%} net long", "source: CFTC COT, public"])


def sm01_smart_money(ctx: AnalysisContext) -> AgentMessage:
    parts = [f(ctx) for f in (sm02_sweep, sm03_order_block, sm04_fvg, sm05_bos_choch,
                              sm06_structure, sm08_premium_discount)]
    votes = [1 if m.recommendation is Rec.BUY else -1 for m in parts
             if m.recommendation in (Rec.BUY, Rec.SELL)]
    ev = [f"{m.agent_id} {m.recommendation.value}" for m in parts]
    if len(votes) < 2 or abs(sum(votes)) < len(votes) * 0.6:
        return message("SM01", ctx, Rec.WAIT, 0.3, "no SMC confluence", ev)
    return message("SM01", ctx, Rec.BUY if sum(votes) > 0 else Rec.SELL, 0.45,
                   "SMC confluence", [*ev, DISCLAIMER])


ANALYZERS = {
    "SM01": sm01_smart_money, "SM02": sm02_sweep, "SM03": sm03_order_block, "SM04": sm04_fvg,
    "SM05": sm05_bos_choch, "SM06": sm06_structure, "SM07": sm07_liquidity_sides,
    "SM08": sm08_premium_discount, "SM09": sm09_sessions, "SM10": sm10_institutional,
}
