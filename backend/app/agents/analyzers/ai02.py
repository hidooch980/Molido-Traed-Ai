"""AI02: a deliberately simple, honest baseline forecaster.

Question: given the sign of the last `lookback`-bar return, how often did the
next bar close higher? Estimated only from pairs whose outcome bar had already
closed (walk-forward by construction), with Laplace smoothing, and scored by
its own Brier score against the base rate. It recommends a direction only when
it beats the base rate on its own history *and* the edge is large enough. It is
a baseline to beat, not a claim of predictive power.
"""

from __future__ import annotations

from app.agents.analyzers.bars import AnalysisContext
from app.agents.analyzers.common import abstain, message
from app.agents.analyzers.ml import train_eval
from app.agents.messages import AgentMessage
from app.agents.messages import Recommendation as Rec

MIN_PAIRS = 100
MIN_EDGE = 0.05


def _pairs(closes: list[float], lookback: int) -> list[tuple[int, int]]:
    """(signal, outcome) with signal = sign of past return, outcome = next bar up."""
    out = []
    for i in range(lookback, len(closes) - 1):
        past = closes[i] - closes[i - lookback]
        if past == 0:
            continue
        out.append((1 if past > 0 else -1, 1 if closes[i + 1] > closes[i] else 0))
    return out


def forecast(closes: list[float], lookback: int = 5) -> dict[str, float] | None:
    pairs = _pairs(closes, lookback)
    if len(pairs) < MIN_PAIRS:
        return None
    base = sum(o for _, o in pairs) / len(pairs)
    p_up = {s: (sum(o for sig, o in pairs if sig == s) + 1)
            / (sum(1 for sig, _ in pairs if sig == s) + 2) for s in (1, -1)}
    # In-history calibration of each rule (walk-forward refit would be stricter;
    # this is reported as in-sample Brier and labelled so).
    brier_model = sum((p_up[s] - o) ** 2 for s, o in pairs) / len(pairs)
    brier_base = sum((base - o) ** 2 for _, o in pairs) / len(pairs)
    now = closes[-1] - closes[-1 - lookback]
    signal = 0 if now == 0 else (1 if now > 0 else -1)
    return {"n": len(pairs), "base_rate": base, "p_up": p_up.get(signal, base),
            "signal": signal, "brier_model": brier_model, "brier_base": brier_base}


MIN_ML_BARS = 300
MIN_SKILL = 0.002  # OOS Brier improvement over the base rate required to speak


def ai02_forecast(ctx: AnalysisContext) -> AgentMessage:
    if len(ctx.bars) >= MIN_ML_BARS:
        m = train_eval(list(ctx.bars))
        if m is not None:
            ev = [f"logistic regression, train {m['n_train']} / test {m['n_test']} "
                  "(chronological)",
                  f"P(next up)={m['p_up']:.3f}",
                  f"Brier OOS {m['brier_oos']:.4f} vs base {m['brier_base_oos']:.4f}",
                  f"accuracy OOS {m['accuracy_oos']:.3f}, log loss {m['logloss_oos']:.4f}"]
            skill = m["brier_base_oos"] - m["brier_oos"]
            edge = m["p_up"] - 0.5
            if skill < MIN_SKILL or abs(edge) < MIN_EDGE:
                return message("AI02", ctx, Rec.WAIT, 0.2,
                               "model shows no out-of-sample skill or no edge now", ev)
            return message("AI02", ctx, Rec.BUY if edge > 0 else Rec.SELL, min(0.7, abs(edge)),
                           "logistic model with out-of-sample skill (shadow, unvalidated live)",
                           ev)
    f = forecast(ctx.closes)
    if f is None:
        return abstain("AI02", ctx, f"fewer than {MIN_PAIRS} resolved history pairs")
    ev = [f"n={int(f['n'])}", f"P(next up)={f['p_up']:.3f}", f"base rate {f['base_rate']:.3f}",
          f"Brier model {f['brier_model']:.4f} vs base {f['brier_base']:.4f} (in-sample)"]
    beats = f["brier_model"] < f["brier_base"]
    edge = f["p_up"] - 0.5
    if f["signal"] == 0 or not beats or abs(edge) < MIN_EDGE:
        return message("AI02", ctx, Rec.WAIT, 0.2, "baseline shows no usable edge", ev)
    return message("AI02", ctx, Rec.BUY if edge > 0 else Rec.SELL, abs(edge),
                   "baseline sign-persistence forecast (not a validated model)", ev)
