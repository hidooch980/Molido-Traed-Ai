"""Shadow analyzers for the roles that were implemented only on the trading path.

Each function reads the closed bars in the context plus optional extras, and
emits an AgentMessage. Missing inputs are WAIT or ABSTAIN, never a guess.
None of these place, size, or route an order. Only L4 roles may BLOCK, and
none of them can override a Risk Brain BLOCK.
"""

from __future__ import annotations

from typing import Any

from app.agents.analyzers.bars import AnalysisContext, atr, ema, swings
from app.agents.analyzers.common import abstain, message
from app.agents.analyzers.extra import _trend, sl_tp
from app.agents.messages import AgentMessage
from app.agents.messages import Recommendation as Rec
from app.agents.risk_gate import RiskLimits
from app.agents.slippage import DEFAULT_CAP_POINTS, decide

# --------------------------------------------------------------------------- TA / AI


def _rsi(closes: list[float], n: int = 14) -> float | None:
    if len(closes) < n + 1:
        return None
    gains = 0.0
    losses = 0.0
    window = closes[-(n + 1):]
    for a, b in zip(window, window[1:], strict=False):
        delta = b - a
        if delta >= 0:
            gains += delta
        else:
            losses += -delta
    avg_loss = losses / n
    if avg_loss == 0:
        return 100.0 if gains > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + (gains / n) / avg_loss)


def ta01_technical(ctx: AnalysisContext) -> AgentMessage:
    closes = ctx.closes
    if len(closes) < 50:
        return abstain("TA01", ctx, "fewer than 50 closed bars")
    fast, slow, last = ema(closes, 20), ema(closes, 50), closes[-1]
    rel = _rsi(closes, 14)
    a = atr(ctx.bars, 14)
    if fast is None or slow is None or rel is None or a is None:
        return abstain("TA01", ctx, "indicators undefined on this window")
    ev = [f"EMA20={fast:.5f}", f"EMA50={slow:.5f}", f"RSI14={rel:.1f}", f"ATR={a:.5f}"]
    if last > fast > slow and rel < 75:
        return message("TA01", ctx, Rec.BUY, 0.45, "price above rising EMAs, RSI not extreme", ev)
    if last < fast < slow and rel > 25:
        return message("TA01", ctx, Rec.SELL, 0.45, "price below falling EMAs, RSI not extreme", ev)
    return message("TA01", ctx, Rec.WAIT, 0.25, "technicals are mixed or extreme", ev)


def ta04_trend(ctx: AnalysisContext) -> AgentMessage:
    trend = _trend(ctx.bars)
    if trend is None:
        return abstain("TA04", ctx, "not enough closed bars for a trend reading")
    ev = [f"EMA20 slope/position: {'up' if trend > 0 else 'down' if trend < 0 else 'flat'}"]
    if trend > 0:
        return message("TA04", ctx, Rec.BUY, 0.4, "short-term trend up", ev)
    if trend < 0:
        return message("TA04", ctx, Rec.SELL, 0.4, "short-term trend down", ev)
    return message("TA04", ctx, Rec.WAIT, 0.25, "no directional trend", ev)


def ta05_reversal(ctx: AnalysisContext) -> AgentMessage:
    if len(ctx.bars) < 25:
        return abstain("TA05", ctx, "fewer than 25 closed bars")
    from app.agents.analyzers.extra import candle_pattern

    found = candle_pattern(ctx.bars[-2], ctx.bars[-1])
    a = atr(ctx.bars, 14) or 0.0
    hi, lo = swings(ctx.bars, 2)
    last = ctx.bars[-1]
    ev = []
    if found:
        ev.append(found[0])
    at_low = bool(lo) and abs(last.low - ctx.bars[lo[-1]].low) <= a
    at_high = bool(hi) and abs(last.high - ctx.bars[hi[-1]].high) <= a
    if at_low:
        ev.append("at a confirmed swing low")
    if at_high:
        ev.append("at a confirmed swing high")
    if found and found[1] > 0 and at_low:
        return message("TA05", ctx, Rec.BUY, 0.5, "bullish reversal at a swing low", ev)
    if found and found[1] < 0 and at_high:
        return message("TA05", ctx, Rec.SELL, 0.5, "bearish reversal at a swing high", ev)
    return message("TA05", ctx, Rec.WAIT, 0.2, "no reversal at a confirmed swing", ev)


def ta06_breakout(ctx: AnalysisContext) -> AgentMessage:
    if len(ctx.bars) < 30:
        return abstain("TA06", ctx, "fewer than 30 closed bars")
    a = atr(ctx.bars, 14)
    hi, lo = swings(ctx.bars, 2)
    if a is None or (not hi and not lo):
        return abstain("TA06", ctx, "no confirmed swing or ATR")
    last = ctx.bars[-1]
    ev = []
    if hi and last.close > ctx.bars[hi[-1]].high + 0.1 * a and (last.high - last.low) >= a:
        ev.append(f"close above swing high {ctx.bars[hi[-1]].high:.5f}")
        return message("TA06", ctx, Rec.BUY, 0.45, "upside breakout of a confirmed swing", ev)
    if lo and last.close < ctx.bars[lo[-1]].low - 0.1 * a and (last.high - last.low) >= a:
        ev.append(f"close below swing low {ctx.bars[lo[-1]].low:.5f}")
        return message("TA06", ctx, Rec.SELL, 0.45, "downside breakout of a confirmed swing", ev)
    return message("TA06", ctx, Rec.WAIT, 0.2, "no swing breakout on the last closed bar", ev)


def ai01_regime(ctx: AnalysisContext) -> AgentMessage:
    if len(ctx.bars) < 40:
        return abstain("AI01", ctx, "fewer than 40 closed bars")
    a = atr(ctx.bars, 14)
    ranges = [b.high - b.low for b in ctx.bars[-40:]]
    if a is None or not ranges:
        return abstain("AI01", ctx, "ATR undefined")
    mid = sorted(ranges)[len(ranges) // 2]
    trend = _trend(ctx.bars)
    if a > 1.3 * mid and trend in (1, -1):
        label = "trending, expanded range"
        rec = Rec.BUY if trend == 1 else Rec.SELL
        return message("AI01", ctx, rec, 0.35, label, [f"ATR={a:.5f}", f"median range={mid:.5f}"])
    if a < 0.7 * mid:
        return message("AI01", ctx, Rec.WAIT, 0.4, "compressed / ranging regime",
                       [f"ATR={a:.5f}", f"median range={mid:.5f}"])
    return message("AI01", ctx, Rec.WAIT, 0.25, "regime mixed or transitional",
                   [f"ATR={a:.5f}", f"median range={mid:.5f}"])


def ai03_adaptive(ctx: AnalysisContext) -> AgentMessage:
    learning = ctx.extras.get("learning")
    if not learning:
        return abstain("AI03", ctx, "no isolated weight-replay result in this run")
    ev = [str(x) for x in (learning.get("evidence") or [])][:8]
    why = str(learning.get("summary") or "isolated version comparison only; not applied")
    return message("AI03", ctx, Rec.WAIT, 0.3, why, ev or ["shadow comparison only"])


def ai04_adversarial(ctx: AnalysisContext) -> AgentMessage:
    if len(ctx.bars) < 25:
        return abstain("AI04", ctx, "fewer than 25 closed bars")
    trend = _trend(ctx.bars)
    last = ctx.bars[-1]
    a = atr(ctx.bars, 14) or 0.0
    ev = []
    if trend == 1 and last.close < last.open and (last.open - last.close) >= 0.6 * max(a, 1e-12):
        ev.append("last bar is a large down close against an up trend")
    if trend == -1 and last.close > last.open and (last.close - last.open) >= 0.6 * max(a, 1e-12):
        ev.append("last bar is a large up close against a down trend")
    if ctx.spread is not None and a and ctx.spread > 0.25 * a:
        ev.append(f"spread {ctx.spread:g} is wide vs ATR {a:g}")
    if not ev:
        return message("AI04", ctx, Rec.WAIT, 0.2,
                       "no contrary evidence on the last closed bar", [])
    return message("AI04", ctx, Rec.WAIT, 0.45,
                   "contrary evidence; reduce confidence in a chase", ev)


# -------------------------------------------------------------- risk / execution (L4 may BLOCK)


def _risk_ctx(ctx: AnalysisContext) -> dict[str, Any]:
    raw = ctx.extras.get("risk_context") or {}
    return raw if isinstance(raw, dict) else {}


def _risk_already_blocked(ctx: AnalysisContext) -> bool:
    verdict = _risk_ctx(ctx).get("verdict") or ctx.extras.get("risk_verdict") or ""
    return str(verdict).upper() == "BLOCK"


def rk01_risk(ctx: AnalysisContext) -> AgentMessage:
    if _risk_already_blocked(ctx):
        return message("RK01", ctx, Rec.BLOCK, 1.0,
                       "Risk Brain already blocked; this shadow copy agrees and cannot override",
                       ["risk_verdict=BLOCK"])
    info = _risk_ctx(ctx)
    limits = RiskLimits()
    ev = []
    if info.get("kill_switch"):
        return message("RK01", ctx, Rec.BLOCK, 1.0, "kill switch is engaged", ["kill_switch"])
    if "equity" not in info and "daily_pnl_pct" not in info and "kill_switch" not in info:
        return message("RK01", ctx, Rec.WAIT, 0.0,
                       "no account risk snapshot in this run; not approving anything",
                       ["risk context missing"])
    daily = info.get("daily_pnl_pct")
    if daily is None:
        ev.append("daily P&L unknown")
        return message("RK01", ctx, Rec.WAIT, 0.0,
                       "daily P&L is unknown; missing data is not a clean account", ev)
    loss = -min(0.0, float(daily))
    ev.append(f"daily_pnl_pct={daily}")
    if loss >= limits.max_daily_loss_pct:
        return message("RK01", ctx, Rec.BLOCK, 1.0,
                       f"daily loss {loss:.2f}% reached limit {limits.max_daily_loss_pct}%", ev)
    return message("RK01", ctx, Rec.WAIT, 0.5,
                   "account checks passed; this shadow gate does not approve trades", ev)


def rk03_sizing(ctx: AnalysisContext) -> AgentMessage:
    info = _risk_ctx(ctx)
    equity = info.get("equity")
    plan = sl_tp(ctx, "BUY")
    if equity is None or float(equity or 0) <= 0:
        return abstain("RK03", ctx, "account equity is unknown; size not guessed")
    if plan is None:
        return abstain("RK03", ctx, "no stop distance, so size is undefined")
    risk_pct = 0.5
    risk_amount = float(equity) * risk_pct / 100.0
    ev = [f"equity={float(equity):.2f}", f"risk {risk_pct}% = {risk_amount:.2f}",
          f"stop distance {abs(plan['entry'] - plan['stop_loss']):.5f}"]
    return message("RK03", ctx, Rec.WAIT, 0.4, "deterministic size proposal; not an order", ev)


def rk04_portfolio(ctx: AnalysisContext) -> AgentMessage:
    if _risk_already_blocked(ctx):
        return message("RK04", ctx, Rec.BLOCK, 1.0, "Risk Brain already blocked; cannot override",
                       ["risk_verdict=BLOCK"])
    info = _risk_ctx(ctx)
    opens = info.get("open_symbols")
    if opens is None:
        opens = ctx.extras.get("open_symbols")
    if opens is None:
        return message("RK04", ctx, Rec.WAIT, 0.0,
                       "open positions unknown; not treating the book as empty",
                       ["open_symbols missing"])
    symbols = [str(s).upper() for s in opens]
    cap = RiskLimits().max_open_positions
    ev = [f"open={symbols or 'none'}", f"cap={cap}"]
    if ctx.symbol.upper() in symbols:
        return message("RK04", ctx, Rec.BLOCK, 0.9,
                       f"{ctx.symbol} already has an open position", ev)
    if len(symbols) >= cap:
        return message("RK04", ctx, Rec.BLOCK, 0.9,
                       f"{len(symbols)} positions open (cap {cap})", ev)
    return message("RK04", ctx, Rec.WAIT, 0.4, "portfolio caps not breached", ev)


def rk05_ftmo(ctx: AnalysisContext) -> AgentMessage:
    if _risk_already_blocked(ctx):
        return message("RK05", ctx, Rec.BLOCK, 1.0, "Risk Brain already blocked; cannot override",
                       ["risk_verdict=BLOCK"])
    challenge = ctx.extras.get("challenge") or {}
    if not challenge:
        return abstain("RK05", ctx, "no challenge account snapshot in this run")
    ev = [f"{k}={v}" for k, v in challenge.items() if k in
          ("daily_loss_pct", "max_loss_pct", "status", "label") and v is not None]
    if challenge.get("breach") or challenge.get("status") in {"failed", "breached"}:
        return message("RK05", ctx, Rec.BLOCK, 1.0, "challenge rules already breached", ev)
    daily = challenge.get("daily_loss_pct")
    limit = challenge.get("daily_loss_limit_pct")
    if daily is not None and limit is not None and float(daily) >= float(limit):
        return message("RK05", ctx, Rec.BLOCK, 1.0, "daily loss at the challenge limit", ev)
    return message("RK05", ctx, Rec.WAIT, 0.4, "challenge snapshot does not show a breach", ev)


def ex01_execution(ctx: AnalysisContext) -> AgentMessage:
    return message(
        "EX01", ctx, Rec.WAIT, 1.0,
        "shadow cycle only: this role will not send an order to MetaTrader",
        ["paper/shadow", "no command file", "live execution is not connected to agents"],
    )


def ex02_slippage(ctx: AnalysisContext) -> AgentMessage:
    if _risk_already_blocked(ctx):
        return message("EX02", ctx, Rec.BLOCK, 1.0,
                       "Risk Brain already blocked this; EX02 cannot override it",
                       ["risk_verdict=BLOCK"])
    fills = list(ctx.extras.get("slippage_fills") or [])
    cap = ctx.extras.get("slippage_cap_points", DEFAULT_CAP_POINTS)
    point = ctx.extras.get("point")
    verdict = decide(fills, symbol=ctx.symbol, cap_points=float(cap),
                     default_point=float(point) if point else None,
                     risk_verdict=str(ctx.extras.get("risk_verdict") or "") or None)
    rec = Rec.BLOCK if verdict.blocks else Rec.WAIT
    return message("EX02", ctx, rec, 0.8 if verdict.blocks else 0.5,
                   verdict.analysis, verdict.evidence)


def ex03_guardian(ctx: AnalysisContext) -> AgentMessage:
    opens = ctx.extras.get("open_symbols")
    if opens is None:
        opens = (_risk_ctx(ctx).get("open_symbols"))
    if opens is None:
        return message("EX03", ctx, Rec.WAIT, 0.0,
                       "no position snapshot in this run; not inventing an empty book",
                       ["open_symbols missing"])
    held = ctx.symbol.upper() in {str(s).upper() for s in opens}
    ev = [f"open_symbols={list(opens)}"]
    if held:
        return message("EX03", ctx, Rec.WAIT, 0.5, f"{ctx.symbol} is open on the snapshot", ev)
    return message("EX03", ctx, Rec.WAIT, 0.4, f"{ctx.symbol} is not in the open snapshot", ev)


def ex04_journal(ctx: AnalysisContext) -> AgentMessage:
    return message(
        "EX04", ctx, Rec.WAIT, 0.3,
        "shadow cycle: no new journal row is written here; audit stays on the execution path",
        ["read-only in this cycle"],
    )


def ex05_commander(ctx: AnalysisContext) -> AgentMessage:
    if _risk_already_blocked(ctx) or _risk_ctx(ctx).get("kill_switch"):
        return message("EX05", ctx, Rec.BLOCK, 1.0,
                       "kill switch or Risk Brain BLOCK; commander will not advance an intent",
                       ["blocked"])
    return message(
        "EX05", ctx, Rec.WAIT, 1.0,
        "paper/shadow commander idle; will not advance an intent without Risk Brain approval",
        ["no live send"],
    )


ANALYZERS = {
    "TA01": ta01_technical,
    "TA04": ta04_trend,
    "TA05": ta05_reversal,
    "TA06": ta06_breakout,
    "AI01": ai01_regime,
    "AI03": ai03_adaptive,
    "AI04": ai04_adversarial,
    "RK01": rk01_risk,
    "RK03": rk03_sizing,
    "RK04": rk04_portfolio,
    "RK05": rk05_ftmo,
    "EX01": ex01_execution,
    "EX02": ex02_slippage,
    "EX03": ex03_guardian,
    "EX04": ex04_journal,
    "EX05": ex05_commander,
}
